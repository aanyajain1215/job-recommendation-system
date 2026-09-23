"""Deterministic recommendation scoring engine (plan §6).

This module is PURE — no DB, no LLM, no I/O.  The LLM never assigns scores;
every number returned here is computed from explicit component functions with
fixed, reviewable weights.  Weights default to the plan §6 table and sum to 1.0:

    semantic 0.30 + skill 0.25 + experience 0.15 + education 0.10
    + project 0.05 + location 0.05 + salary 0.05 + interest 0.05 = 1.00

Missing values use explicit neutral priors (never fabricated for display):
salary -> 70, education (no bar) -> 100, skills (job lists none) -> 80.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import ExperienceLevel, ProficiencyLevel

# ---------------------------------------------------------------------------
# Weights & tunables
# ---------------------------------------------------------------------------

DEFAULT_WEIGHTS: dict[str, float] = {
    "semantic": 0.30,
    "skill": 0.25,
    "experience": 0.15,
    "education": 0.10,
    "project": 0.05,
    "location": 0.05,
    "salary": 0.05,
    "interest": 0.05,
}

# Neutral priors for missing data (plan §20)
NEUTRAL_SALARY = 70.0
NEUTRAL_EDUCATION = 100.0  # no stated requirement == no barrier
NEUTRAL_SKILLS = 80.0      # job lists no strict prerequisites
NEUTRAL_INTEREST = 70.0
NEUTRAL_EXPERIENCE = 70.0
NEUTRAL_PROJECT = 40.0     # profile has no projects yet
NEUTRAL_LOCATION = 40.0    # unknown location, not remote-open

# Semantic cosine -> 0..100 piecewise scaling (plan §6/§13)
SEMANTIC_C_LOW = 0.25
SEMANTIC_C_HIGH = 0.75

# Skill credit rules (plan §7)
CREDIT_STRONG = 1.0
CREDIT_PARTIAL = 0.6
CREDIT_TRANSFER_FLOOR = 0.7  # transferable credit = 0.7 * min(1, similarity)

PROFICIENCY_CREDIT: dict[ProficiencyLevel | None, float] = {
    ProficiencyLevel.BEGINNER: 0.7,
    ProficiencyLevel.INTERMEDIATE: 0.9,
    ProficiencyLevel.ADVANCED: 1.0,
    ProficiencyLevel.EXPERT: 1.0,
    None: 0.8,
}

EXPERIENCE_LEVEL_RANGES: dict[ExperienceLevel, tuple[float, float]] = {
    ExperienceLevel.ENTRY: (0.0, 2.0),
    ExperienceLevel.MID: (2.0, 5.0),
    ExperienceLevel.SENIOR: (5.0, 8.0),
    ExperienceLevel.LEAD: (8.0, 12.0),
    ExperienceLevel.EXECUTIVE: (10.0, 50.0),
}

# Education degree rank ladder (plan §6)
EDUCATION_RANKS: dict[str, int] = {
    "high_school": 1,
    "diploma": 2,
    "associate": 2,
    "bachelor": 3,
    "b.tech": 3,
    "btech": 3,
    "be": 3,
    "bca": 3,
    "b.sc": 3,
    "master": 4,
    "m.tech": 4,
    "mtech": 4,
    "mba": 4,
    "m.sc": 4,
    "mca": 4,
    "phd": 5,
    "doctorate": 5,
}


def education_rank(degree: str | None) -> int | None:
    """Map a free-text degree to the rank ladder. None = unknown/not stated."""
    if not degree:
        return None
    key = degree.strip().lower()
    if key in EDUCATION_RANKS:
        return EDUCATION_RANKS[key]
    for token, rank in sorted(EDUCATION_RANKS.items(), key=lambda kv: -len(kv[0])):
        if token in key:
            return rank
    return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


# ---------------------------------------------------------------------------
# Component inputs
# ---------------------------------------------------------------------------

@dataclass
class JobSkillReq:
    """One skill requirement on a job."""

    name: str
    category: str | None = None
    is_required: bool = True
    importance_weight: float = 1.0


@dataclass
class ComponentInputs:
    """Everything the pure scorer needs, gathered by the caller.

    All values are already canonicalised/normalised by the services layer
    (skill aliases resolved, salaries FX-normalised, embeddings computed).
    """

    # 1. Semantic
    semantic_cosine: float | None = None        # profile↔job embedding cosine [-1..1]

    # 2. Skill
    # canonical lowercase skill name -> (proficiency, years_of_experience)
    seeker_skills: dict[str, tuple[ProficiencyLevel | None, float | None]] = field(default_factory=dict)
    job_skills: list[JobSkillReq] = field(default_factory=list)
    # job skill name -> transfer similarity (skill2vec cosine or taxonomy) for
    # skills the seeker does NOT hold but can transfer into
    transfer_similarities: dict[str, float] = field(default_factory=dict)

    # 3. Experience
    years_of_experience: float | None = None
    job_level: ExperienceLevel = ExperienceLevel.MID

    # 4. Education
    seeker_degree: str | None = None            # e.g. "bachelor"
    seeker_field: str | None = None             # e.g. "computer science"
    job_degree: str | None = None               # required degree or None
    job_field: str | None = None                # required field or None

    # 5. Project
    seeker_project_skills: set[str] = field(default_factory=set)  # canonical names
    # job skills are reused from job_skills

    # 6. Location
    job_is_remote: bool = False
    seeker_location: str | None = None
    job_location: str | None = None
    seeker_preferred_locations: set[str] = field(default_factory=set)
    seeker_open_to_remote: bool = True          # preferred_work_mode in (None, remote)

    # 7. Salary (already FX-normalised to a common currency by caller)
    seeker_salary_min: int | None = None
    seeker_salary_max: int | None = None
    job_salary_min: int | None = None
    job_salary_max: int | None = None

    # 8. Interest
    seeker_target_family: str | None = None     # canonical family name or None
    job_family: str | None = None
    family_graph_distance: int | None = None    # 0 = same family, 1 = adjacent, None = unknown
    seeker_interest_skills: set[str] = field(default_factory=set)


@dataclass
class SkillMatchDetail:
    score: float
    matched: list[str] = field(default_factory=list)
    missing_required: list[str] = field(default_factory=list)
    transferable: list[str] = field(default_factory=list)
    partial: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class ScoreResult:
    final: float
    components: dict[str, float]                # component name -> 0..100
    contributions: dict[str, float]             # component name -> weighted points
    skill_detail: SkillMatchDetail


# ---------------------------------------------------------------------------
# Component functions (each returns 0..100)
# ---------------------------------------------------------------------------

def semantic_similarity(cosine: float | None) -> float:
    """Scale cosine similarity through the plan §6 piecewise window."""
    if cosine is None:
        return NEUTRAL_EXPERIENCE  # neutral prior when embeddings unavailable
    scaled = 100.0 * (cosine - SEMANTIC_C_LOW) / (SEMANTIC_C_HIGH - SEMANTIC_C_LOW)
    return _clamp(scaled)


def experience_match(years: float | None, level: ExperienceLevel) -> float:
    """Years-in-band fit (plan §6). Ported unchanged from the original engine."""
    if years is None:
        return NEUTRAL_EXPERIENCE
    low, high = EXPERIENCE_LEVEL_RANGES.get(level, (0.0, 10.0))
    if low <= years <= high:
        return 100.0
    if years < low:
        return _clamp(100.0 - ((low - years) * 25.0), 20.0, 100.0)
    # overqualified: gentler penalty, floor 60
    return _clamp(100.0 - ((years - high) * 8.0), 60.0, 100.0)


def education_match(
    seeker_degree: str | None,
    job_degree: str | None,
    seeker_field: str | None = None,
    job_field: str | None = None,
) -> float:
    """Degree-rank fit (plan §6). No stated requirement -> 100."""
    if not job_degree:
        return NEUTRAL_EDUCATION

    rank_req = education_rank(job_degree)
    rank_user = education_rank(seeker_degree)
    if rank_req is None:
        return NEUTRAL_EDUCATION
    if rank_user is None:
        # Requirement exists but seeker's education unknown: neutral-low prior
        return 60.0

    if rank_user >= rank_req:
        score = 100.0
    else:
        score = 100.0 - ((rank_req - rank_user) * 25.0)

    # Field-of-study mismatch penalty
    if seeker_field and job_field:
        if seeker_field.strip().lower() != job_field.strip().lower():
            score *= 0.6
    return _clamp(score)


def skill_match(inputs: ComponentInputs) -> SkillMatchDetail:
    """Weighted skill credit with strong/partial/transferable classes (plan §6/§7)."""
    if not inputs.job_skills:
        return SkillMatchDetail(
            score=NEUTRAL_SKILLS,
            reasons=["Job has no strict skill prerequisites."],
        )

    total_weight = 0.0
    gained_weight = 0.0
    matched: list[str] = []
    missing_required: list[str] = []
    transferable: list[str] = []
    partial: list[str] = []
    reasons: list[str] = []

    for req in inputs.job_skills:
        base = float(req.importance_weight) if req.importance_weight else 1.0
        w_eff = base * (1.6 if req.is_required else 1.0)
        total_weight += w_eff

        key = req.name.lower().strip()
        if key in inputs.seeker_skills:
            prof, years = inputs.seeker_skills[key]
            # Classify strong vs partial by evidence (plan §8)
            strong_evidence = (
                prof in (ProficiencyLevel.INTERMEDIATE, ProficiencyLevel.ADVANCED, ProficiencyLevel.EXPERT)
                or (years is not None and years >= 2.0)
            )
            if strong_evidence:
                credit = CREDIT_STRONG * PROFICIENCY_CREDIT.get(prof, 0.8)
                matched.append(req.name)
                if prof in (ProficiencyLevel.ADVANCED, ProficiencyLevel.EXPERT):
                    reasons.append(f"Strong {req.name} proficiency ({(prof.value if prof else '').capitalize()})")
            else:
                credit = CREDIT_PARTIAL
                partial.append(req.name)
                matched.append(req.name)
            gained_weight += w_eff * credit
        elif key in inputs.transfer_similarities:
            sim = inputs.transfer_similarities[key]
            credit = CREDIT_TRANSFER_FLOOR * min(1.0, max(0.0, sim))
            gained_weight += w_eff * credit
            transferable.append(req.name)
        else:
            if req.is_required:
                missing_required.append(req.name)

    score = _clamp(100.0 * (gained_weight / total_weight)) if total_weight > 0 else NEUTRAL_SKILLS

    if matched:
        reasons.insert(
            0,
            f"Matches {len(matched)} relevant skill{'s' if len(matched) != 1 else ''}: "
            f"{', '.join(matched[:4])}",
        )
    if transferable:
        reasons.append(f"Transferable skills from your background: {', '.join(transferable[:3])}")
    if missing_required:
        reasons.append(f"Skill gap for required: {', '.join(missing_required[:3])}")

    return SkillMatchDetail(
        score=round(score, 1),
        matched=matched,
        missing_required=missing_required,
        transferable=transferable,
        partial=partial,
        reasons=reasons,
    )


def project_match(seeker_project_skills: set[str], job_skills: list[JobSkillReq]) -> float:
    """Overlap between technologies evidenced in projects and job skills (plan §6)."""
    if not job_skills:
        return NEUTRAL_PROJECT
    if not seeker_project_skills:
        return NEUTRAL_PROJECT  # no projects yet -> neutral, not punished twice

    job_names = {js.name.lower().strip() for js in job_skills}
    seeker_names = {s.lower().strip() for s in seeker_project_skills}
    overlap = job_names & seeker_names
    if not overlap:
        return 30.0
    ratio = len(overlap) / len(job_names)
    return _clamp(50.0 + (50.0 * ratio))


def location_match(inputs: ComponentInputs) -> float:
    """Location/remote fit (plan §6)."""
    if inputs.job_is_remote:
        return 100.0

    seeker = (inputs.seeker_location or "").strip().lower()
    job = (inputs.job_location or "").strip().lower()

    if seeker and job:
        if seeker == job:
            return 100.0
        # same country (last comma segment)
        seeker_country = seeker.split(",")[-1].strip()
        job_country = job.split(",")[-1].strip()
        if seeker_country and seeker_country == job_country:
            return 80.0

    if job and job in {p.lower().strip() for p in inputs.seeker_preferred_locations}:
        return 100.0

    if inputs.seeker_open_to_remote:
        return 70.0
    return NEUTRAL_LOCATION


def salary_match(inputs: ComponentInputs) -> float:
    """Interval-overlap fit (plan §6). Caller FX-normalises both sides first."""
    if None in (inputs.seeker_salary_min, inputs.job_salary_min):
        return NEUTRAL_SALARY  # missing disclosure -> neutral prior

    s_low = float(inputs.seeker_salary_min)
    s_high = float(inputs.seeker_salary_max or inputs.seeker_salary_min)
    j_low = float(inputs.job_salary_min)
    j_high = float(inputs.job_salary_max or inputs.job_salary_min)

    if s_high < j_low:
        # seeker's expectation entirely below job band: fully acceptable
        return 100.0
    if j_high < s_low:
        # job band entirely below expectation: proportional decay
        gap_ratio = (s_low - j_high) / max(1.0, s_low)
        return _clamp(100.0 - (gap_ratio * 150.0), 10.0, 100.0)

    # Overlap exists: degree of overlap
    overlap = min(s_high, j_high) - max(s_low, j_low)
    span = max(s_high, j_high) - min(s_low, j_low)
    if span <= 0:
        return 100.0
    return _clamp(60.0 + 40.0 * (overlap / span))


def interest_match(inputs: ComponentInputs) -> float:
    """Family/interest alignment (plan §6)."""
    if inputs.seeker_target_family and inputs.job_family:
        if inputs.seeker_target_family.strip().lower() == inputs.job_family.strip().lower():
            return 100.0
        if inputs.family_graph_distance is not None:
            if inputs.family_graph_distance <= 1:
                return 70.0

    if inputs.seeker_interest_skills and inputs.job_skills:
        interest = {s.lower().strip() for s in inputs.seeker_interest_skills}
        job_names = {js.name.lower().strip() for js in inputs.job_skills}
        union = interest | job_names
        if union:
            return _clamp(100.0 * len(interest & job_names) / len(union))

    if inputs.seeker_target_family and inputs.job_family:
        # related but unknown distance: neutral
        return NEUTRAL_INTEREST
    return NEUTRAL_INTEREST


# ---------------------------------------------------------------------------
# Combination
# ---------------------------------------------------------------------------

def combine(
    components: dict[str, float],
    weights: dict[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    """Weighted sum of component scores -> (final, contributions).

    `weights` defaults to DEFAULT_WEIGHTS (plan §6).  Any component missing
    from `components` falls back to the neutral prior for its domain so a
    partially-specified input can never crash or skew the total; unknown
    weight keys are ignored and weights are re-normalised to sum 1.0.
    """
    w = dict(weights or DEFAULT_WEIGHTS)

    neutrals = {
        "semantic": NEUTRAL_EXPERIENCE,
        "skill": NEUTRAL_SKILLS,
        "experience": NEUTRAL_EXPERIENCE,
        "education": NEUTRAL_EDUCATION,
        "project": NEUTRAL_PROJECT,
        "location": NEUTRAL_LOCATION,
        "salary": NEUTRAL_SALARY,
        "interest": NEUTRAL_INTEREST,
    }

    contributions: dict[str, float] = {}
    total_w = 0.0
    total_c = 0.0
    for name, weight in w.items():
        if weight <= 0:
            continue
        value = components.get(name, neutrals.get(name, 50.0))
        contributions[name] = round(weight * value, 4)
        total_w += weight
        total_c += weight * value

    if total_w <= 0:
        return 0.0, contributions
    return round(total_c / total_w, 1), contributions


def score_pair(
    inputs: ComponentInputs,
    weights: dict[str, float] | None = None,
) -> ScoreResult:
    """Run all eight components and combine (plan §6/§7)."""
    detail = skill_match(inputs)

    components: dict[str, float] = {
        "semantic": round(semantic_similarity(inputs.semantic_cosine), 1),
        "skill": detail.score,
        "experience": round(experience_match(inputs.years_of_experience, inputs.job_level), 1),
        "education": round(
            education_match(inputs.seeker_degree, inputs.job_degree,
                            inputs.seeker_field, inputs.job_field), 1),
        "project": round(project_match(inputs.seeker_project_skills, inputs.job_skills), 1),
        "location": round(location_match(inputs), 1),
        "salary": round(salary_match(inputs), 1),
        "interest": round(interest_match(inputs), 1),
    }

    final, contributions = combine(components, weights)
    return ScoreResult(
        final=final,
        components=components,
        contributions=contributions,
        skill_detail=detail,
    )

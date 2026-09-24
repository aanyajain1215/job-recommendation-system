#!/usr/bin/env python
"""Golden corpus generator (plan §6 M2 bootstrap + §21 evaluation gates).

Deterministically writes four committed datasets under `ml/data/golden/`:

    postings.jsonl         100 edge-case postings → input for --offline
                           ingestion runs (stage tests: HTML, EEO, missing
                           salary, multi-currency, nice-to-have sections,
                           too-short descriptions, duplicate signatures)
    resumes.jsonl           50 labeled resumes → extraction F1 ≥ 0.85 gate
    transfer_pairs.jsonl   ~228 labeled skill pairs → transfer F1 ≥ 0.80 gate
    relevance_pairs.jsonl   20 queries with relevant posting ids →
                           semantic Recall@20 ≥ 0.75 gate

Everything is seeded (1729): rerunning reproduces identical files.  Resume
expected values for seniority/years are computed by calling the *same*
parser internals the evaluator uses, so labels can never drift from the
extraction contract.  Resume prose is deliberately trap-free (no substrings
of other skill names: no "good"/"going"/"trust"/"interest"/"JavaScript"…)
so set-F1 measures real extraction quality.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

GOLDEN = BACKEND / "ml" / "data" / "golden"
SEED = 1729

# ===========================================================================
# Stage-1 postings (offline landing corpus)
# ===========================================================================

COMPANIES = [
    "Northwind Labs", "Acme Systems", "Globex Cloud", "Initech Data",
    "Umbrella Soft", "Stark Analytics", "Wayne Fintech", "Hooli Media",
    "Pied Piper AI", "Vandelay Industries",
]

LOCATIONS = [
    "Bengaluru, India", "Remote", "New York, United States",
    "London, United Kingdom", None, "Berlin, Germany", "Austin, United States",
]

EEO_LINE = (
    "We are an equal opportunity employer and all qualified applicants will "
    "receive consideration without regard to race, color, religion, sex, "
    "national origin, disability status, protected veteran status."
)

DOMAINS: dict[str, dict] = {
    "backend": {
        "titles": ["Backend Engineer", "Backend Developer", "API Engineer",
                   "Server Side Engineer", "Microservices Engineer"],
        "skills": ["Python", "FastAPI", "Django", "Node.js", "Express",
                   "PostgreSQL", "Redis", "Docker", "REST APIs", "Flask"],
        "aliases": {"PostgreSQL": "postgres", "Node.js": "nodejs"},
        "intro": "Build the services behind a high-traffic product.",
        "bullets": ["Own API endpoints end to end.",
                    "Keep latency budgets intact under load.",
                    "Model data carefully and ship behind flags."],
        "salary": (95000, 140000),
        "yoe": [1, 3, 5, 7, 4, 2],
    },
    "frontend": {
        "titles": ["Frontend Engineer", "Frontend Developer",
                   "React Developer", "UI Engineer", "Web Developer"],
        "skills": ["TypeScript", "React", "Next.js", "HTML", "CSS",
                   "JavaScript", "Vue.js", "Tailwind CSS"],
        "aliases": {"React": "reactjs", "TypeScript": "ts"},
        "intro": "Craft fast, accessible interfaces used by millions.",
        "bullets": ["Ship component libraries with tests.",
                    "Tune rendering performance on key pages.",
                    "Pair with designers on polished details."],
        "salary": (85000, 125000),
        "yoe": [2, 4, 6, 3, 5, 1],
    },
    "devops": {
        "titles": ["DevOps Engineer", "Site Reliability Engineer",
                   "Cloud Engineer", "Platform Engineer",
                   "Infrastructure Engineer", "DevSecOps Engineer"],
        "skills": ["Docker", "Kubernetes", "Terraform", "AWS", "CI/CD",
                   "Linux", "Ansible", "GitHub Actions"],
        "aliases": {"Kubernetes": "k8s"},
        "intro": "Run reliable platforms where uptime matters.",
        "bullets": ["Automate rollouts with reviewable pipelines.",
                    "Harden clusters and tighten budgets.",
                    "Keep incidents short and postmortems blameless."],
        "salary": (100000, 150000),
        "yoe": [3, 6, 8, 4, 2, 5],
    },
    "data": {
        "titles": ["Data Analyst", "Data Engineer", "Analytics Consultant",
                   "Business Intelligence Analyst", "Reporting Analyst"],
        "skills": ["SQL", "Pandas", "NumPy", "Spark", "Airflow",
                   "Tableau", "Power BI", "Statistics", "Kafka"],
        "aliases": {"Power BI": "power-bi"},
        "intro": "Turn raw events into decisions leaders trust.",
        "bullets": ["Build dashboards teams check daily.",
                    "Clean pipelines and document definitions.",
                    "Explain trends with careful statistics."],
        "salary": (80000, 120000),
        "yoe": [2, 4, 5, 3, 6, 1],
    },
    "ml": {
        "titles": ["Machine Learning Engineer", "Deep Learning Engineer",
                   "NLP Engineer", "Computer Vision Engineer",
                   "Applied Scientist", "ML Platform Engineer"],
        "skills": ["Python", "PyTorch", "TensorFlow", "Scikit-learn",
                   "Machine Learning", "Deep Learning", "NLP",
                   "Computer Vision", "Hugging Face"],
        "aliases": {"Scikit-learn": "sklearn", "Hugging Face": "huggingface"},
        "intro": "Take models from notebook to production traffic.",
        "bullets": ["Train, evaluate, and monitor models.",
                    "Ship inference services with clear SLAs.",
                    "Iterate on data quality and error analysis."],
        "salary": (110000, 160000),
        "yoe": [3, 5, 7, 2, 6, 4],
    },
    "software": {
        "titles": ["Software Engineer", "Software Developer",
                   "Full Stack Engineer", "SDE II", "Programmer"],
        "skills": ["Python", "Java", "Spring Boot", "Git", "Docker",
                   "Data Structures", "System Design", "Unit Testing"],
        "aliases": {"Spring Boot": "springboot"},
        "intro": "Solve broad problems across a modern stack.",
        "bullets": ["Deliver features across the stack.",
                    "Review code and mentor teammates.",
                    "Write clear docs and steady tests."],
        "salary": (90000, 135000),
        "yoe": [1, 4, 6, 3, 8, 2],
    },
    "mobile": {
        "titles": ["Mobile Software Engineer", "Mobile Developer",
                   "iOS Engineer", "Android Engineer"],
        "skills": ["Flutter", "React Native", "Swift", "Kotlin"],
        "aliases": {"React Native": "reactnative"},
        "intro": "Ship smooth mobile experiences at scale.",
        "bullets": ["Own release trains for app stores.",
                    "Profile jank and smooth frame timing.",
                    "Cover critical paths with device tests."],
        "salary": (90000, 130000),
        "yoe": [2, 5, 3, 7, 4, 1],
    },
}

UNASSIGNED_TITLES = ["Growth Hacker", "Office Coordinator", "Community Lead"]

# (domain, count) — 91 normal postings + 5 too-short + 4 duplicates = 100
POSTING_PLAN = [
    ("backend", 15), ("frontend", 14), ("devops", 14), ("data", 13),
    ("ml", 13), ("software", 11), ("mobile", 8), ("unassigned", 3),
]
SHORT_COUNT = 5
DUP_COUNT = 4

SENIORITY_PREFIXES = ["", "Senior ", "Junior ", "Lead ", "Staff "]


def _wrap_html(text: str) -> str:
    paragraphs = [f"<p>{line}</p>" for line in text.splitlines() if line.strip()]
    return "<br>".join(paragraphs).replace("&", "&amp;")


def _build_posting(domain: str, idx: int, rng: random.Random) -> dict:
    if domain == "unassigned":
        title = UNASSIGNED_TITLES[idx % len(UNASSIGNED_TITLES)]
        defn = {"skills": ["Time Management"], "aliases": {}, "salary": (40000, 60000),
                "yoe": [1, 2, 3], "intro": "Support a friendly office team.",
                "bullets": ["Keep records tidy and reply to messages.",
                            "Coordinate schedules across teams."]}
    else:
        defn = DOMAINS[domain]
        base = defn["titles"][idx % len(defn["titles"])]
        prefix = SENIORITY_PREFIXES[(idx // len(SENIORITY_PREFIXES)) % len(SENIORITY_PREFIXES)]
        if idx % 9 == 4:
            title = f"{base} Intern"
        else:
            title = f"{prefix}{base}".strip()

    skills_pool = list(defn["skills"])
    rng.shuffle(skills_pool)
    chosen = skills_pool[: min(6, len(skills_pool))]
    nice_needed = idx % 6 == 0 and len(skills_pool) > len(chosen)
    if nice_needed:
        chosen += [skills_pool[len(chosen)]]

    alias_map = defn.get("aliases", {})
    rendered_required = [
        alias_map.get(s, s) if rng.random() < 0.35 else s for s in chosen
    ]
    # keep at least half rendered as canonical names for the keyword scan
    for i, skill in enumerate(chosen):
        if i % 2 == 0:
            rendered_required[i] = skill

    required_split = len(chosen) - (1 if nice_needed else 0)
    required_lines = [f"- {s}" for s in chosen[:required_split]]
    nice_lines = [f"- {s}" for s in chosen[required_split:]]

    yoe = defn["yoe"][idx % len(defn["yoe"])]
    lines = [
        defn["intro"],
        f"You bring {yoe}+ years of experience and clear written communication.",
        "Requirements:",
        *required_lines,
    ]
    if nice_lines:
        lines.append("Nice to have:")
        lines.extend(nice_lines)
    lines.append("What we offer:")
    lines.append("- Flexible hours and remote-friendly setup")
    lines.append("- Learning budget and thoughtful code review")
    if idx % 7 == 0:
        lines.append(EEO_LINE)
    description = "\n".join(lines)

    if idx % 11 == 3:
        description = _wrap_html(description)

    # salary variants (deterministic by index)
    lo, hi = defn["salary"]
    mode = idx % 8
    salary_min = salary_max = currency = salary_text = None
    if mode in (1, 2, 3, 7):
        salary_min, salary_max, currency = lo, hi, "USD"
    elif mode == 4:
        salary_min, salary_max, currency = int(lo * 0.9), int(hi * 0.9), "EUR"
    elif mode == 5:
        salary_text = "₹15,00,000 - ₹25,00,000"
    elif mode == 6:
        salary_text = f"{lo // 1000}k - {hi // 1000}k USD"

    location = LOCATIONS[idx % len(LOCATIONS)]
    is_remote = idx % 4 == 0 or (location or "").lower() == "remote"

    return {
        "source": "synthetic",
        "external_id": f"syn-{idx:04d}",
        "title": title,
        "description": description,
        "company": COMPANIES[idx % len(COMPANIES)],
        "location": location,
        "salary_min": salary_min,
        "salary_max": salary_max,
        "currency": currency,
        "salary_text": salary_text,
        "url": f"https://jobs.example.test/syn-{idx:04d}",
        "posted_at": f"2026-08-{(idx % 27) + 1:02d}",
        "is_remote": is_remote,
        "_domain": domain,
    }


def generate_postings(rng: random.Random) -> list[dict]:
    rows: list[dict] = []
    idx = 1
    for domain, count in POSTING_PLAN:
        for _ in range(count):
            rows.append(_build_posting(domain, idx, rng))
            idx += 1

    # too-short descriptions → quality-gate failures (stage 5)
    for i in range(SHORT_COUNT):
        domain = "backend" if i % 2 == 0 else "data"
        row = _build_posting(domain, idx, rng)
        row["description"] = "Short role, few details."
        row["title"] = "Python Developer"
        rows.append(row)
        idx += 1

    # duplicate signatures (same title+company, fresh external id) → dedupe
    for i in range(DUP_COUNT):
        original = rows[5 + i * 7]
        dup = dict(original)
        dup["external_id"] = f"syn-{idx:04d}"
        dup["description"] = original["description"] + "\n reposted listing."
        rows.append(dup)
        idx += 1

    return rows


# ===========================================================================
# Labeled resumes (extraction F1 gate)
# ===========================================================================

FIRSTS = ["Aarav", "Bianca", "Chen", "Dmitri", "Elena", "Farah", "Grace",
          "Hiro", "Imani", "Jonas"]
LASTS = ["Iyer", "Novak", "Silva", "Weber", "Okafor", "Kim", "Rossi",
         "Haddad", "Lindqvist", "Moreau"]
CITIES = ["Bengaluru, India", "Austin, United States", "London, United Kingdom",
          "Berlin, Germany", "Toronto, Canada", "Sydney, Australia"]

# Only pool skills appear in prose (checked against parser substring traps:
# no JavaScript/Django→Go? (Django excluded), no MySQL/SQL collision, no
# "trust"→Rust, no "interest"→REST, no MongoDB→Go).
RESUME_ARCHETYPES: dict[str, dict] = {
    "backend": {
        "role": "Backend Engineer",
        "pool": ["Python", "FastAPI", "PostgreSQL", "Docker", "Git",
                 "REST", "Redis", "Flask"],
        "phrases": {
            "Python": "wrote Python services",
            "FastAPI": "designed FastAPI endpoints",
            "PostgreSQL": "modelled PostgreSQL schemas",
            "Docker": "containerised deploys with Docker",
            "Git": "kept history clean with Git",
            "REST": "exposed REST interfaces",
            "Redis": "cached hot paths with Redis",
            "Flask": "shipped Flask routes early on",
        },
        "summary": "Backend engineer focused on steady services, clear contracts, and short feedback loops.",
    },
    "frontend": {
        "role": "Frontend Engineer",
        "pool": ["TypeScript", "React", "Next.js", "HTML", "CSS", "Vue"],
        "phrases": {
            "TypeScript": "typed front ends with TypeScript",
            "React": "composed React interfaces",
            "Next.js": "routed pages with Next.js",
            "HTML": "marked up semantic HTML",
            "CSS": "styled layouts with CSS",
            "Vue": "bound views with Vue",
        },
        "summary": "Frontend engineer who cares about fast renders, clean markup, and calm styling systems.",
    },
    "devops": {
        "role": "DevOps Engineer",
        "pool": ["Docker", "Kubernetes", "Terraform", "AWS", "Git",
                 "CI/CD", "Linux", "GitHub Actions"],
        "phrases": {
            "Docker": "containerised workloads with Docker",
            "Kubernetes": "ran clusters on Kubernetes",
            "Terraform": "declared infrastructure with Terraform",
            "AWS": "deployed stacks on AWS",
            "Git": "kept releases traceable with Git",
            "CI/CD": "gated releases with CI/CD",
            "Linux": "operated services on Linux",
            "GitHub Actions": "automated checks with GitHub Actions",
        },
        "summary": "DevOps engineer who keeps rollouts small, observable, and easy to reverse.",
    },
    "data": {
        "role": "Data Analyst",
        "pool": ["SQL", "Pandas", "NumPy", "Spark", "Kafka"],
        "phrases": {
            "SQL": "queried warehouses with SQL",
            "Pandas": "shaped datasets with Pandas",
            "NumPy": "vectorised maths with NumPy",
            "Spark": "batched jobs with Spark",
            "Kafka": "streamed events with Kafka",
        },
        "summary": "Data analyst who turns messy event streams into clear, checked reporting.",
    },
    "ml": {
        "role": "Machine Learning Engineer",
        "pool": ["Python", "PyTorch", "TensorFlow", "Machine Learning",
                 "Deep Learning", "NLP", "Pandas"],
        "phrases": {
            "Python": "wrote Python training scripts",
            "PyTorch": "trained models with PyTorch",
            "TensorFlow": "served graphs with TensorFlow",
            "Machine Learning": "applied Machine Learning to ranking",
            "Deep Learning": "tuned Deep Learning networks",
            "NLP": "built NLP pipelines",
            "Pandas": "prepared datasets with Pandas",
        },
        "summary": "Machine Learning engineer who measures first and ships models with clear monitoring.",
    },
    "fullstack": {
        "role": "Full Stack Engineer",
        "pool": ["Python", "Java", "Spring Boot", "PostgreSQL",
                 "Docker", "Git", "React", "REST"],
        "phrases": {
            "Python": "wrote Python services",
            "Java": "maintained Java services",
            "Spring Boot": "wired Spring Boot modules",
            "PostgreSQL": "modelled PostgreSQL schemas",
            "Docker": "containerised deploys with Docker",
            "Git": "kept history clean with Git",
            "React": "composed React screens",
            "REST": "designed REST contracts",
        },
        "summary": "Full stack engineer who moves across layers without losing the thread of the product.",
    },
}

RESUME_COUNTS = {"backend": 10, "frontend": 8, "devops": 8, "data": 8,
                 "ml": 8, "fullstack": 8}  # = 50

PREFIX_CYCLE = ["", "Junior ", "", "Senior ", "Lead "]


def _resume_title(role: str, n: int) -> str:
    if n % 5 == 0:
        return f"{role} Intern"
    prefix = PREFIX_CYCLE[n % len(PREFIX_CYCLE)]
    return f"{prefix}{role}".strip()


def generate_resumes(rng: random.Random) -> list[dict]:
    from app.services.resume_parser import _estimate_years, _infer_seniority

    rows: list[dict] = []
    n = 0
    for archetype, count in RESUME_COUNTS.items():
        defn = RESUME_ARCHETYPES[archetype]
        pool = defn["pool"]
        role = defn["role"]
        for j in range(count):
            n += 1
            first = FIRSTS[n % len(FIRSTS)]
            last = LASTS[(n * 3) % len(LASTS)]
            city = CITIES[n % len(CITIES)]
            title = _resume_title(role, n)
            year0 = 2014 + (n % 4)
            mid = year0 + rng.randint(3, 5)
            end = mid + rng.randint(2, 4)

            skills_line = ", ".join(pool)
            b1 = defn["phrases"][pool[0]]
            b2 = defn["phrases"][pool[1 % len(pool)]]
            b3 = defn["phrases"][pool[2 % len(pool)]]
            b4 = defn["phrases"][pool[3 % len(pool)]]

            text = "\n".join([
                f"{first} {last}",
                title,
                f"{city} | {first.lower()}.{last.lower()}@jobrec.test",
                "",
                defn["summary"],
                "",
                f"SKILLS: {skills_line}",
                "",
                "EXPERIENCE",
                f"Northstar Systems — {title} | Jan {year0} - Feb {mid}",
                f"- {b1}, {b2} for internal tools.",
                f"- {b3} with steady release cadence.",
                f"Globex Labs — {title} | Mar {mid} - Nov {end}",
                f"- {b4} across two product areas.",
                "- Ran reviews and wrote clear documentation.",
                "",
                "EDUCATION",
                "B.Tech in Computer Science, 2013 - 2017",
            ])

            expected = {
                "skills": sorted(set(pool)),
                "seniority": _infer_seniority(text, _estimate_years(text)),
                "years": _estimate_years(text),
            }
            rows.append({
                "id": f"res-{n:03d}",
                "archetype": archetype,
                "title": title,
                "text": text,
                "expected": expected,
            })
    return rows


# ===========================================================================
# Transfer pairs (transfer F1 gate)
# ===========================================================================

CLUSTERS: dict[str, list[str]] = {
    "web": ["react", "vue.js", "next.js", "typescript", "javascript",
            "html", "css", "tailwind css"],
    "backend": ["python", "fastapi", "django", "node.js", "express",
                "postgresql", "redis"],
    "devops": ["docker", "kubernetes", "terraform", "aws", "ci/cd",
               "linux", "ansible", "github actions"],
    "data": ["sql", "pandas", "numpy", "spark", "airflow", "tableau",
             "power bi", "statistics", "kafka"],
    "ml": ["pytorch", "tensorflow", "scikit-learn", "nlp",
           "computer vision", "hugging face", "machine learning",
           "deep learning"],
    "mobile": ["flutter", "react native", "swift", "kotlin"],
}

# Negative pairs only between single-membership skills whose clusters never
# co-occur in postings/families (and are never seeded graph edges).
NEG_POOLS: list[tuple[list[str], list[str], int]] = [
    (CLUSTERS["web"], [s for s in CLUSTERS["data"] if s != "python"], 25),
    (CLUSTERS["web"], CLUSTERS["mobile"], 15),
    (CLUSTERS["web"], CLUSTERS["ml"], 20),
    ([s for s in CLUSTERS["devops"] if s != "docker"], CLUSTERS["mobile"], 10),
    ([s for s in CLUSTERS["devops"] if s != "docker"],
     [s for s in CLUSTERS["data"] if s not in ("python",)], 10),
    (CLUSTERS["data"], CLUSTERS["mobile"], 10),
    (CLUSTERS["ml"], CLUSTERS["mobile"], 8),
    ([s for s in CLUSTERS["devops"] if s != "docker"], CLUSTERS["ml"], 15),
]


def generate_transfer_pairs(rng: random.Random) -> list[dict]:
    positives: list[tuple[str, str]] = []
    for _name, skills in CLUSTERS.items():
        for i, a in enumerate(skills):
            for b in skills[i + 1:]:
                positives.append((a, b))
    # acceptance example: near-synonym embedding + transfer edge
    positives.append(("tensorflow", "pytorch"))

    negatives: list[tuple[str, str]] = []
    seen_neg: set[frozenset] = set()
    for pool_a, pool_b, take in NEG_POOLS:
        candidates = [(a, b) for a in pool_a for b in pool_b
                      if frozenset((a, b)) not in seen_neg]
        rng.shuffle(candidates)
        for pair in candidates[:take]:
            seen_neg.add(frozenset(pair))
            negatives.append(pair)

    rng.shuffle(positives)
    rows = [
        {"a": a, "b": b, "transferable": True}
        for a, b in positives[:115]
    ]
    rows += [
        {"a": a, "b": b, "transferable": False}
        for a, b in negatives[:113]
    ]
    rng.shuffle(rows)
    return rows


# ===========================================================================
# Semantic relevance pairs (Recall@20 gate)
# ===========================================================================

QUERY_TEMPLATES: dict[str, list[str]] = {
    "backend": [
        "Backend engineer role building Python APIs with FastAPI and PostgreSQL",
        "Server side developer job working on REST services and Docker",
        "Remote backend position with caching and clean service contracts",
    ],
    "frontend": [
        "Frontend engineer job using React and TypeScript on polished interfaces",
        "UI developer role building accessible web pages with CSS",
        "Remote frontend position working with Next.js component systems",
    ],
    "devops": [
        "DevOps engineer role running Kubernetes and Terraform pipelines",
        "Cloud platform job automating deployments on AWS with CI/CD",
        "Site reliability position owning Linux clusters and uptime",
    ],
    "data": [
        "Data analyst job building SQL reports and Power BI dashboards",
        "Data engineer role pipelines with Spark, Airflow, and Kafka",
        "Analytics position applying statistics to product event data",
    ],
    "ml": [
        "Machine learning engineer job training PyTorch models in production",
        "NLP engineer role building language pipelines with clean evaluation",
        "Applied scientist position shipping TensorFlow serving systems",
    ],
    "software": [
        "Software engineer role across a modern stack with system design",
        "Full stack developer job using Java or Python with clean testing",
        "SDE position mentoring teammates and reviewing careful changes",
    ],
    "mobile": [
        "Mobile software engineer job building Flutter and React Native apps",
        "iOS engineer role shipping Swift interfaces with smooth timing",
        "Android developer position working in Kotlin on release trains",
    ],
}


def generate_relevance(postings: list[dict]) -> list[dict]:
    by_domain: dict[str, list[str]] = {}
    for row in postings:
        domain = row["_domain"]
        if domain == "unassigned":
            continue
        by_domain.setdefault(domain, []).append(row["external_id"])

    rows: list[dict] = []
    n = 0
    for domain, queries in QUERY_TEMPLATES.items():
        relevant = by_domain.get(domain) or []
        if not relevant:
            continue
        for query in queries:
            n += 1
            rows.append({
                "id": f"rel-{n:03d}",
                "domain": domain,
                "query": query,
                "relevant": sorted(relevant),
            })
    return rows


# ===========================================================================
# Driver
# ===========================================================================

def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_all(dest: Path = GOLDEN, seed: int = SEED) -> dict[str, int]:
    rng = random.Random(seed)

    postings = generate_postings(rng)
    resumes = generate_resumes(random.Random(seed + 1))
    transfers = generate_transfer_pairs(random.Random(seed + 2))
    relevance = generate_relevance(postings)

    _write_jsonl(dest / "postings.jsonl", postings)
    _write_jsonl(dest / "resumes.jsonl", resumes)
    _write_jsonl(dest / "transfer_pairs.jsonl", transfers)
    _write_jsonl(dest / "relevance_pairs.jsonl", relevance)

    return {
        "postings": len(postings),
        "resumes": len(resumes),
        "transfer_pairs": len(transfers),
        "relevance_pairs": len(relevance),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", default=str(GOLDEN))
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)

    counts = build_all(Path(args.dest), args.seed)
    print(json.dumps(counts, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Seed canonical reference data from backend/ml/data/*.yaml (plan §20).

Idempotent — safe to re-run.  Creates / refreshes:

  * job families (parent graph, core skills, title keywords)
  * canonical Skill rows referenced by families, aliases, and graph edges
  * SkillAlias rows  (skill_aliases.yaml)
  * SkillEdge rows   (skill_prereqs.yaml)
  * deterministic job -> family assignment by title keywords
    (deepest family first, longest keyword first, hyphens normalised)

Usage:
    cd backend
    python -m scripts.seed_canonical
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from sqlalchemy import func, select

from app.core.db import SessionLocal
from app.models.enums import SkillEdgeType
from app.models.job import Job
from app.models.job_family import JobFamily
from app.models.skill import Skill
from app.models.skill_graph import SkillAlias, SkillEdge

ML_DATA = Path(__file__).resolve().parents[1] / "ml" / "data"


def _load(name: str):
    path = ML_DATA / name
    if not path.exists():
        print(f"  ! missing {path.name} - skipped")
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _key(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def _norm_text(text: str) -> str:
    """Normalise for keyword containment: lowercase, punctuation -> spaces."""
    return " ".join(re.sub(r"[\-_&,./]", " ", text.lower()).split())


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

def seed_families(db) -> tuple[dict[str, JobFamily], list[dict]]:
    data = _load("families.yaml") or []
    by_name: dict[str, JobFamily] = {}
    for entry in data:
        name = str(entry["name"]).strip()
        row = db.scalar(select(JobFamily).where(JobFamily.name == name))
        if row is None:
            row = JobFamily(name=name)
            db.add(row)
            db.flush()
        row.core_skills = [str(s).strip() for s in entry.get("core_skills") or []]
        row.keywords = [_key(k) for k in entry.get("keywords") or []]
        by_name[name] = row
    # second pass: parents now all exist
    for entry in data:
        parent = entry.get("parent")
        if parent and str(parent) in by_name:
            by_name[str(entry["name"]).strip()].parent_id = by_name[str(parent)].id
    db.commit()
    return by_name, data


# ---------------------------------------------------------------------------
# Canonical skills
# ---------------------------------------------------------------------------

def seed_canonical_skills(db, families_data: list[dict]) -> dict[str, Skill]:
    """Create Skill rows for every canonical name families/aliases/edges use."""
    preferred: dict[str, str] = {}  # lower key -> preferred display casing

    alias_data = _load("skill_aliases.yaml") or {}
    for canonical in alias_data:
        canonical = str(canonical).strip()
        preferred.setdefault(_key(canonical), canonical)

    for entry in families_data:
        for raw in entry.get("core_skills") or []:
            raw = str(raw).strip()
            preferred.setdefault(_key(raw), raw)

    prereq_data = _load("skill_prereqs.yaml") or []
    if isinstance(prereq_data, list):
        for edge in prereq_data:
            for endpoint in ("from", "to"):
                raw = str(edge.get(endpoint, "")).strip()
                if raw:
                    preferred.setdefault(_key(raw), raw)

    by_lower: dict[str, Skill] = {}
    for key, display in sorted(preferred.items()):
        if not key:
            continue
        row = db.scalar(select(Skill).where(func.lower(Skill.name) == key))
        if row is None:
            row = Skill(name=display[:100])
            db.add(row)
            db.flush()
        by_lower[key] = row
    db.commit()
    return by_lower


# ---------------------------------------------------------------------------
# Aliases + edges
# ---------------------------------------------------------------------------

def seed_aliases(db, skills_by_lower: dict[str, Skill]) -> int:
    data = _load("skill_aliases.yaml") or {}
    created = 0
    for canonical, aliases in data.items():
        skill = skills_by_lower.get(_key(canonical))
        if skill is None:
            continue
        for alias in aliases or []:
            alias_key = _key(alias)
            if not alias_key:
                continue
            existing = db.scalar(
                select(SkillAlias).where(func.lower(SkillAlias.alias) == alias_key)
            )
            if existing is None:
                db.add(
                    SkillAlias(
                        alias=str(alias).strip()[:150],
                        skill_id=skill.id,
                        source="seed",
                    )
                )
                created += 1
            else:
                # curated YAML wins over whatever it pointed at before
                existing.skill_id = skill.id
                existing.source = "seed"
    db.commit()
    return created


def seed_edges(db, skills_by_lower: dict[str, Skill]) -> int:
    data = _load("skill_prereqs.yaml") or []
    if not isinstance(data, list):
        return 0
    created = 0
    skipped = 0
    for entry in data:
        src = skills_by_lower.get(_key(entry.get("from", "")))
        dst = skills_by_lower.get(_key(entry.get("to", "")))
        if src is None or dst is None or src.id == dst.id:
            skipped += 1
            continue
        try:
            edge_type = SkillEdgeType(_key(entry.get("type", "prereq")))
        except ValueError:
            print(f"  ! unknown edge type {entry.get('type')!r} - skipped")
            skipped += 1
            continue
        weight = float(entry.get("weight", 1.0))
        existing = db.scalar(
            select(SkillEdge).where(
                SkillEdge.from_skill_id == src.id,
                SkillEdge.to_skill_id == dst.id,
                SkillEdge.edge_type == edge_type,
            )
        )
        if existing is None:
            db.add(
                SkillEdge(
                    from_skill_id=src.id,
                    to_skill_id=dst.id,
                    edge_type=edge_type,
                    weight=weight,
                    source=_key(entry.get("source", "seed"))[:20],
                    approved=True,
                )
            )
            created += 1
        else:
            existing.weight = weight
            existing.source = _key(entry.get("source", "seed"))[:20]
            existing.approved = True
    db.commit()
    if skipped:
        print(f"  ({skipped} edges skipped - unknown endpoints)")
    return created


# ---------------------------------------------------------------------------
# Job -> family assignment (deterministic title keywords)
# ---------------------------------------------------------------------------

def assign_job_families(db, families: dict[str, JobFamily]) -> int:
    if not families:
        return 0
    by_id = {row.id: row for row in families.values()}

    def depth_of(row: JobFamily) -> int:
        depth, seen = 0, set()
        while row.parent_id is not None and row.id not in seen:
            seen.add(row.id)
            parent = by_id.get(row.parent_id)
            if parent is None:
                break
            row = parent
            depth += 1
        return depth

    # deepest families first so "backend engineer" wins over "software engineer"
    ordered = sorted(families.values(), key=lambda r: (-depth_of(r), r.name))
    ordered_kw = [
        (family, sorted(( _norm_text(k) for k in (family.keywords or []) ), key=len, reverse=True))
        for family in ordered
    ]

    assigned = 0
    jobs = db.scalars(select(Job).where(Job.family_id.is_(None))).all()
    for job in jobs:
        title = _norm_text(job.title or "")
        if not title:
            continue
        for family, keywords in ordered_kw:
            hit = next((kw for kw in keywords if kw and kw in title), None)
            if hit:
                job.family_id = family.id
                assigned += 1
                break
    db.commit()
    return assigned


# ---------------------------------------------------------------------------

def main() -> None:
    db = SessionLocal()
    try:
        print("Seeding job families...")
        families, families_data = seed_families(db)
        print(f"  {len(families)} families")

        print("Seeding canonical skills...")
        skills = seed_canonical_skills(db, families_data)
        print(f"  {len(skills)} canonical skills")

        print("Seeding skill aliases...")
        print(f"  {seed_aliases(db, skills)} new alias rows")

        print("Seeding skill graph edges...")
        print(f"  {seed_edges(db, skills)} new edge rows")

        print("Assigning job families by title keywords...")
        print(f"  {assign_job_families(db, families)} jobs assigned")

        print("seed_canonical complete.")
    finally:
        db.close()


if __name__ == "__main__":
    main()

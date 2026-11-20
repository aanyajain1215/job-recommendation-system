"""O*NET 31.0 occupation <-> technology data for the M1 skill graph.

Source: O*NET 31.0 Database, U.S. Department of Labor / Employment and
Training Administration (https://www.onetcenter.org/database.html), licensed
under CC BY 4.0. Files used (downloaded once into ml/data/external/onet/):

  software_skills.csv      occupation -> technology used on the job
                           (31.8k links, 923 occupations, 8.7k technologies)
  occupation_data.csv      occupation titles + descriptions
  related_occupations.csv  expert-curated related occupations (EVALUATION ONLY)

This replaces the hand-written families.yaml / skill_prereqs.yaml clusters as
the source of skill relatedness. Prerequisite ORDER (learn X before Y) is not
something O*NET records, so the curated prereq edges stay for roadmap ordering.
"""

from __future__ import annotations

import csv
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
ONET_DIR = BACKEND_ROOT / "ml" / "data" / "external" / "onet"
ONET_VERSION = "31.0"
BASE_URL = "https://www.onetcenter.org/dl_files/database/db_31_0_csv"
FILES = ("software_skills.csv", "occupation_data.csv", "related_occupations.csv")

# App skill (canonical, lowercase - see skill_aliases.yaml) -> O*NET technology
# name, for names that do not match exactly. Curated by hand from O*NET search;
# only unambiguous product matches are listed.
APP_TO_ONET: dict[str, str] = {
    "aws": "Amazon Web Services AWS software",
    "azure": "Microsoft Azure software",
    "gcp": "Google Cloud software",
    "airflow": "Apache Airflow",
    "angular": "Google Angular",
    "ansible": "Ansible software",
    "css": "Cascading style sheets CSS",
    "html": "Hypertext markup language HTML",
    "excel": "Microsoft Excel",
    "hadoop": "Apache Hadoop",
    "java": "Oracle Java",
    "jira": "Atlassian JIRA",
    "kafka": "Apache Kafka",
    "power bi": "Microsoft Power BI",
    "rust": "Rust programming language",
    "spark": "Apache Spark",
    "sql": "Structured query language SQL",
    "terraform": "IBM Terraform",
    "unit testing": "Unit testing software",
    "data visualization": "Data visualization software",
    "data analysis": "Data analysis software",
    "microservices": "Microservices Architecture",
    "grafana": "Grafana Labs Grafana Cloud",
    "network security": "Network security auditing software",
    "siem": "IBM QRadar SIEM",
    "sklearn": "Scikit-learn",
    "scikit-learn": "Scikit-learn",
    "jenkins": "Jenkins CI",
    "go": "Go",
    "golang": "Go",
    "spring boot": "Spring Boot",
    "vue.js": "Vue.js",
    "node.js": "Node.js",
    "splunk": "Splunk Enterprise",
    "openai api": "OpenAI ChatGPT",
    "github actions": "GitHub",
    "rest apis": "RESTful API",
    "ethical hacking": "Penetration testing software",
    "incident response": "Security incident management software",
    "statistics": "Statistical software",
}
# Deliberately NOT mapped: abstract concepts with no O*NET tool equivalent
# ("machine learning", "system design", "data structures", "ci/cd", ...) and
# tools O*NET does not list (FastAPI, Next.js, Tailwind, pytest, ...). Automatic
# name matching was tried and rejected: BGE matched "fastapi" to FASTA (a DNA
# file format) at 0.82 cosine, as confidently as correct matches. These skills
# get no embedding and the app falls back to the curated prereq/transfer edges.


def download(force: bool = False) -> Path:
    ONET_DIR.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        path = ONET_DIR / name
        if force or not path.exists():
            urllib.request.urlretrieve(f"{BASE_URL}/{name}", path)  # noqa: S310 (fixed https URL)
    (ONET_DIR / "SOURCE.txt").write_text(
        f"O*NET {ONET_VERSION} Database by the U.S. Department of Labor, Employment and Training\n"
        "Administration (USDOL/ETA). Used under the CC BY 4.0 license.\n"
        f"Downloaded from {BASE_URL}/\n",
        encoding="utf-8",
    )
    return ONET_DIR


def _read(name: str) -> list[dict]:
    with (ONET_DIR / name).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@dataclass
class OnetData:
    occupations: dict[str, dict]                    # code -> {title, description}
    occ_techs: dict[str, set[str]]                  # code -> technologies
    tech_category: dict[str, str]                   # tech -> O*NET commodity/element name
    hot: set[str]                                   # O*NET "hot technology" flag
    related: dict[str, list[str]] = field(default_factory=dict)  # code -> related codes (Primary-Short)

    @property
    def techs(self) -> list[str]:
        return sorted({t for ts in self.occ_techs.values() for t in ts})

    def tech_degree(self) -> Counter:
        return Counter(t for ts in self.occ_techs.values() for t in ts)


def load(min_degree: int = 2, keep: set[str] | None = None) -> OnetData:
    """Load O*NET, keeping technologies used by >= min_degree occupations.

    Technologies named in `keep` (the app's mapped skills) are retained even
    when rarer, so every mappable app skill gets a vector.
    """
    download()
    occupations = {
        r["O*NET-SOC Code"]: {"title": r["Title"], "description": r["Description"]}
        for r in _read("occupation_data.csv")
    }
    occ_techs: dict[str, set[str]] = defaultdict(set)
    first_cat: dict[str, str] = {}
    hot: set[str] = set()
    for r in _read("software_skills.csv"):
        tech = r["Workplace Example"].strip()
        occ_techs[r["O*NET-SOC Code"]].add(tech)
        first_cat.setdefault(tech, r["Element Name"])
        if r.get("Hot Technology") == "Y":
            hot.add(tech)

    degree = Counter(t for ts in occ_techs.values() for t in ts)
    keep = keep or set()
    allowed = {t for t, d in degree.items() if d >= min_degree} | (keep & set(degree))
    occ_techs = {o: {t for t in ts if t in allowed} for o, ts in occ_techs.items()}
    occ_techs = {o: ts for o, ts in occ_techs.items() if ts}

    related: dict[str, list[str]] = defaultdict(list)
    for r in _read("related_occupations.csv"):
        if r["Relatedness Tier"] == "Primary-Short":
            related[r["O*NET-SOC Code"]].append(r["Related O*NET-SOC Code"])

    return OnetData(
        occupations={o: occupations[o] for o in occ_techs if o in occupations},
        occ_techs=occ_techs,
        tech_category={t: first_cat[t] for t in allowed},
        hot=hot & allowed,
        related=dict(related),
    )


def app_skill_vocabulary() -> list[str]:
    """Canonical app skills (lowercase) from the alias map + families + prereqs."""
    import yaml  # noqa: PLC0415

    data = BACKEND_ROOT / "ml" / "data"
    aliases = yaml.safe_load((data / "skill_aliases.yaml").read_text(encoding="utf-8")) or {}
    fams = yaml.safe_load((data / "families.yaml").read_text(encoding="utf-8")) or []
    pre = yaml.safe_load((data / "skill_prereqs.yaml").read_text(encoding="utf-8")) or []
    vocab = {str(k).lower().strip() for k in aliases}
    vocab |= {str(s).lower().strip() for f in fams for s in f.get("core_skills", [])}
    vocab |= {str(e[k]).lower().strip() for e in pre for k in ("from", "to")}
    return sorted(v for v in vocab if v)


def map_app_skills(techs: list[str] | set[str], vocab: list[str]) -> dict[str, str]:
    """App skill -> O*NET technology (exact case-insensitive match, then APP_TO_ONET)."""
    by_lower = {t.lower(): t for t in techs}
    out: dict[str, str] = {}
    for skill in vocab:
        if skill in by_lower:
            out[skill] = by_lower[skill]
        elif skill in APP_TO_ONET and APP_TO_ONET[skill] in set(techs):
            out[skill] = APP_TO_ONET[skill]
    return out

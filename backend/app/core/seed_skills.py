from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models.skill import Skill

INITIAL_SKILLS = [
    # Programming Languages
    ("Python", "programming_language"),
    ("TypeScript", "programming_language"),
    ("JavaScript", "programming_language"),
    ("Go", "programming_language"),
    ("Java", "programming_language"),
    ("Rust", "programming_language"),
    ("C++", "programming_language"),
    ("SQL", "programming_language"),

    # Frontend
    ("React", "frontend"),
    ("Next.js", "frontend"),
    ("Vue.js", "frontend"),
    ("TailwindCSS", "frontend"),
    ("HTML5", "frontend"),
    ("CSS3", "frontend"),
    ("Redux", "frontend"),

    # Backend & APIs
    ("FastAPI", "backend"),
    ("Django", "backend"),
    ("Node.js", "backend"),
    ("Express.js", "backend"),
    ("Spring Boot", "backend"),
    ("GraphQL", "backend"),
    ("REST APIs", "backend"),
    ("gRPC", "backend"),

    # Databases & Vector Stores
    ("PostgreSQL", "database"),
    ("pgvector", "database"),
    ("Redis", "database"),
    ("MongoDB", "database"),
    ("Elasticsearch", "database"),
    ("MySQL", "database"),

    # Machine Learning & AI
    ("Machine Learning", "machine_learning"),
    ("Deep Learning", "machine_learning"),
    ("PyTorch", "machine_learning"),
    ("TensorFlow", "machine_learning"),
    ("Scikit-Learn", "machine_learning"),
    ("LightGBM", "machine_learning"),
    ("XGBoost", "machine_learning"),
    ("NLP", "machine_learning"),
    ("Sentence Transformers", "machine_learning"),
    ("Hugging Face", "machine_learning"),
    ("Computer Vision", "machine_learning"),
    ("LangChain", "machine_learning"),

    # Cloud & DevOps
    ("Docker", "devops"),
    ("Kubernetes", "devops"),
    ("AWS", "cloud"),
    ("GCP", "cloud"),
    ("Azure", "cloud"),
    ("CI/CD", "devops"),
    ("Terraform", "devops"),
    ("Linux", "devops"),

    # Architecture & Product
    ("System Design", "architecture"),
    ("Microservices", "architecture"),
    ("Event-Driven Architecture", "architecture"),
    ("Agile / Scrum", "process"),
    ("Product Management", "management"),
    ("UI/UX Design", "design"),
]


def seed_skills(db: Session) -> int:
    """Seed initial skill taxonomy if not already present."""
    count_added = 0
    for name, category in INITIAL_SKILLS:
        normalized_name = name.strip()
        existing = db.scalar(select(Skill).where(Skill.name.ilike(normalized_name)))
        if existing is None:
            skill = Skill(name=normalized_name, category=category)
            db.add(skill)
            count_added += 1

    if count_added > 0:
        db.commit()
    return count_added


if __name__ == "__main__":
    with SessionLocal() as session:
        added = seed_skills(session)
        print(f"Seeded {added} new skills into the taxonomy.")

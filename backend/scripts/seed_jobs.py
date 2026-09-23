from sqlalchemy import select
from app.core.db import SessionLocal
from app.models.company import Company
from app.models.enums import EmploymentType, ExperienceLevel, JobStatus, UserRole
from app.models.job import Job
from app.models.skill import JobSkill, Skill
from app.models.user import User

JOBS_DATA = [
    {
        "title": "Senior Machine Learning & Recommender Systems Engineer",
        "description": "Architect candidate generation, two-stage ranking pipelines, and embedding models. You will lead the transition to hybrid retrieval combining content-based filtering and vector search.",
        "requirements": "Strong foundations in PyTorch, sentence-transformers, LightGBM, and PostgreSQL with pgvector. 4+ years of applied ML experience.",
        "employment_type": EmploymentType.FULL_TIME,
        "experience_level": ExperienceLevel.SENIOR,
        "location": "San Francisco, CA",
        "is_remote": True,
        "salary_min": 160000,
        "salary_max": 210000,
        "salary_currency": "USD",
        "skills": [
            ("Machine Learning", True, 2.0),
            ("Python", True, 1.8),
            ("PyTorch", True, 1.5),
            ("Sentence Transformers", False, 1.2),
            ("PostgreSQL", False, 1.0),
        ],
    },
    {
        "title": "Full-Stack Next.js & FastAPI Developer",
        "description": "Join our product engineering pod to build modern web interfaces with Next.js 16, TypeScript, and high-performance Python FastAPI services.",
        "requirements": "3+ years building responsive SPAs with React, Next.js, TailwindCSS, and integrating RESTful backend services.",
        "employment_type": EmploymentType.FULL_TIME,
        "experience_level": ExperienceLevel.MID,
        "location": "Remote",
        "is_remote": True,
        "salary_min": 130000,
        "salary_max": 170000,
        "salary_currency": "USD",
        "skills": [
            ("Next.js", True, 1.8),
            ("TypeScript", True, 1.6),
            ("React", True, 1.6),
            ("FastAPI", True, 1.5),
            ("TailwindCSS", False, 1.0),
        ],
    },
    {
        "title": "Cloud & DevOps Infrastructure Lead",
        "description": "Own container orchestration, multi-stage CI/CD pipelines, and cloud observability for our growing recommendation microservices.",
        "requirements": "Deep expertise with Docker, Kubernetes, AWS, Terraform, and automated deployment automation. 6+ years in DevOps/SRE.",
        "employment_type": EmploymentType.FULL_TIME,
        "experience_level": ExperienceLevel.LEAD,
        "location": "San Francisco, CA",
        "is_remote": False,
        "salary_min": 180000,
        "salary_max": 230000,
        "salary_currency": "USD",
        "skills": [
            ("Kubernetes", True, 2.0),
            ("Docker", True, 1.8),
            ("AWS", True, 1.6),
            ("Terraform", True, 1.4),
            ("CI/CD", False, 1.0),
        ],
    },
    {
        "title": "Senior Data Platform Engineer",
        "description": "Build high-throughput ingestion pipelines and feature stores supporting near real-time recommendation updates and analytical modeling.",
        "requirements": "Solid experience with SQL, PostgreSQL, Redis caches, event streaming, and distributed data pipelines.",
        "employment_type": EmploymentType.FULL_TIME,
        "experience_level": ExperienceLevel.SENIOR,
        "location": "New York, NY",
        "is_remote": True,
        "salary_min": 150000,
        "salary_max": 195000,
        "salary_currency": "USD",
        "skills": [
            ("PostgreSQL", True, 1.8),
            ("Python", True, 1.6),
            ("Redis", True, 1.4),
            ("SQL", True, 1.5),
            ("System Design", False, 1.2),
        ],
    },
    {
        "title": "Product Manager - AI & Recommendation Platforms",
        "description": "Drive the roadmap for our AI matching engine, recruiter workflow automation, and candidate discovery products.",
        "requirements": "Demonstrated success launching machine learning or marketplace products. Strong understanding of user feedback loops.",
        "employment_type": EmploymentType.FULL_TIME,
        "experience_level": ExperienceLevel.SENIOR,
        "location": "Remote",
        "is_remote": True,
        "salary_min": 140000,
        "salary_max": 185000,
        "salary_currency": "USD",
        "skills": [
            ("Product Management", True, 2.0),
            ("Agile / Scrum", True, 1.5),
            ("System Design", False, 1.0),
        ],
    },
]


def seed_jobs():
    with SessionLocal() as db:
        employer = db.scalar(select(User).where(User.email == "recruiter@technova.io"))
        if not employer:
            print("Employer recruiter@technova.io not found.")
            return

        company = db.scalar(select(Company).where(Company.created_by_user_id == employer.id).limit(1))
        if not company:
            company = Company(
                name="TechNova Labs",
                slug=f"technova-{str(employer.id)[:8]}",
                created_by_user_id=employer.id,
            )
            db.add(company)
            db.flush()

        added_count = 0
        for item in JOBS_DATA:
            existing = db.scalar(select(Job).where(Job.title == item["title"]))
            if existing:
                continue

            job = Job(
                company_id=company.id,
                posted_by_user_id=employer.id,
                title=item["title"],
                description=item["description"],
                requirements=item["requirements"],
                employment_type=item["employment_type"],
                experience_level=item["experience_level"],
                location=item["location"],
                is_remote=item["is_remote"],
                salary_min=item["salary_min"],
                salary_max=item["salary_max"],
                salary_currency=item["salary_currency"],
                status=JobStatus.PUBLISHED,
            )
            db.add(job)
            db.flush()

            for skill_name, is_req, weight in item["skills"]:
                sk = db.scalar(select(Skill).where(Skill.name.ilike(skill_name)))
                if not sk:
                    sk = Skill(name=skill_name)
                    db.add(sk)
                    db.flush()

                job_skill = JobSkill(
                    job_id=job.id,
                    skill_id=sk.id,
                    is_required=is_req,
                    importance_weight=weight,
                )
                job.skills.append(job_skill)

            added_count += 1

        db.commit()
        print(f"Successfully seeded {added_count} diverse job postings.")


if __name__ == "__main__":
    seed_jobs()

import json
import urllib.request
import urllib.parse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.db import SessionLocal
from app.models.job import Job
from app.models.profile import Profile
from app.models.skill import JobSkill, ProfileSkill
from app.models.user import User
from app.services.recommender import ContentRecommender


def test_content_recommender_service():
    print("\n--- 1. Testing ContentRecommender Service Logic ---")
    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.email == "aanya.seeker@example.com")
        )
        assert user is not None, "Seeker user 'aanya.seeker@example.com' not found"

        profile = db.scalar(
            select(Profile)
            .where(Profile.user_id == user.id)
            .options(
                selectinload(Profile.skills).selectinload(ProfileSkill.skill)
            )
        )
        assert profile is not None, "Profile not found for seeker"

        skills = [ps.skill.name for ps in profile.skills if ps.skill]
        print(f"Candidate Profile: {profile.first_name} {profile.last_name}")
        print(f"Candidate Headline: {profile.headline}")
        print(f"Candidate Skills ({len(skills)}): {', '.join(skills)}")

        jobs = db.scalars(
            select(Job)
            # Seeded golden corpus only: these assertions test recommender
            # LOGIC on known inputs — never live-ingested composition
            # (test hygiene: no corpus-size dependence).
            .where(Job.source == "native")
            .options(
                selectinload(Job.company),
                selectinload(Job.skills).selectinload(JobSkill.skill),
                selectinload(Job.applications),
            )
        ).all()
        print(f"Total Jobs Available: {len(jobs)}")

        feed = ContentRecommender.recommend_jobs(profile=profile, jobs=jobs, limit=10)
        print(f"\nRecommendation Feed Generated: {len(feed.items)} items (completeness: {feed.profile_completeness_score}%)")
        print(f"Recommendation Type: {feed.recommendation_type}")

        for rank, item in enumerate(feed.items, 1):
            print(f"\n[Rank {rank}] {item.job.title} - Match: {item.match_score}% (Skill: {item.skill_match_score}%, TF-IDF: {item.content_similarity_score}%)")
            print(f"  Matched Skills: {item.matched_skills}")
            print(f"  Missing Skills: {item.missing_skills}")
            print(f"  Reasons: {item.match_reasons}")

        # Assertions
        assert len(feed.items) > 0
        top_job = feed.items[0]
        assert top_job.match_score > 60.0, f"Top match score {top_job.match_score} is unexpectedly low"
        # The top job should have matched skills
        assert len(top_job.matched_skills) > 0, "Top job has no matched skills"

        # Check DevOps job has lower score and lists missing skills
        devops_item = next((item for item in feed.items if "DevOps" in item.job.title or "Infrastructure" in item.job.title), None)
        if devops_item:
            print(f"\nDevOps Item Match Score: {devops_item.match_score}%")
            print(f"DevOps Missing Skills: {devops_item.missing_skills}")
            assert any(s in devops_item.missing_skills for s in ["Kubernetes", "Docker", "Terraform"]), "DevOps missing skills did not detect expected infrastructure tools"

        # Test Cold-Start Candidate
        empty_profile = Profile(
            first_name="New",
            last_name="User",
            headline="",
            bio="",
            years_of_experience=None,
            skills=[],
        )
        cold_feed = ContentRecommender.recommend_jobs(profile=empty_profile, jobs=jobs, limit=5)
        print(f"\nCold-Start Feed Type: {cold_feed.recommendation_type}, items: {len(cold_feed.items)}")
        assert cold_feed.recommendation_type == "cold_start"
        assert len(cold_feed.items) > 0

    print(">>> ContentRecommender service test PASSED!")


def test_recommendations_api():
    print("\n--- 2. Testing GET /api/v1/recommendations Endpoint ---")
    login_url = "http://localhost:8000/api/v1/auth/login"
    login_data = json.dumps({
        "email": "aanya.seeker@example.com",
        "password": "Password123!"
    }).encode("utf-8")
    
    req = urllib.request.Request(
        login_url,
        data=login_data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        auth_data = json.loads(resp.read().decode("utf-8"))
        access_token = auth_data["access_token"]
        print("Logged in successfully, token retrieved.")

    # Call /api/v1/recommendations
    rec_url = "http://localhost:8000/api/v1/recommendations"
    req = urllib.request.Request(
        rec_url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        },
        method="GET"
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        rec_data = json.loads(resp.read().decode("utf-8"))
        print(f"API Returned {len(rec_data['items'])} recommendations (type: {rec_data['recommendation_type']})")
        assert "items" in rec_data
        assert rec_data["total"] >= 1
        assert "match_score" in rec_data["items"][0]
        assert "matched_skills" in rec_data["items"][0]
        assert "missing_skills" in rec_data["items"][0]

    print(">>> Recommendations API endpoint test PASSED!")


if __name__ == "__main__":
    test_content_recommender_service()
    test_recommendations_api()

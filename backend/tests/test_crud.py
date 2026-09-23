import urllib.request
import json
from uuid import UUID

from app.core.db import SessionLocal
from app.models.user import User
from app.core.security import create_access_token

def run_tests():
    with SessionLocal() as db:
        seeker = db.query(User).filter(User.email == "aanya.seeker@example.com").first()
        employer = db.query(User).filter(User.email == "recruiter@technova.io").first()

        seeker_token = create_access_token(seeker.id, seeker.role.value)
        emp_token = create_access_token(employer.id, employer.role.value)

    print("Tokens generated successfully.")

    # 1. Resume upload
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    payload = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="aanya_resume.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
        "Aanya Sharma - Senior Full Stack Engineer. Python, FastAPI, React, PostgreSQL.\r\n"
        f"--{boundary}--\r\n"
    ).encode("utf-8")

    req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/profiles/me/resume",
        data=payload,
        headers={
            "Authorization": f"Bearer {seeker_token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST"
    )

    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode())
        print("[1/4] Resume uploaded successfully:", res.get("resume_url"))

    # 2. Resume download test
    resume_url = res.get("resume_url")
    dl_req = urllib.request.Request(
        f"http://127.0.0.1:8000{resume_url}",
        headers={"Authorization": f"Bearer {seeker_token}"},
        method="GET"
    )
    with urllib.request.urlopen(dl_req) as dl_resp:
        content = dl_resp.read().decode()
        assert "Aanya Sharma" in content
        print("[2/4] Resume downloaded and verified content.")

    # 3. Post Job by Employer
    job_data = {
        "title": "Lead Machine Learning & Backend Engineer",
        "description": "Architect candidate matching and two-stage ranking pipeline.",
        "requirements": "Proficiency with Python, FastAPI, and vector embeddings.",
        "employment_type": "full_time",
        "experience_level": "senior",
        "location": "San Francisco, CA",
        "is_remote": True,
        "salary_min": 150000,
        "salary_max": 200000,
        "salary_currency": "USD",
        "skills": [
            {"skill_name": "Python", "is_required": True, "importance_weight": 1.5},
            {"skill_name": "Machine Learning", "is_required": True, "importance_weight": 1.4},
            {"skill_name": "FastAPI", "is_required": True, "importance_weight": 1.2}
        ]
    }
    job_req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/jobs",
        data=json.dumps(job_data).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {emp_token}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(job_req) as job_resp:
        created_job = json.loads(job_resp.read().decode())
        print("[3/4] Job created by employer:", created_job["title"], "ID:", created_job["id"])

    # 4. Search & filter jobs
    search_req = urllib.request.Request(
        "http://127.0.0.1:8000/api/v1/jobs?search=Machine%20Learning&is_remote=true",
        method="GET"
    )
    with urllib.request.urlopen(search_req) as s_resp:
        search_res = json.loads(s_resp.read().decode())
        print("[4/4] Public jobs search count:", search_res["total"], "First title:", search_res["items"][0]["title"])

    print("=== ALL BACKEND TESTS PASSED ===")

if __name__ == "__main__":
    run_tests()

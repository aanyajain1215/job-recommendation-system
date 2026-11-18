"""Phase 0 employer-side audit: create one real posting via the app's own
"Post a job" feature, then run Talent / Insights / What-If / Performance.

Updates ml/reports/audit_feature_runs.json in place.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
REPORT = BACKEND / "ml" / "reports" / "audit_feature_runs.json"


def call(method: str, path: str, token: str | None = None, body: dict | None = None, timeout: int = 240) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    t = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"status": resp.status, "latency_ms": int((time.monotonic() - t) * 1000), "response": json.loads(resp.read().decode())}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw[:600]
        return {"status": exc.code, "latency_ms": int((time.monotonic() - t) * 1000), "response": payload}
    except Exception as exc:  # noqa: BLE001
        return {"status": -1, "latency_ms": int((time.monotonic() - t) * 1000), "response": {"error": str(exc)}}


def brief(response: object, limit: int = 900) -> object:
    text = json.dumps(response, ensure_ascii=False)
    if len(text) <= limit:
        return response
    if isinstance(response, dict):
        out = {}
        for k, v in response.items():
            out[k] = f"<list len={len(v)}>" if isinstance(v, list) and len(v) > 4 else v
        return out
    return {"truncated": True, "head": text[:limit]}


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    login = call("POST", "/auth/login", body={"email": "employer.qa@jobrec.io", "password": "Password123!"})
    token = login["response"].get("access_token")
    assert token, f"employer login failed: {login}"

    created = call("POST", "/jobs", token=token, body={
        "title": "Senior Backend Engineer (Phase 0 Audit Posting)",
        "description": (
            "Real audit posting created through the app's Post a job feature. "
            "Build and maintain Python/FastAPI services with PostgreSQL, design REST APIs, "
            "write tests, and deploy with Docker. Strong SQL and system design skills required."
        ),
        "requirements": "Python, FastAPI, PostgreSQL, Docker, REST APIs, SQL, system design",
        "employment_type": "full_time",
        "experience_level": "senior",
        "location": "Bengaluru, India",
        "is_remote": False,
        "salary_min": 1800000,
        "salary_max": 2800000,
        "salary_currency": "INR",
        "skills": [
            {"skill_name": "Python", "is_required": True, "importance_weight": 1.5},
            {"skill_name": "FastAPI", "is_required": True, "importance_weight": 1.2},
            {"skill_name": "PostgreSQL", "is_required": True, "importance_weight": 1.0},
            {"skill_name": "Docker", "is_required": False, "importance_weight": 0.8},
        ],
        "family": "Backend Engineering",
    })
    print("create job:", created["status"], str(created["response"])[:200])
    assert created["status"] in (200, 201)
    job_id = created["response"]["id"]

    features = [
        ("Employer Hiring", "GET", "/employer/jobs", None),
        ("Employer Talent", "GET", f"/employer/postings/{job_id}/talent", None),
        ("Employer Insights", "GET", f"/employer/postings/{job_id}/insights", None),
        ("Employer Performance", "GET", f"/employer/postings/{job_id}/performance", None),
        ("Employer What-If", "POST", f"/employer/postings/{job_id}/whatif", {}),
    ]
    new_records = []
    for name, method, path, body in features:
        r = call(method, path, token=token, body=body)
        ok = 200 <= r["status"] < 300
        new_records.append({
            "profile": "employer.qa@jobrec.io", "feature": name,
            "input": {"job_id": job_id, "jobs_in_db": 1117},
            "request": f"{method} {path}", "status_code": r["status"],
            "latency_ms": r["latency_ms"], "pass": ok,
            "observed_output": brief(r["response"]),
        })
        print(f"{name:22s} {r['status']:>3} {r['latency_ms']:>6}ms")

    report["records"] = [r for r in report["records"] if not r["feature"].startswith("Employer")] + new_records
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("updated", REPORT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

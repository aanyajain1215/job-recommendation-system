"""Phase 0 feature audit runner — real profiles, real jobs, no synthetic data.

Calls every user-facing feature through the HTTP API and writes structured
request/response evidence to ``ml/reports/audit_feature_runs.json``.

Run from ``backend/`` (stack must be up)::

    python scripts/run_phase0_audit.py
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000/api/v1"
OUT = BACKEND / "ml" / "reports" / "audit_feature_runs.json"
JOB_ID = "5fc8ae4f-6085-488d-9bf4-d06152543d68"  # real native job, 5 skills
AUDIT_EMAILS = [f"audit_livecareer_{i:02d}@audit.jobrec.io" for i in range(10)]
AUDIT_PASSWORD = "AuditOnly123!"


def call(method: str, path: str, token: str | None = None, body: dict | None = None, timeout: int = 180) -> dict:
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            return {
                "status": resp.status,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "response": payload,
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw[:1000]
        return {
            "status": exc.code,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "response": payload,
        }
    except Exception as exc:  # noqa: BLE001 - audit records failures, never crashes
        return {
            "status": -1,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "response": {"error": str(exc)},
        }


def login(email: str, password: str) -> str | None:
    r = call("POST", "/auth/login", body={"email": email, "password": password})
    return r["response"].get("access_token") if r["status"] == 200 else None


def brief(response: object, limit: int = 900) -> object:
    """Truncate large responses but keep structure and key numbers."""
    text = json.dumps(response, ensure_ascii=False)
    if len(text) <= limit:
        return response
    if isinstance(response, dict):
        out = {}
        for k, v in response.items():
            if isinstance(v, list):
                out[k] = f"<list len={len(v)}> first=" + json.dumps(v[0], ensure_ascii=False)[:400] if v else []
            elif isinstance(v, dict):
                out[k] = json.dumps(v, ensure_ascii=False)[:300]
            else:
                out[k] = v
        return out
    return {"truncated": True, "head": text[:limit]}


def main() -> int:
    records: list[dict] = []
    started_at = datetime.now(timezone.utc).isoformat()

    for idx, email in enumerate(AUDIT_EMAILS):
        token = login(email, AUDIT_PASSWORD)
        if not token:
            records.append({"profile": email, "feature": "auth", "status": "FAIL", "evidence": {"error": "login failed"}})
            continue
        inputs = {
            "profile": email,
            "jobs_in_db": 1116,
            "job_id": JOB_ID,
            "dataset": "opensporks/resumes (CC0-1.0), 10 real resumes",
        }
        features = [
            ("Profile", "GET", "/profiles/me", None),
            ("AI Matches", "GET", "/recommendations?limit=10", None),
            ("Find Jobs", "GET", "/jobs?q=python&limit=10", None),
            ("AI Search", "GET", "/jobs/nl?" + urllib.parse.urlencode({"q": "python developer remote"}), None),
            ("Skill Gap", "GET", f"/recommendations/{JOB_ID}/gap", None),
            ("Roadmap", "GET", f"/recommendations/{JOB_ID}/roadmap", None),
            ("Careers", "GET", "/careers/discover", None),
            ("What-If", "POST", "/simulate", {"add_skills": [{"name": "Python", "level": "advanced", "years": 5}]}),
            ("Resume Optimizer", "POST", f"/jobs/{JOB_ID}/resume-optimize", {}),
            ("Saved", "GET", "/applications/me", None),
            ("Save Job", "POST", f"/jobs/{JOB_ID}/save", {}),
        ]
        for name, method, path, body in features:
            r = call(method, path, token=token, body=body)
            ok = 200 <= r["status"] < 300
            records.append({
                "profile": email,
                "feature": name,
                "input": inputs,
                "request": f"{method} {path}" + (f" body={body}" if body else ""),
                "status_code": r["status"],
                "latency_ms": r["latency_ms"],
                "pass": ok,
                "observed_output": brief(r["response"]),
            })
            print(f"[{idx+1:02d}/10] {name:18s} {r['status']:>3} {r['latency_ms']:>6}ms", flush=True)

    # Employer-side features (real native job owned by the dev employer).
    for name, email, password, path, method, body in [
        ("Employer Hiring", "recruiter@technova.io", "Password123!", "/employer/jobs", "GET", None),
        ("Employer Talent", "recruiter@technova.io", "Password123!", f"/employer/postings/{JOB_ID}/talent", "GET", None),
        ("Employer Insights", "recruiter@technova.io", "Password123!", f"/employer/postings/{JOB_ID}/insights", "GET", None),
        ("Employer Performance", "recruiter@technova.io", "Password123!", f"/employer/postings/{JOB_ID}/performance", "GET", None),
        ("Employer What-If", "recruiter@technova.io", "Password123!", f"/employer/postings/{JOB_ID}/whatif", "POST", {}),
        ("Admin Config", "admin.qa@jobrec.io", "Password123!", "/admin/config", "GET", None),
        ("Admin LLM Usage", "admin.qa@jobrec.io", "Password123!", "/admin/llm-usage", "GET", None),
        ("Admin Skills", "admin.qa@jobrec.io", "Password123!", "/admin/skills?q=python", "GET", None),
        ("Admin Duplicates", "admin.qa@jobrec.io", "Password123!", "/admin/jobs/duplicates", "GET", None),
        ("Admin Models", "admin.qa@jobrec.io", "Password123!", "/admin/models", "GET", None),
    ]:
        token = login(email, password)
        if not token:
            records.append({"profile": email, "feature": name, "pass": False, "observed_output": {"error": "login failed"}})
            print(f"[ops] {name:18s} LOGIN FAIL", flush=True)
            continue
        r = call(method, path, token=token, body=body)
        ok = 200 <= r["status"] < 300
        records.append({
            "profile": email, "feature": name,
            "input": {"jobs_in_db": 1116, "job_id": JOB_ID},
            "request": f"{method} {path}", "status_code": r["status"],
            "latency_ms": r["latency_ms"], "pass": ok,
            "observed_output": brief(r["response"]),
        })
        print(f"[ops] {name:18s} {r['status']:>3} {r['latency_ms']:>6}ms", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"generated_at": started_at, "data": "REAL: 10 CC0 resumes + 1116 real ingested jobs", "records": records}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    passed = sum(1 for r in records if r.get("pass"))
    print(f"DONE: {passed}/{len(records)} passed -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

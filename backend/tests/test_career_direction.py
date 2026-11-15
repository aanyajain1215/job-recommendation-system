"""Career-direction form backend (requirement 2).

The profile model already stored ``target_family`` and ``career_interests`` but
had no UI.  These tests pin the API contract the new profile form relies on:

- ``GET /careers/families`` returns the canonical selector list,
- ``PUT /profiles/me`` round-trips target family + roles/domains,
- an empty string explicitly clears the target family,
- an unknown family is rejected (422/404), never silently stored.

Everything persisted is keyed to a throwaway seeker/family and purged in
teardown.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.db import SessionLocal
from app.main import app
from app.models.job_family import JobFamily
from app.models.user import User

client = TestClient(app, raise_server_exceptions=False)


def _register_seeker() -> dict:
    uid = uuid4().hex[:8]
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "email": f"career_dir_{uid}@example.com",
            "password": "Password123!",
            "role": "job_seeker",
        },
    )
    assert reg.status_code == 201, reg.text
    body = reg.json()
    return {
        "headers": {"Authorization": f"Bearer {body['access_token']}"},
        "id": body["user"]["id"],
    }


def _delete_user(user_id) -> None:
    with SessionLocal() as db:
        row = db.get(User, UUID(str(user_id)))
        if row is not None:
            db.delete(row)
            db.commit()


@pytest.fixture
def seeker():
    account = _register_seeker()
    yield account
    _delete_user(account["id"])


@pytest.fixture
def family():
    """Self-seeded canonical family (the dev DB may ship with none)."""
    name = f"Career Direction Test {uuid4().hex[:8]}"
    with SessionLocal() as db:
        row = JobFamily(name=name)
        db.add(row)
        db.commit()
        db.refresh(row)
        family_id = row.id
    yield {"id": str(family_id), "name": name}
    with SessionLocal() as db:
        row = db.get(JobFamily, UUID(str(family_id)))
        if row is not None:
            db.delete(row)
            db.commit()


def test_families_endpoint_lists_seeded_family(seeker, family):
    resp = client.get("/api/v1/careers/families", headers=seeker["headers"])
    assert resp.status_code == 200, resp.text
    names = resp.json()["families"]
    assert family["name"] in names
    assert names == sorted(names), "selector list must be deterministic"


def test_families_endpoint_requires_auth():
    resp = client.get("/api/v1/careers/families")
    assert resp.status_code in (401, 403), resp.text


def test_target_family_and_interests_round_trip(seeker, family):
    put = client.put(
        "/api/v1/profiles/me",
        headers=seeker["headers"],
        json={
            "headline": "Switching into data",
            "target_family": family["name"],
            "career_interests": ["Data Science", "Fintech", "Data Science"],
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["target_family"] == family["name"]
    # Duplicates are preserved verbatim by the API; the UI de-dupes on input.
    assert body["career_interests"] == ["Data Science", "Fintech", "Data Science"]

    persisted = client.get("/api/v1/profiles/me", headers=seeker["headers"])
    assert persisted.status_code == 200, persisted.text
    data = persisted.json()
    assert data["target_family"] == family["name"]
    assert data["career_interests"] == ["Data Science", "Fintech", "Data Science"]


def test_empty_values_clear_the_direction(seeker, family):
    client.put(
        "/api/v1/profiles/me",
        headers=seeker["headers"],
        json={"target_family": family["name"], "career_interests": ["Fintech"]},
    )

    cleared = client.put(
        "/api/v1/profiles/me",
        headers=seeker["headers"],
        json={"target_family": "", "career_interests": []},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["target_family"] is None
    assert cleared.json()["career_interests"] == []


def test_unknown_target_family_is_rejected(seeker):
    resp = client.put(
        "/api/v1/profiles/me",
        headers=seeker["headers"],
        json={"target_family": f"Nonexistent {uuid4().hex[:8]}"},
    )
    assert resp.status_code in (400, 404, 422), resp.text
    # The failed update must not persist a direction.
    me = client.get("/api/v1/profiles/me", headers=seeker["headers"]).json()
    assert me["target_family"] is None

"""model_registry helpers shared by the ml train scripts (plan §6/§17).

Registration is a real DB row per artifact (name, version, metrics);
promotion flips `active` exclusively within one name.  Serving-side loaders
read artifacts from disk (rerank/calibration) — the registry is the ops
record of what was trained, when, and how well.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _session():
    from app.core.db import SessionLocal  # noqa: PLC0415

    return SessionLocal()


def next_version(db, name: str) -> str:
    from app.models.ops import ModelRegistry  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    rows = db.scalars(select(ModelRegistry.version).where(ModelRegistry.name == name)).all()
    highest = 0
    for version in rows:
        m = re.fullmatch(r"v(\d+)", version or "")
        if m:
            highest = max(highest, int(m.group(1)))
    return f"v{highest + 1}"


def register(
    name: str,
    version: str,
    artifact_path: str,
    metrics: dict[str, Any] | None = None,
    *,
    promote: bool = False,
) -> dict[str, Any]:
    """Insert (or refresh) a registry row; optionally promote it active."""
    from app.models.ops import ModelRegistry  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    db = _session()
    try:
        row = db.scalar(
            select(ModelRegistry).where(
                ModelRegistry.name == name, ModelRegistry.version == version
            )
        )
        if row is None:
            row = ModelRegistry(name=name, version=version, artifact_path=artifact_path)
            db.add(row)
        row.metrics = metrics or {}
        row.artifact_path = artifact_path
        row.trained_at = datetime.now(timezone.utc)
        db.flush()
        if promote:
            _promote_in_session(db, name, version)
        db.commit()
        return {
            "name": name,
            "version": version,
            "artifact_path": artifact_path,
            "metrics": row.metrics,
            "active": bool(row.active),
        }
    finally:
        db.close()


def _promote_in_session(db, name: str, version: str) -> None:
    from app.models.ops import ModelRegistry  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    rows = db.scalars(select(ModelRegistry).where(ModelRegistry.name == name)).all()
    for row in rows:
        row.active = row.version == version


def promote(name: str, version: str) -> bool:
    """Make `version` the sole active artifact for `name`."""
    db = _session()
    try:
        _promote_in_session(db, name, version)
        db.commit()
        return True
    finally:
        db.close()


def get_row(name: str, version: str | None = None) -> dict[str, Any] | None:
    from app.models.ops import ModelRegistry  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    db = _session()
    try:
        stmt = select(ModelRegistry).where(ModelRegistry.name == name)
        if version:
            stmt = stmt.where(ModelRegistry.version == version)
        row = db.scalar(stmt.order_by(ModelRegistry.created_at.desc()))
        if row is None:
            return None
        return {
            "name": row.name,
            "version": row.version,
            "artifact_path": row.artifact_path,
            "metrics": row.metrics or {},
            "active": bool(row.active),
            "trained_at": row.trained_at.isoformat() if row.trained_at else None,
        }
    finally:
        db.close()

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.db import get_db
from app.core.security import decode_token
from app.models.enums import UserRole
from app.models.user import User

security_scheme = HTTPBearer(auto_error=True)
# Public read endpoints (job catalog/search) keep working without a token but
# still personalise when one is present (skill-gap previews).
optional_security_scheme = HTTPBearer(auto_error=False)
log = logging.getLogger(__name__)

# One write per user per window is enough for DAU/WAU/MAU reporting.
ACTIVITY_WRITE_INTERVAL = timedelta(minutes=2)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Validate bearer access token and return active authenticated user."""
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type; access token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token claims.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_uuid = UUID(user_id_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    stmt = (
        select(User)
        .options(selectinload(User.profile), selectinload(User.companies))
        .where(User.id == user_uuid)
    )
    user = db.scalar(stmt)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    # Live-usage signal for the admin console. Throttled so hot read paths do
    # not turn every request into an UPDATE.
    now = datetime.now(timezone.utc)
    last_seen = user.last_active_at
    if last_seen is not None and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if last_seen is None or last_seen < now - ACTIVITY_WRITE_INTERVAL:
        try:
            user.last_active_at = now
            db.commit()
        except Exception:  # pragma: no cover - telemetry must never block auth
            db.rollback()
            log.exception("Failed to refresh last_active_at for user %s", user.id)

    return user


def get_optional_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(optional_security_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User | None:
    """Resolve the bearer user when present; anonymous requests pass through.

    Used by public read paths (job catalog / search) so a signed-in seeker
    gets per-listing skill-gap previews without making the catalog login-only.
    Missing or invalid tokens degrade to anonymous rather than 401.
    """
    if credentials is None:
        return None
    try:
        return get_current_user(credentials, db)
    except HTTPException:
        return None


def require_roles(*allowed_roles: UserRole) -> Callable[[User], User]:
    """Dependency factory ensuring current user possesses one of the allowed roles."""
    def role_checker(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action forbidden for role '{current_user.role.value}'. Allowed roles: {[r.value for r in allowed_roles]}.",
            )
        return current_user

    return role_checker

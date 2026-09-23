import re
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import get_current_user, require_roles
from app.core.db import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.company import Company
from app.models.enums import UserRole
from app.models.profile import Profile
from app.models.user import User
from app.schemas.auth import (
    TokenRefreshRequest,
    TokenRefreshResponse,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
)
from app.schemas.user import UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^\w\s-]", "", text.strip().lower())
    return re.sub(r"[-\s]+", "-", cleaned)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(
    data: UserRegisterRequest,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    normalized_email = data.email.strip().lower()

    existing_user = db.scalar(select(User).where(func.lower(User.email) == normalized_email))
    if existing_user is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email address already exists.",
        )

    hashed_pw = hash_password(data.password)

    new_user = User(
        email=normalized_email,
        hashed_password=hashed_pw,
        role=data.role,
        is_active=True,
        is_verified=False,
    )
    db.add(new_user)
    db.flush()

    if data.role == UserRole.JOB_SEEKER:
        profile = Profile(
            user_id=new_user.id,
            first_name=data.first_name.strip() if data.first_name else "",
            last_name=data.last_name.strip() if data.last_name else "",
        )
        db.add(profile)
    elif data.role == UserRole.EMPLOYER and data.company_name:
        base_slug = _slugify(data.company_name) or "company"
        unique_slug = f"{base_slug}-{str(new_user.id)[:8]}"
        company = Company(
            name=data.company_name.strip(),
            slug=unique_slug,
            created_by_user_id=new_user.id,
            is_verified=False,
        )
        db.add(company)

    db.commit()

    # Re-query with eager-loaded relationships
    user = db.scalar(
        select(User)
        .options(selectinload(User.profile), selectinload(User.companies))
        .where(User.id == new_user.id)
    )

    access_token = create_access_token(subject=user.id, role=user.role.value)
    refresh_token = create_refresh_token(subject=user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login(
    data: UserLoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    normalized_email = data.email.strip().lower()

    user = db.scalar(
        select(User)
        .options(selectinload(User.profile), selectinload(User.companies))
        .where(func.lower(User.email) == normalized_email)
    )

    if user is None or not verify_password(data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is deactivated.",
        )

    access_token = create_access_token(subject=user.id, role=user.role.value)
    refresh_token = create_refresh_token(subject=user.id)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=TokenRefreshResponse)
def refresh_token(
    data: TokenRefreshRequest,
    db: Annotated[Session, Depends(get_db)],
) -> TokenRefreshResponse:
    try:
        payload = decode_token(data.refresh_token)
    except ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has expired. Please log in again.",
        ) from exc
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token.",
        ) from exc

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type; refresh token required.",
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token claims.",
        )

    try:
        user_uuid = UUID(user_id_str)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid user ID in token.",
        ) from exc

    user = db.scalar(select(User).where(User.id == user_uuid))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is inactive or not found.",
        )

    new_access_token = create_access_token(subject=user.id, role=user.role.value)
    return TokenRefreshResponse(access_token=new_access_token, token_type="bearer")


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    return UserResponse.model_validate(current_user)


@router.get("/employer-only", response_model=UserResponse)
def employer_only_area(
    current_user: Annotated[User, Depends(require_roles(UserRole.EMPLOYER))],
) -> UserResponse:
    return UserResponse.model_validate(current_user)

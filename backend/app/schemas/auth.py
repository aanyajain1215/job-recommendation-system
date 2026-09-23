from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import UserRole
from app.schemas.user import UserResponse


class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128, description="Password must be at least 8 characters")
    role: Literal[UserRole.JOB_SEEKER, UserRole.EMPLOYER] = Field(
        default=UserRole.JOB_SEEKER,
        description="Self-registration is only allowed for job_seeker or employer",
    )
    first_name: str | None = Field(default=None, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)
    company_name: str | None = Field(default=None, max_length=200)


class UserLoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class TokenRefreshRequest(BaseModel):
    refresh_token: str


class TokenRefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

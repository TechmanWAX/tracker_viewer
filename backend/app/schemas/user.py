"""User-related Pydantic schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class UserBase(BaseModel):
    """Base user schema."""
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=50)


class UserCreate(UserBase):
    """Schema for user registration."""
    password: str = Field(..., min_length=8, max_length=128)


class UserLogin(BaseModel):
    """Schema for user login."""
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class VerifyEmailRequest(BaseModel):
    """Body for POST /auth/verify-email — consume a single-use
    verification link from the email."""
    token: str = Field(..., min_length=8, max_length=128)


class ResendVerificationRequest(BaseModel):
    """Body for POST /auth/resend-verification — request a new
    verification link. The endpoint always returns 200 to avoid
    leaking which emails are registered; the response payload is
    the same shape either way."""
    email: EmailStr


class EmailVerificationError(BaseModel):
    """Returned by /auth/verify-email on failure. `code` is a
    machine-readable discriminator for the frontend to decide
    which message to show."""
    code: str  # one of: invalid, expired, used
    detail: str


class UserUpdate(BaseModel):
    """Schema for user updates."""
    email: Optional[EmailStr] = None
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    password: Optional[str] = Field(None, min_length=8, max_length=128)


class User(UserBase):
    """Schema for user responses."""
    user_id: str
    is_active: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}
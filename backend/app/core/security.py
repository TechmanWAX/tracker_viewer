"""Security utilities: JWT handling, password hashing, and cookie management."""

import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING

from jose import jwt, JWTError
from passlib.context import CryptContext
from pydantic import BaseModel

if TYPE_CHECKING:
    from app.core.config import Settings

# Password hashing context — pbkdf2_sha256 is built into passlib stdlib and
# has no 72-byte limit (the bcrypt issue that breaks the latest bcrypt lib).
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# JWT configuration
ALGORITHM = "HS256"


class TokenPayload(BaseModel):
    """JWT token payload structure."""
    sub: str  # Subject (user ID)
    type: str  # Token type: "access" or "refresh"
    iat: datetime
    exp: datetime
    jti: Optional[str] = None  # JWT ID — unique per token, ensures rotation


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Hash a password."""
    return pwd_context.hash(password)


def _encode_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    """Encode a JWT with a unique jti so successive tokens differ."""
    to_encode = {
        "sub": subject,
        "type": token_type,
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + expires_delta,
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(to_encode, get_settings().jwt_secret_key, algorithm=ALGORITHM)


def create_access_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a new access token."""
    if expires_delta is None:
        expires_delta = timedelta(minutes=15)
    return _encode_token(subject, "access", expires_delta)


def create_refresh_token(
    subject: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a new refresh token."""
    if expires_delta is None:
        expires_delta = timedelta(days=7)
    return _encode_token(subject, "refresh", expires_delta)


def decode_token(token: str) -> Optional[TokenPayload]:
    """Decode and validate a JWT token."""
    try:
        payload = jwt.decode(
            token,
            get_settings().jwt_secret_key,
            algorithms=[ALGORITHM],
        )
        return TokenPayload(**payload)
    except JWTError:
        return None


def generate_csrf_token() -> str:
    """Generate a secure CSRF token."""
    return secrets.token_urlsafe(32)


def verify_csrf_token(token: str, expected: str) -> bool:
    """Verify a CSRF token matches the expected value."""
    return secrets.compare_digest(token, expected)


def get_settings() -> "Settings":
    """Lazy import settings to avoid circular dependencies."""
    from app.core.config import get_settings as _get_settings
    return _get_settings()
"""User model - imported from db-implementer."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, DateTime, Boolean
from sqlalchemy.types import TypeDecorator, CHAR
import uuid as _uuid

from app.db.base import Base

__all__ = ["User"]


class GUID(TypeDecorator):
    """Cross-dialect UUID type: native UUID on PostgreSQL, CHAR(36) elsewhere."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID
            return dialect.type_descriptor(UUID())
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, _uuid.UUID):
            if dialect.name == "postgresql":
                return value
            return str(value)
        # Already a string – pass through on SQLite, try UUID on PostgreSQL
        if dialect.name == "postgresql":
            return _uuid.UUID(str(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, _uuid.UUID):
            return str(value)
        try:
            return str(_uuid.UUID(str(value)))
        except (ValueError, AttributeError):
            return str(value)


class User(Base):
    """User model for authentication."""

    __tablename__ = "users"

    user_id = Column(
        GUID(),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    username = Column(String(50), unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    # Email verification. `is_verified` is False until the user clicks
    # the link in the verification email; login is blocked until then.
    # We deliberately keep this separate from `is_active` so an admin
    # disable and "not yet verified" stay distinct concerns.
    is_verified = Column(Boolean, default=False, nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    def __repr__(self):
        return f"<User {self.username}>"
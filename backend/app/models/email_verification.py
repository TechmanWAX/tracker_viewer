"""EmailVerification model — single-use, time-limited tokens for the
"verify your email" link sent at registration and on resend.

Design notes
------------
* The raw token is 32 random bytes (`secrets.token_urlsafe(32)`) and
  is only ever known to the user (it travels in the email link). We
  store SHA-256(raw) in `token_hash`, not the raw value. A DB leak
  therefore does not let an attacker forge verification links.

* Single-use is enforced by `used_at`: once a row is consumed we set
  `used_at = now()` and a follow-up lookup by the same hash returns
  "already used". There is no grace period.

* Expiration is enforced by `expires_at` at lookup time. There is no
  background sweep — stale rows just sit there and get ignored. (A
  periodic cleanup job is a reasonable future addition.)

* Per-user uniqueness isn't required: a user may have several rows
  (e.g. the most recent resend over older ones). We delete the
  previous rows when issuing a new one to keep the table tidy.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, ForeignKey, Index, String, DateTime
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, CHAR

from app.db.base import Base
from app.models.user import GUID

__all__ = ["EmailVerification"]


class EmailVerification(Base):
    """A pending (or consumed) email verification token."""

    __tablename__ = "email_verifications"

    id = Column(
        GUID(),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    user_id = Column(
        GUID(),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    # SHA-256 hex of the raw token, 64 chars on both PostgreSQL and
    # SQLite. We use CHAR(64) so the column is fixed-width (faster
    # index lookups, and the length is implicit from the hash itself).
    token_hash = Column(CHAR(64), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    used_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The whole point of the table is the token lookup, so the
        # hash is indexed. `user_id` is indexed so /resend-verification
        # can clean up the previous row in O(1) lookups.
        Index("ix_email_verifications_token_hash", "token_hash", unique=True),
        Index("ix_email_verifications_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<EmailVerification user={self.user_id} "
            f"expires={self.expires_at} used={self.used_at}>"
        )

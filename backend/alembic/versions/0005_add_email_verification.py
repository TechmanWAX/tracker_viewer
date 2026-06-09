"""Add email verification

Adds:
  * `users.is_verified` BOOLEAN NOT NULL DEFAULT FALSE
  * `users.verified_at` TIMESTAMPTZ NULL
  * new `email_verifications` table (id, user_id, token_hash,
    expires_at, created_at, used_at) with a unique index on
    `token_hash` and a non-unique index on `user_id`.

Existing users (created before this migration) are treated as
"legacy verified" — `is_verified` defaults to TRUE for them via a
one-shot UPDATE in the same migration, so the new login gate doesn't
strand people who registered before email verification existed.

Revision ID: 0005_add_email_verification
Revises: 0004_add_job_content_hash
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0005_add_email_verification"
down_revision: Union[str, None] = "0004_add_job_content_hash"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # Add `is_verified` and `verified_at` to users. We add them with
    # `server_default=FALSE` for new users, then immediately flip the
    # flag to TRUE for any existing rows so the new login gate
    # doesn't lock out pre-verification users.
    op.add_column(
        "users",
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Backfill: everyone who existed before this migration is treated
    # as already verified. This is the safest default for a live
    # deployment: a stricter alternative would be to invalidate them
    # and force re-registration, but that's a separate decision.
    op.execute("UPDATE users SET is_verified = TRUE, verified_at = COALESCE(verified_at, created_at)")

    # The new email_verifications table. `id` and `user_id` use the
    # dialect-appropriate UUID type: native UUID on PostgreSQL, plain
    # String(36) on SQLite (the test fixtures use the GUID
    # TypeDecorator at the model level; here at the migration level
    # we just need a column type that both DBs can index and FK on).
    if is_pg:
        id_type = postgresql.UUID(as_uuid=True)
        fk_type = postgresql.UUID(as_uuid=True)
        sha_type = postgresql.CHAR(64)
    else:
        id_type = sa.String(length=36)
        fk_type = sa.String(length=36)
        sha_type = sa.String(length=64)

    op.create_table(
        "email_verifications",
        sa.Column("id", id_type, primary_key=True),
        sa.Column("user_id", fk_type, nullable=False),
        sa.Column("token_hash", sha_type, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_email_verifications_token_hash",
        "email_verifications",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "ix_email_verifications_user_id",
        "email_verifications",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_email_verifications_user_id", table_name="email_verifications")
    op.drop_index("ix_email_verifications_token_hash", table_name="email_verifications")
    op.drop_table("email_verifications")
    op.drop_column("users", "verified_at")
    op.drop_column("users", "is_verified")

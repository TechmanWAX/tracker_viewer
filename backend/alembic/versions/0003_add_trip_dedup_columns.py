"""Add original_filename + content_sha256 to trips for dedup

The upload endpoint now computes a SHA-256 hash while streaming the
file to disk, then rejects (409) any re-upload by the same user with
the same filename and same content. To make that check both fast and
race-free we add:

  - `trips.original_filename` (String 512) — the file name the user
    actually uploaded, distinct from `trip_name` which is a
    human-friendly label.
  - `trips.content_sha256` (CHAR 64) — hex SHA-256 of the file bytes.
  - a unique index on (user_id, original_filename, content_sha256)
    so the database enforces the dedup rule even under concurrent
    uploads of the same file by the same user.

The columns are nullable for backward compatibility with trips
created before this migration.

Revision ID: 0003_add_trip_dedup_columns
Revises: 0002_add_job_progress
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0003_add_trip_dedup_columns'
down_revision: Union[str, None] = '0002_add_job_progress'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use CHAR(64) on PostgreSQL for the hex SHA-256 (always exactly
    # 64 chars). On SQLite (used by tests) this falls back to VARCHAR
    # automatically when the dialect sees a non-recognized type, but
    # to be explicit we branch on the dialect.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sha_type = postgresql.CHAR(64)
    else:
        sha_type = sa.String(length=64)

    op.add_column(
        "trips",
        sa.Column("original_filename", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "trips",
        sa.Column("content_sha256", sha_type, nullable=True),
    )

    # Unique index that powers the dedup check. We name it explicitly
    # so the upload endpoint can rely on the constraint name in error
    # messages. NOT VALID is intentional: existing rows pre-dating
    # the column will be (NULL, NULL) and the unique index ignores
    # NULLs in PostgreSQL, so we don't need to backfill.
    op.create_index(
        "ix_trips_user_filename_hash",
        "trips",
        ["user_id", "original_filename", "content_sha256"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_trips_user_filename_hash", table_name="trips")
    op.drop_column("trips", "content_sha256")
    op.drop_column("trips", "original_filename")

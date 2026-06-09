"""Add content_sha256 to jobs table

The upload endpoint computes the file's SHA-256 while streaming it
to disk, then needs to pass that hash to the worker so it can copy
it onto the resulting Trip row. The hash is persisted on the Job
row (not passed as a Celery task argument) so the same code path
works for both dev (asyncio.create_task) and production (Celery
delay) dispatch.

This migration is paired with 0003 which adds the same column to
the trips table; the unique index there is what enforces the dedup
rule.

Revision ID: 0004_add_job_content_hash
Revises: 0003_add_trip_dedup_columns
Create Date: 2026-06-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0004_add_job_content_hash'
down_revision: Union[str, None] = '0003_add_trip_dedup_columns'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sha_type = postgresql.CHAR(64)
    else:
        sha_type = sa.String(length=64)

    op.add_column(
        "jobs",
        sa.Column("content_sha256", sha_type, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("jobs", "content_sha256")

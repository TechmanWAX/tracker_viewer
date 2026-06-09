"""Add progress columns to jobs table

The Celery worker writes parse progress to the jobs table so the
frontend can render a progress bar. Storing these as dedicated columns
(instead of inside the JSON `result` column) means we can use a single
atomic UPDATE statement and avoid any ORM/dict-tracking gotchas across
the worker / API server boundary.

Revision ID: 0002_add_job_progress
Revises: 0001_initial
Create Date: 2026-06-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002_add_job_progress'
down_revision: Union[str, None] = '0001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'jobs',
        sa.Column('progress', sa.Float(), nullable=True),
    )
    op.add_column(
        'jobs',
        sa.Column('processed_bytes', sa.BigInteger(), nullable=True),
    )
    op.add_column(
        'jobs',
        sa.Column('total_bytes', sa.BigInteger(), nullable=True),
    )
    # Partial index: most rows are terminal (done/failed) and we only
    # poll in-flight jobs. A small partial index on status='processing'
    # speeds up the worker's atomic UPDATE.
    op.create_index(
        'ix_jobs_processing',
        'jobs',
        ['job_id'],
        postgresql_where=sa.text("status = 'processing'"),
    )


def downgrade() -> None:
    op.drop_index('ix_jobs_processing', table_name='jobs')
    op.drop_column('jobs', 'total_bytes')
    op.drop_column('jobs', 'processed_bytes')
    op.drop_column('jobs', 'progress')

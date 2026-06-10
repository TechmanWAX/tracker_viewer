"""Add share_token and is_shared to trips table

Allows trip owners to generate a public link that anyone
(including unauthenticated visitors) can open. The share_token
is a short random string embedded in the URL; the is_shared
flag lets the UI know whether sharing is active.

Revision ID: 0009_add_trip_sharing
Revises: 0008_pwm_float
"""

from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0009_add_trip_sharing"
down_revision: Union[str, None] = "0008_pwm_float"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("trips", sa.Column("share_token", sa.String(64), nullable=True))
    op.add_column("trips", sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("ix_share_token", "trips", ["share_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_share_token")
    op.drop_column("trips", "is_shared")
    op.drop_column("trips", "share_token")

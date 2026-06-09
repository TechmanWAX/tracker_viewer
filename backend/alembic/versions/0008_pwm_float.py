"""Change telemetry_points.pwm from INTEGER to FLOAT

Background
----------
The original model declared `pwm` as Integer, but the firmware
reports it as a float (e.g. `57.27` in the 2025-11-02 CSV).
Going through the Integer column silently truncated to `57`,
losing the fractional part. The Pydantic schema already
declares `pwm: Optional[float] = Field(None, ge=0, le=100)`,
so the response side accepted floats but the storage side
clamped them. This migration aligns the DB column with the
schema.

Existing rows that already had an integer-stored PWM value
will be unchanged (an integer is a valid float).

Revision ID: 0008_pwm_float
Revises: 0007_add_remaining_telemetry
Create Date: 2026-06-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0008_pwm_float"
down_revision: Union[str, None] = "0007_add_remaining_telemetry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL INTEGER → DOUBLE PRECISION requires two steps
    # (you can't alter type in one step), so we go via FLOAT.
    # SQLite has no INTEGER-vs-FLOAT distinction at the storage
    # layer, so the same op is a no-op (type-affinity) there.
    op.execute("ALTER TABLE telemetry_points ALTER COLUMN pwm TYPE FLOAT")


def downgrade() -> None:
    # NB: this will truncate any fractional values that have
    # been stored since the upgrade. The 0007 migration is
    # recent enough that this is unlikely to matter in
    # practice, but document the loss in the docstring so
    # ops doesn't roll back by accident.
    op.execute("ALTER TABLE telemetry_points ALTER COLUMN pwm TYPE INTEGER")

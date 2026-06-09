"""Add remaining CSV telemetry fields to telemetry_points

Background
----------
The CSV schema (see backend/4 — CSV Parser Result.py) has 24
columns. Of those, the original `telemetry_points` model only
stored 18. Six fields were silently dropped on ingest:

  * `gps_speed`     — GPS-reported speed (km/h), distinct from the
                      wheel-rotation-based `speed` (some firmware
                      variants disagree; both are useful).
  * `gps_alt`       — GPS altitude (m above WGS84 ellipsoid).
  * `gps_heading`   — GPS bearing in degrees (0..360, sometimes
                      -1 when no fix is available; we keep it
                      unconstrained so the raw value passes
                      through).
  * `gps_distance`  — per-tick GPS distance (m), separate from
                      the running `distance` odometer column.
  * `phase_current` — phase-side current (A, motor controller
                      input), distinct from the battery-side
                      `current` (A). These two can differ when
                      the controller does field-weakening.
  * `totaldistance` — device-lifetime odometer (m). Differs from
                      `distance` which is the per-trip running
                      odometer (the source of the trip's
                      `total_distance_meters`).

The model also had columns for `torque`, `pwm`, `system_temp`,
`temp2`, `tilt`, `roll`, `mode`, `alert` that the schema didn't
expose and the worker didn't insert — a separate bug; this
migration only adds the truly-missing columns, the schema
expose + worker insert for the others comes in the same change
as the rest of this work.

All new columns are nullable Float. No backfill: existing rows
simply have NULL for these fields, which the dashboard renders
as `—` via the existing null-handling in `TelemetryDashboard`.

Revision ID: 0007_add_remaining_telemetry_fields
Revises: 0006_make_latlng_optional
Create Date: 2026-06-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
# NB: revision id is capped at VARCHAR(32) by the alembic_version
# table — `0007_add_remaining_telemetry_fields` is 41 chars, too
# long. Shorten, do not just truncate the file name, otherwise
# the migration can't even register.
revision: str = "0007_add_remaining_telemetry"
down_revision: Union[str, None] = "0006_make_latlng_optional"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # All columns are Float, nullable. The schema layer applies
    # the actual value-range checks (e.g. voltage>=0, battery
    # 0..100). Keeping the DB unconstrained means an old row with
    # a slightly-out-of-range value (sensor glitch) won't block
    # an ingest.
    for col in (
        "gps_speed",
        "gps_alt",
        "gps_heading",
        "gps_distance",
        "phase_current",
        "totaldistance",
    ):
        op.add_column(
            "telemetry_points",
            sa.Column(col, sa.Float(), nullable=True),
        )


def downgrade() -> None:
    for col in (
        "totaldistance",
        "phase_current",
        "gps_distance",
        "gps_heading",
        "gps_alt",
        "gps_speed",
    ):
        op.drop_column("telemetry_points", col)

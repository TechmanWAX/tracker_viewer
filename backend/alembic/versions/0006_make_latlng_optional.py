"""Make lat/lng optional + add has_gps trip flag

Background
----------
Some controller firmware variants produce CSVs without GPS
columns (date/time/speed/voltage/current/power/etc., but no
latitude/longitude). Until this migration these files were
silently rejected: the parser enforced lat/lng as critical
fields, the worker never got a chance to create the trip, and
the user saw a misleading "done (0/0 rows ingested)" status.

Schema changes
--------------
* `telemetry_points.latitude` and `telemetry_points.longitude`
  become nullable. A row with NULL lat/lng is valid — it just
  doesn't show up on the map.

* `trips.min_lat`, `trips.max_lat`, `trips.min_lon`,
  `trips.max_lon` become nullable. For a no-GPS trip, none of
  them have a value to aggregate.

* `trips.has_gps` (BOOLEAN, NOT NULL, default TRUE) is added.
  The worker sets it during ingest based on whether at least
  one telemetry row had a non-NULL lat/lng. Existing trips
  backfill to TRUE: their rows already had lat/lng, so a
  recompute would agree. The backfill is conservative and
  cheap (one SELECT, one UPDATE per table).

Revision ID: 0006_make_latlng_optional
Revises: 0005_add_email_verification
Create Date: 2026-06-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006_make_latlng_optional"
down_revision: Union[str, None] = "0005_add_email_verification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # telemetry_points: lat/lng → nullable.
    op.alter_column(
        "telemetry_points",
        "latitude",
        existing_type=sa.Float(),
        nullable=True,
    )
    op.alter_column(
        "telemetry_points",
        "longitude",
        existing_type=sa.Float(),
        nullable=True,
    )

    # trips: bbox columns → nullable. We don't need to touch
    # `total_distance_meters` — it was already nullable.
    op.alter_column(
        "trips",
        "min_lat",
        existing_type=sa.Float(),
        nullable=True,
    )
    op.alter_column(
        "trips",
        "max_lat",
        existing_type=sa.Float(),
        nullable=True,
    )
    op.alter_column(
        "trips",
        "min_lon",
        existing_type=sa.Float(),
        nullable=True,
    )
    op.alter_column(
        "trips",
        "max_lon",
        existing_type=sa.Float(),
        nullable=True,
    )

    # trips: add `has_gps` flag. NOT NULL with server default
    # TRUE so the column is non-breaking for existing rows.
    if is_pg:
        op.add_column(
            "trips",
            sa.Column(
                "has_gps",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
        )
    else:
        # SQLite doesn't accept `server_default` on Boolean in
        # older alembic/sqlalchemy combos, so we add as nullable
        # then backfill and tighten. Safe on any dialect.
        op.add_column(
            "trips",
            sa.Column("has_gps", sa.Boolean(), nullable=True),
        )
        op.execute("UPDATE trips SET has_gps = 1")
        op.alter_column(
            "trips",
            "has_gps",
            existing_type=sa.Boolean(),
            nullable=False,
        )

    # Backfill `has_gps` on PostgreSQL too: any trip that has at
    # least one telemetry point with both lat and lng is "has
    # GPS" by definition. The conservative answer is `true` —
    # the worker will write the actual value on the next upload
    # — and the recompute below keeps existing rows consistent.
    if is_pg:
        op.execute(
            """
            UPDATE trips t
            SET has_gps = EXISTS (
                SELECT 1
                FROM telemetry_points p
                WHERE p.trip_id = t.trip_id
                  AND p.latitude IS NOT NULL
                  AND p.longitude IS NOT NULL
            )
            """
        )
    else:
        op.execute(
            """
            UPDATE trips
            SET has_gps = (
                SELECT CASE WHEN COUNT(*) > 0 THEN 1 ELSE 0 END
                FROM telemetry_points p
                WHERE p.trip_id = trips.trip_id
                  AND p.latitude IS NOT NULL
                  AND p.longitude IS NOT NULL
            )
            """
        )


def downgrade() -> None:
    op.drop_column("trips", "has_gps")
    op.alter_column("trips", "max_lon", existing_type=sa.Float(), nullable=False)
    op.alter_column("trips", "min_lon", existing_type=sa.Float(), nullable=False)
    op.alter_column("trips", "max_lat", existing_type=sa.Float(), nullable=False)
    op.alter_column("trips", "min_lat", existing_type=sa.Float(), nullable=False)
    op.alter_column(
        "telemetry_points", "longitude", existing_type=sa.Float(), nullable=False
    )
    op.alter_column(
        "telemetry_points", "latitude", existing_type=sa.Float(), nullable=False
    )

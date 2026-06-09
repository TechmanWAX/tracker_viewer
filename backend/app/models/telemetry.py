"""Telemetry model - cross-dialect (PostgreSQL Geography / SQLite lat/lng)."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, String, DateTime, Float, Integer, ForeignKey, Index
from sqlalchemy.types import TypeDecorator, String as StringType

from app.db.base import Base
from app.models.user import GUID

__all__ = ["CompatGeography", "TelemetryPoint"]


class CompatGeography(TypeDecorator):
    """Geography(Point, 4326) on PostgreSQL; TEXT on other engines.

    On PostgreSQL the column is a native PostGIS geography index.
    On SQLite (or any non-postgres dialect) the column stores the
    WKT string ``POINT(lon lat)`` so it round-trips without error.
    """

    impl = StringType
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from geoalchemy2 import Geography
            return dialect.type_descriptor(Geography(geometry_type="POINT", srid=4326))
        return dialect.type_descriptor(StringType(255))

    def process_bind_param(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        if value is None:
            return None
        if hasattr(value, "wkt"):
            return value.wkt
        return str(value)

    def process_result_value(self, value, dialect):
        if dialect.name == "postgresql":
            return value
        return value


class TelemetryPoint(Base):
    """Telemetry point model."""

    __tablename__ = "telemetry_points"

    timestamp = Column(DateTime(timezone=True), nullable=False, primary_key=True)
    trip_id = Column(
        GUID(),
        ForeignKey("trips.trip_id", ondelete="CASCADE"),
        nullable=False,
        primary_key=True,
    )

    # Cross-dialect lat/lng – available on every backend.
    # Both are nullable because some controller firmware variants
    # don't emit GPS coordinates at all — those rows still carry
    # valid telemetry (speed/voltage/current/power/etc.) and we
    # ingest them, just without a map position. The trip-level
    # `has_gps` flag tells the UI which mode to render in.
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # PostGIS geography column – native on PostgreSQL, WKT TEXT on SQLite
    geom = Column(
        CompatGeography(),
        nullable=True,
    )

    # Wheel-rotation speed (km/h), non-negative.
    speed = Column(Float, nullable=False)
    # GPS-derived values, reported by the receiver. `gps_speed` is in
    # km/h; `gps_alt` is metres above WGS84; `gps_heading` is degrees
    # (0..360 from the receiver, sometimes -1 when no fix).
    gps_speed = Column(Float, nullable=True)
    gps_alt = Column(Float, nullable=True)
    gps_heading = Column(Float, nullable=True)
    # Per-tick GPS distance (m). Distinct from `distance` (the per-trip
    # running odometer) — some firmware uses GPS distance, some uses
    # the wheel-rotation odometer, some both.
    gps_distance = Column(Float, nullable=True)
    # Battery-side voltage (V) and currents (A). `current` is the
    # battery pack current; `phase_current` is the motor-side
    # current, which can diverge during field-weakening. Both are
    # signed (positive = draw, negative = regen).
    voltage = Column(Float, nullable=True)
    current = Column(Float, nullable=True)
    phase_current = Column(Float, nullable=True)
    power = Column(Float, nullable=True)
    # Motor controller telemetry.
    torque = Column(Float, nullable=True)
    pwm = Column(Float, nullable=True)
    battery_level = Column(Float, nullable=True)
    # Two odometers: `distance` is the per-trip running odometer
    # (monotonic within a trip, reset to 0 between trips), used
    # to compute `trips.total_distance_meters = MAX - MIN`.
    # `totaldistance` is the device-lifetime odometer (never
    # resets), useful for the fleet-level "km on this device"
    # view.
    distance = Column(Float, nullable=True)
    totaldistance = Column(Float, nullable=True)
    # Temperatures in °C. `system_temp` is the controller MOSFET /
    # heatsink; `temp2` is the motor or battery (firmware-defined).
    system_temp = Column(Float, nullable=True)
    temp2 = Column(Float, nullable=True)
    # Inertial / attitude. `tilt` is pitch (forward/back), `roll`
    # is side-to-side; both in degrees.
    tilt = Column(Float, nullable=True)
    roll = Column(Float, nullable=True)
    # Status strings: `mode` is the controller's current drive
    # mode (e.g. "1"=manual, "2"=eco), `alert` is a non-fatal
    # warning code. Bounded length so a runaway firmware can't
    # balloon the row.
    mode = Column(String(20), nullable=True)
    alert = Column(String(50), nullable=True)

    __table_args__ = (
        Index("idx_telemetry_playback", "trip_id", "timestamp"),
    )

    def __repr__(self):
        return f"<TelemetryPoint {self.trip_id} @ {self.timestamp}>"

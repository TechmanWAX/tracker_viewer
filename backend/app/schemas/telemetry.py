"""Telemetry-related Pydantic schemas."""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class TelemetryPointBase(BaseModel):
    """Base telemetry point schema.

    Sign conventions for the power-train fields (this is an EV
    controller, not a generic device):
      * `speed`, `voltage`, `battery_level` are non-negative.
      * `current` and `power` are signed: positive = drawing from
        the battery (acceleration), negative = regen braking.
        Hard-capping them at 0 in the schema silently turns real
        regen readings into validation errors and breaks GET
        /points for the affected trip. See the trip
        `a8f86b4b-…` that started failing on 2025-11-02
        recordings with current=-0.63 / power=-31.83.

    Latitude / longitude are optional because some controller
    firmware variants don't emit GPS coordinates at all; we
    still ingest the rest of the telemetry. When a value *is*
    present it still has to be within physical bounds.

    All other fields are optional too — a row that was logged
    by a firmware version that doesn't emit, say, `gps_heading`
    is still a valid row, the column just stays NULL.
    """
    timestamp: datetime
    speed: float = Field(..., ge=0, le=200)
    # GPS-derived
    gps_speed: Optional[float] = Field(None, ge=0, le=200)
    gps_alt: Optional[float] = Field(None, ge=-500, le=10000)
    # Heading is unconstrained: receivers report -1 (no fix) or
    # 0..360 depending on the firmware. Capping at 0..360 would
    # silently drop "no fix" rows.
    gps_heading: Optional[float] = None
    gps_distance: Optional[float] = Field(None, ge=0)
    # Power-train
    voltage: Optional[float] = Field(None, ge=0)
    # Signed: regen braking produces negative readings.
    current: Optional[float] = None
    phase_current: Optional[float] = None
    power: Optional[float] = None
    torque: Optional[float] = None
    # PWM is a duty-cycle percent (0..100). Some firmware reports
    # it as an integer string ("90") and others as a float ("90.5").
    pwm: Optional[float] = Field(None, ge=0, le=100)
    battery_level: Optional[float] = Field(None, ge=0, le=100)
    # Odometer. `distance` is the per-trip running odometer; the
    # trip's `total_distance_meters` is computed as
    # MAX(distance)-MIN(distance). `totaldistance` is the device's
    # lifetime odometer — never resets.
    distance: Optional[float] = Field(None, ge=0)
    totaldistance: Optional[float] = Field(None, ge=0)
    # Vehicle state
    system_temp: Optional[float] = Field(None, ge=-50, le=200)
    temp2: Optional[float] = Field(None, ge=-50, le=200)
    tilt: Optional[float] = Field(None, ge=-180, le=180)
    roll: Optional[float] = Field(None, ge=-180, le=180)
    mode: Optional[str] = Field(None, max_length=20)
    alert: Optional[str] = Field(None, max_length=50)
    # Position
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)


class TelemetryPointCreate(TelemetryPointBase):
    """Schema for creating telemetry points."""
    trip_id: str


class TelemetryPoint(TelemetryPointBase):
    """Schema for telemetry point responses."""
    trip_id: str
    timestamp: datetime

    model_config = {"from_attributes": True}


class TelemetryPointList(BaseModel):
    """Schema for telemetry point list responses."""
    trip_id: str
    points: List[TelemetryPoint]
    total: int


class TelemetryQueryParams(BaseModel):
    """Query parameters for telemetry endpoint."""
    bbox: Optional[str] = Field(
        None,
        description="Bounding box: minLon,minLat,maxLon,maxLat"
    )
    from_ts: Optional[datetime] = Field(
        None,
        description="Start timestamp for filtering"
    )
    to_ts: Optional[datetime] = Field(
        None,
        description="End timestamp for filtering"
    )
    limit: int = Field(default=1000, ge=1, le=50000)
    offset: int = Field(default=0, ge=0)
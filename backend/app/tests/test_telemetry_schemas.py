"""Regression tests for telemetry response schemas.

The point of this file is to lock in the sign-convention rules for
the power-train fields, so a future "let's be defensive and add
ge=0 to current/power" rewrite doesn't silently re-break the map
for any trip with regen-braking readings.

The 2025-11-02 EV-controller CSV had rows like `current=-0.63,
power=-31.83` (negative = regen, perfectly physical), which the
DB stored fine but the response schema rejected — making
GET /trips/{id}/points return 500 and the map render blank.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.schemas.telemetry import (
    TelemetryPoint,
    TelemetryPointCreate,
)


def _kwargs(**overrides):
    """Baseline valid row. Override any field per test."""
    base = dict(
        trip_id="00000000-0000-0000-0000-000000000000",
        timestamp=datetime.fromisoformat("2025-11-02T13:00:20.176"),
        latitude=55.6766,
        longitude=37.6531,
        speed=12.11,
        voltage=50.53,
        current=-0.63,
        power=-31.83,
        battery_level=51.0,
    )
    base.update(overrides)
    return base


def test_telemetry_point_accepts_negative_current_and_power():
    """Regen braking: negative current/power must validate.

    This is the exact row shape that broke GET /points for the
    2025-11-02 trip.
    """
    p = TelemetryPoint(**_kwargs())
    assert p.current == -0.63
    assert p.power == -31.83


def test_telemetry_point_accepts_positive_current_and_power():
    """Acceleration: positive current/power still validates."""
    p = TelemetryPoint(**_kwargs(current=10.5, power=525.0))
    assert p.current == 10.5
    assert p.power == 525.0


def test_telemetry_point_accepts_zero_current_and_power():
    """Coast: zero is the boundary — must still validate."""
    p = TelemetryPoint(**_kwargs(current=0.0, power=0.0))
    assert p.current == 0.0
    assert p.power == 0.0


def test_telemetry_point_accepts_missing_current_and_power():
    """Sensors sometimes go missing — both must be optional."""
    p = TelemetryPoint(**_kwargs(current=None, power=None))
    assert p.current is None
    assert p.power is None


def test_telemetry_point_rejects_negative_speed():
    """Speed is the wheel-rotation sensor — never negative."""
    with pytest.raises(ValidationError):
        TelemetryPoint(**_kwargs(speed=-1.0))


def test_telemetry_point_rejects_battery_over_100():
    """Battery level is a percentage 0..100."""
    with pytest.raises(ValidationError):
        TelemetryPoint(**_kwargs(battery_level=101.0))


def test_telemetry_point_create_also_allows_negative_current_power():
    """Create schema inherits from base, so the same fix applies
    to ingestion — a fresh upload with regen data must round-trip
    cleanly through Create → DB → response."""
    p = TelemetryPointCreate(**_kwargs())
    assert p.current == -0.63
    assert p.power == -31.83


def test_telemetry_point_create_rejects_out_of_range_latitude():
    """Lat/lng bounds are enforced on ingestion (TelemetryPointCreate)
    so a corrupted CSV row can't poison the DB with impossible coords."""
    with pytest.raises(ValidationError):
        TelemetryPointCreate(**_kwargs(latitude=91.0))
    with pytest.raises(ValidationError):
        TelemetryPointCreate(**_kwargs(longitude=181.0))


# --- new CSV fields (added in migration 0007) -------------------------
# The CSV schema (see backend/4 — CSV Parser Result.py) has more
# columns than the original telemetry schema exposed:
# gps_speed, gps_alt, gps_heading, gps_distance, phase_current,
# torque, pwm, totaldistance, system_temp, temp2, tilt, roll, mode,
# alert. The schema now accepts all of them; the tests below lock
# in the bounds decisions so a future "let's add ge=0 to be safe"
# rewrite doesn't break regen reads or "no-fix" GPS rows.


def test_telemetry_point_round_trips_full_csv_row():
    """A row containing every CSV field must round-trip through
    TelemetryPoint without losing or re-typing anything."""
    p = TelemetryPoint(
        **_kwargs(
            gps_speed=11.8,
            gps_alt=156.0,
            gps_heading=87.5,
            gps_distance=2.0,
            phase_current=-0.61,
            torque=1.2,
            pwm=15.0,
            distance=1000.0,
            totaldistance=12345.0,
            system_temp=42.0,
            temp2=38.0,
            tilt=-0.5,
            roll=0.2,
            mode="1",
            alert=None,
        )
    )
    assert p.gps_speed == 11.8
    assert p.phase_current == -0.61
    assert p.torque == 1.2
    assert p.pwm == 15.0
    assert p.totaldistance == 12345.0
    assert p.mode == "1"
    assert p.alert is None


def test_telemetry_point_accepts_negative_phase_current():
    """Phase current is signed for the same reason `current` is
    (regen → negative). Symmetric with the regen test above."""
    p = TelemetryPoint(**_kwargs(phase_current=-2.0))
    assert p.phase_current == -2.0


def test_telemetry_point_accepts_gps_heading_minus_one():
    """GPS receivers report `-1` to mean "no fix this tick". Capping
    heading at 0..360 would silently drop those rows."""
    p = TelemetryPoint(**_kwargs(gps_heading=-1.0))
    assert p.gps_heading == -1.0


def test_telemetry_point_rejects_gps_alt_out_of_range():
    """gps_alt is bounded to a physical range (-500 m to +10000 m)
    to catch sensor garbage that would otherwise pollute the chart."""
    with pytest.raises(ValidationError):
        TelemetryPoint(**_kwargs(gps_alt=12000.0))
    with pytest.raises(ValidationError):
        TelemetryPoint(**_kwargs(gps_alt=-1000.0))


def test_telemetry_point_rejects_pwm_above_100():
    """PWM is a duty-cycle percent."""
    with pytest.raises(ValidationError):
        TelemetryPoint(**_kwargs(pwm=150.0))


def test_telemetry_point_rejects_negative_tilt_or_roll():
    """Tilt/roll use the same [-180, 180] range convention as
    pitch/yaw in IMU data."""
    with pytest.raises(ValidationError):
        TelemetryPoint(**_kwargs(tilt=200.0))
    with pytest.raises(ValidationError):
        TelemetryPoint(**_kwargs(roll=-200.0))


def test_telemetry_point_accepts_all_new_fields_as_optional():
    """Every new field is nullable — a row from a firmware that
    doesn't emit, say, `gps_heading` is still a valid row."""
    p = TelemetryPoint(
        **_kwargs(
            gps_speed=None,
            gps_alt=None,
            gps_heading=None,
            gps_distance=None,
            phase_current=None,
            torque=None,
            pwm=None,
            totaldistance=None,
            system_temp=None,
            temp2=None,
            tilt=None,
            roll=None,
            mode=None,
            alert=None,
        )
    )
    assert p.gps_speed is None
    assert p.mode is None

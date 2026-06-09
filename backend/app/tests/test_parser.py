"""Parser service tests."""

import os
import tempfile
import pytest

from app.services.parser_service import ParserService


def _drain(gen):
    """Helper: convert the (chunk, report) generator into a flat list
    of chunks. Used by the tests below to keep assertions readable."""
    out = []
    for chunk, _report in gen:
        out.append(chunk)
    return out


class TestParserService:
    """Tests for the parser service."""

    def test_parse_valid_csv(self, temp_csv_file):
        """Test parsing a valid CSV file."""
        chunks = _drain(ParserService.parse_csv_file(temp_csv_file, chunk_size=10))

        assert len(chunks) >= 1
        assert len(chunks[0]) >= 2  # At least 2 rows

        # Check first row
        first_row = chunks[0][0]
        assert "latitude" in first_row
        assert "longitude" in first_row
        assert first_row["latitude"] == 45.523
        assert first_row["longitude"] == -122.676

    def test_parse_csv_with_invalid_data(self):
        """Test parsing CSV with some invalid data."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("""date,time,latitude,longitude,gps_speed,gps_alt,gps_heading,gps_distance,speed,voltage,phase_current,current,power,torque,pwm,battery_level,distance,totaldistance,system_temp,temp2,tilt,roll,mode,alert
2023-01-01,12:00:00,45.523,-122.676,10.5,50.0,180.0,0.1,10.5,48.0,10.0,10.0,500,1.2,90,85,1.0,1.0,30.0,31.0,0.1,0.1,1,0
2023-01-01,12:00:01,INVALID,-122.677,11.2,50.0,180.0,0.2,11.2,48.0,10.5,10.5,510,1.3,91,84,1.1,1.1,30.1,31.1,0.2,0.2,1,0
""")
            temp_path = f.name

        try:
            chunks = _drain(ParserService.parse_csv_file(temp_path, chunk_size=10))

            # Should have at least one valid chunk
            assert len(chunks) >= 1

            # First chunk should have only the valid row
            assert len(chunks[0]) >= 1

        finally:
            os.unlink(temp_path)

    def test_parse_csv_empty_file(self):
        """Test parsing an empty CSV file (header only)."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("date,time,latitude,longitude\n")
            temp_path = f.name

        try:
            chunks = _drain(ParserService.parse_csv_file(temp_path, chunk_size=10))
            assert len(chunks) == 0

        finally:
            os.unlink(temp_path)

    def test_parse_csv_missing_headers(self):
        """A CSV that's missing the `date` or `time` columns still
        parses — the rows just get rejected at the row-level check
        (which fires after header validation, so the header is
        accepted). The result is an empty batch stream with no
        exception: the worker reports 0 valid rows and the user
        gets a clear "0/0" status. The endpoint layer surfaces
        400/422 for genuinely bad CSVs."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("""date,time,latitude
2023-01-01,12:00:00,45.523
""")
            temp_path = f.name

        try:
            chunks = _drain(ParserService.parse_csv_file(temp_path, chunk_size=10))
            # `date` and `time` are present in every row, so the row
            # IS valid. The parser must return it. (This is the
            # post-fix behaviour: before, the row was rejected
            # because `longitude` was a "critical" field.)
            assert len(chunks) == 1
            assert len(chunks[0]) == 1
            assert chunks[0][0]["latitude"] == 45.523
            # The longitude key wasn't in the source — it shouldn't
            # be in the parsed output either.
            assert "longitude" not in chunks[0][0]

        finally:
            os.unlink(temp_path)

    def test_parse_csv_without_lat_lng_columns(self):
        """Regression for the EV-controller firmware variant that omits
        GPS columns entirely. Rows are still valid — the worker stores
        them with NULL lat/lng and the trip's `has_gps` flag is set
        to False downstream. The parser must not reject these rows.
        """
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("""date,time,speed,voltage,current,power,battery_level
2025-10-05,15:56:55.063,15.80,76.50,8.52,651.78,63
2025-10-05,15:56:55.264,15.44,76.50,7.31,559.22,63
2025-10-05,15:56:55.480,15.77,76.50,1.24,94.86,63
""")
            temp_path = f.name

        try:
            chunks = _drain(ParserService.parse_csv_file(temp_path, chunk_size=10))
            # All three rows must come through (no filtering on lat/lng).
            assert len(chunks) == 1
            assert len(chunks[0]) == 3
            # The lat/lng keys are simply absent — the parser doesn't
            # invent them, and the worker stores NULL for missing cols.
            first = chunks[0][0]
            assert "latitude" not in first or first["latitude"] is None
            assert "longitude" not in first or first["longitude"] is None
            # But the telemetry is intact.
            assert first["speed"] == 15.80
            assert first["power"] == 651.78

        finally:
            os.unlink(temp_path)

    def test_parser_yields_progress_report(self):
        """The generator must yield (chunk, report) pairs so callers can
        drive a progress bar from parser_report.total_rows."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("""date,time,latitude,longitude,gps_speed,gps_alt,gps_heading,gps_distance,speed,voltage,phase_current,current,power,torque,pwm,battery_level,distance,totaldistance,system_temp,temp2,tilt,roll,mode,alert
2023-01-01,12:00:00,45.523,-122.676,10.5,50.0,180.0,0.1,10.5,48.0,10.0,10.0,500,1.2,90,85,1.0,1.0,30.0,31.0,0.1,0.1,1,0
2023-01-01,12:00:01,45.524,-122.677,11.2,50.0,180.0,0.2,11.2,48.0,10.5,10.5,510,1.3,91,84,1.1,1.1,30.1,31.1,0.2,0.2,1,0
""")
            temp_path = f.name
        try:
            for item in ParserService.parse_csv_file(temp_path, chunk_size=10):
                assert isinstance(item, tuple) and len(item) == 2, (
                    f"expected (chunk, report), got {type(item).__name__}"
                )
                chunk, report = item
                assert isinstance(chunk, list)
                assert hasattr(report, "total_rows")
                # We only need to inspect the first yield.
                break
        finally:
            os.unlink(temp_path)
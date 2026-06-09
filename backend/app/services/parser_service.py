"""Parser service - wraps the CSV parser for Celery tasks."""

import csv
import io
from typing import Generator, List, Dict, Any, Optional, Tuple

from app.core.config import get_settings


class ParserService:
    """Service for CSV parsing and validation."""

    SCHEMA = {
        'date': 'date',
        'time': 'time',
        'latitude': float,
        'longitude': float,
        'gps_speed': float,
        'gps_alt': float,
        'gps_heading': float,
        'gps_distance': float,
        'speed': float,
        'voltage': float,
        'phase_current': float,
        'current': float,
        'power': float,
        'torque': float,
        'pwm': float,
        'battery_level': float,
        'distance': float,
        'totaldistance': float,
        'system_temp': float,
        'temp2': float,
        'tilt': float,
        'roll': float,
        'mode': str,
        'alert': str,
    }

    @staticmethod
    def parse_csv_file(
        file_path: str,
        chunk_size: int = 1000,
    ) -> Generator[Tuple[List[Dict[str, Any]], Any], None, None]:
        """
        Parse CSV file and yield (chunk, report) pairs.

        `chunk` is a batch of validated rows (non-None lat/lng) ready for
        bulk insertion. `report` is the running ParsingReport from the
        underlying GPSTelemetryParser, with `total_rows` (raw lines read),
        `valid_rows` (lines that passed type-cast), and `error_rows`.

        Callers can use `report.total_rows` together with a precomputed
        line count to drive a progress bar.
        """
        try:
            # Import the parser module
            from CSV_Parser_Result import GPSTelemetryParser

            parser = GPSTelemetryParser(chunk_size=chunk_size)

            for batch, report in parser.parse(file_path):
                # The parser already enforces date+time as critical
                # fields. We don't filter on lat/lng here: controller
                # firmware that doesn't emit GPS coordinates is still
                # useful to ingest (speed, voltage, current, power,
                # battery, etc.). The downstream worker decides whether
                # the resulting trip has GPS data and sets
                # `trip.has_gps` accordingly.
                if batch:
                    yield batch, report

        except Exception as e:
            raise RuntimeError(f"CSV parsing failed: {str(e)}") from e

    @staticmethod
    def validate_csv_header(file_path: str) -> bool:
        """Validate that CSV file has required headers."""
        try:
            with open(file_path, 'r', encoding='utf-8-sig', errors='replace') as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    return False
                
                # Strip whitespace from headers
                headers = {h.strip() for h in reader.fieldnames}
                required = set(ParserService.SCHEMA.keys())
                
                return required.issubset(headers)
        except Exception:
            return False
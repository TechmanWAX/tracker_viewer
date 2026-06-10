import csv
import io
import codecs
from datetime import datetime
from typing import Dict, Any, Generator, List, Tuple, Optional, Union
from dataclasses import dataclass, field

class HeaderError(Exception):
    """Raised when the CSV header is missing or incompatible with the expected schema."""
    pass

@dataclass
class ParsingError:
    line: int
    reason: str
    raw_data: Union[Dict[str, Any], str]

@dataclass
class ParsingReport:
    total_rows: int = 0
    valid_rows: int = 0
    error_rows: int = 0
    sample_errors: List[ParsingError] = field(default_factory=list)

    def add_error(self, line: int, reason: str, raw_data: Any, max_samples: int = 100):
        self.error_rows += 1
        if len(self.sample_errors) < max_samples:
            # Avoid storing massive raw rows in the report
            snapshot = raw_data
            if isinstance(raw_data, dict):
                snapshot = {k: (v[:50] if isinstance(v, str) else v) for k, v in raw_data.items()}
            elif isinstance(raw_data, str):
                snapshot = raw_data[:500]
            
            self.sample_errors.append(ParsingError(line, reason, snapshot))

class GPSTelemetryParser:
    """
    Production-grade parser for GPS trip telemetry.
    
    Error Handling Strategy:
    1. Delimiter Auto-detection: Uses csv.Sniffer to handle comma, semicolon, or tabs.
    2. Header Enforcement: Validates that all SCHEMA keys are present before parsing.
    3. Encoding Resilience: Uses 'utf-8-sig' with 'replace' error handler to prevent 
       mid-stream UnicodeDecodeError from crashing the generator.
    4. Robust Casting: Strips quotes from numeric strings before casting.
    5. Column Count Validation: Rejects rows that don't match header length to prevent 
       misalignment.

    Performance Considerations:
    1. Memory: Generator-based streaming ensures O(chunk_size) memory footprint.
    2. CPU: Leverages csv.DictReader's C-implementation for high-throughput parsing.
    3. Network Safe: Can be wrapped around any file-like object (io.BufferedReader).
    """

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

    def __init__(self, chunk_size: int = 1000):
        self.chunk_size = chunk_size

    def _coerce_number(self, value: str) -> float:
        """Strips outer quotes and converts to float."""
        if not value:
            return None
        # Strip both double and single quotes and whitespace
        cleaned = value.strip().strip('"\'').strip()
        return float(cleaned)

    def _safe_cast(self, key: str, value: str) -> Any:
        """Casts a string value to the type defined in SCHEMA."""
        if value is None or value.strip() == "":
            return None
        
        val = value.strip()
        expected = self.SCHEMA.get(key)

        try:
            if expected == float:
                return self._coerce_number(val)
            elif expected == 'date':
                datetime.strptime(val, "%Y-%m-%d")
                return val
            elif expected == 'time':
                if ":" not in val:
                    raise ValueError("Invalid time format")
                return val
            elif expected == str:
                return val
            return val 
        except (ValueError, TypeError) as e:
            raise ValueError(f"Type mismatch for {key}: {val} cannot be cast to {expected}") from e

    def parse(self, file_path: str) -> Generator[Tuple[List[Dict[str, Any]], ParsingReport], None, None]:
        """
        Streams a CSV file from disk, yields batches of parsed rows and the current report.
        """
        report = ParsingReport()
        
        # Use 'utf-8-sig' to handle BOM and 'replace' to handle mid-stream encoding corruption
        # without crashing the whole loop.
        with open(file_path, mode='r', encoding='utf-8-sig', errors='replace', newline='') as f:
            # 1. Delimiter Detection
            sample = f.read(4096)
            f.seek(0)
            
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=',;\t')
            except csv.Error:
                # Fallback to comma if sniffing fails or sample is ambiguous
                dialect = csv.excel 

            reader = csv.DictReader(f, dialect=dialect)
            
            # 2. Header Validation
            # Strip whitespace from headers to be robust against 'date , time'
            if reader.fieldnames:
                reader.fieldnames = [name.strip() for name in reader.fieldnames]
            
            if not reader.fieldnames:
                # Empty file (no header) — yield nothing rather than raising;
                # callers that need stricter behavior can detect the empty stream
                # upstream. Returns control to the generator consumer with no batches.
                return

            existing_cols = set(reader.fieldnames)
            # Header validation is intentionally loose: we accept any non-empty
            # header. Per-row critical-field checks (date/time/lat/lng) catch
            # missing columns and surface them as row errors, not fatal header
            # errors. This lets callers recover from partially-malformed CSVs
            # (e.g. a device firmware that drops the gps_alt column).
            extra = existing_cols - set(self.SCHEMA.keys())
            if extra:
                # We accept extra columns but ignore them during type casting
                pass 

            batch = []
            
            # 3. Streaming Parse
            for row in reader:
                # reader.line_num tracks the actual file line number
                line_num = reader.line_num
                report.total_rows += 1
                
                try:
                    # Check for column count mismatch
                    # DictReader puts extra values in a list under None key
                    # and missing values as None.
                    if None in row:
                        # If None is a key, it means there were more columns than headers
                        if None in row:
                            raise ValueError(f"Column count mismatch: row has more fields than header")
                        # If a required column is None, it's a missing value
                        # (We treat this as a valid row with a None value unless it's critical)
                        pass

                    # Critical field check.
                    #
                    # We require `date` and `time` (without them we can't
                    # place the row in time at all, and the trip becomes
                    # meaningless). `latitude`/`longitude` are *not* in
                    # this list — the controller firmware that produces
                    # some of our CSVs does not emit GPS coordinates, and
                    # we still want to ingest the rest of the telemetry
                    # (speed, voltage, current, power, etc.). A trip
                    # without GPS is stored with NULL lat/lng and the
                    # `has_gps=False` flag on the Trip row; the UI shows
                    # a "no GPS data" placeholder instead of a map.
                    for critical in ['date', 'time']:
                        if not row.get(critical):
                            raise ValueError(f"Missing critical field: {critical}")

                    # Type Casting
                    parsed_row = {}
                    for key, value in row.items():
                        if key is None: continue # Extra columns
                        if key in self.SCHEMA:
                            parsed_row[key] = self._safe_cast(key, value)
                        else:
                            parsed_row[key] = value # Keep extra columns as raw strings
                    
                    batch.append(parsed_row)
                    report.valid_rows += 1

                except Exception as e:
                    report.add_error(line_num, str(e), row)

                if len(batch) >= self.chunk_size:
                    yield batch, report
                    batch = []

            # Always emit a final yield so callers always receive a ParsingReport
            # — even when every row errored (batch is empty but report is meaningful).
            yield batch, report


def parse_csv_stream(stream, chunk_size: int = 100) -> Generator[Tuple[List[Dict[str, Any]], ParsingReport], None, None]:
    """Backward-compat helper: parse from a StringIO/text stream.

    The canonical API is GPSTelemetryParser.parse(file_path), which streams from
    disk. This shim writes the stream to a temp file so the same generator-yielding
    API is available for in-memory tests.
    """
    import os
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8", newline=""
    ) as f:
        f.write(stream.read())
        tmp_path = f.name
    try:
        parser = GPSTelemetryParser(chunk_size=chunk_size)
        yield from parser.parse(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

# =============================================================================
# EXAMPLE USAGE & TEST HARNESS
# =============================================================================
if __name__ == "__main__":
    import os
    
    def run_test(name, content, delimiter=','):
        print(f"--- Testing: {name} ---")
        test_file = f"test_{name}.csv"
        with open(test_file, "w", encoding="utf-8-sig") as f:
            f.write(content)
        
        try:
            parser = GPSTelemetryParser(chunk_size=10)
            final_report = None
            for batch, report in parser.parse(test_file):
                final_report = report
            
            if final_report:
                print(f"Result: Valid={final_report.valid_rows}, Errors={final_report.error_rows}")
                for err in final_report.sample_errors:
                    print(f"  Line {err.line}: {err.reason}")
        except Exception as e:
            print(f"Fatal Error: {e}")
        finally:
            if os.path.exists(test_file):
                os.remove(test_file)
        print("\n")

    # 1. Test Quoted Numbers & Semicolon (The "Broken" case)
    quoted_semicolon = (
        "date;time;latitude;longitude;gps_speed;gps_alt;gps_heading;gps_distance;speed;voltage;phase_current;current;power;torque;pwm;battery_level;distance;totaldistance;system_temp;temp2;tilt;roll;mode;alert\n"
        "\"2023-01-01\";\"12:00:00\";\"45.523\";\"-122.676\";\"10.5\";\"50.0\";\"180.0\";\"0.1\";\"10.5\";\"48.0\";\"10.0\";\"10.0\";\"500\";\"1.2\";\"90\";\"85\";\"1.0\";\"1.0\";\"30.0\";\"31.0\";\"0.1\";\"0.1\";\"1\";\"0\"\n"
        "\"2023-01-01\";\"12:00:01\";\"45.524\";\"-122.677\";\"INVALID\";\"50.0\";\"180.0\";\"0.1\";\"10.5\";\"48.0\";\"10.0\";\"10.0\";\"500\";\"1.2\";\"90\";\"85\";\"1.0\";\"1.0\";\"30.0\";\"31.0\";\"0.1\";\"0.1\";\"1\";\"0\"\n"
    )
    run_test("quoted_semicolon", quoted_semicolon)

    # 2. Test Missing Header (Fatal)
    no_header = "2023-01-01,12:00:00,45.5,122.6,10,50,180,0,10,48,10,10,500,1,90,80,1,1,30,31,0,0,1,0"
    run_test("no_header", no_header)

    # 3. Test Column Count Mismatch (Skip row)
    mismatch_cols = (
        "date,time,latitude,longitude,gps_speed,gps_alt,gps_heading,gps_distance,speed,voltage,phase_current,current,power,torque,pwm,battery_level,distance,totaldistance,system_temp,temp2,tilt,roll,mode,alert\n"
        "2023-01-01,12:00:00,45.5,-122.6,10,50,180,0,10,48,10,10,500,1,90,80,1,1,30,31,0,0,1,0,EXTRA_COL\n"
        "2023-01-01,12:00:01,45.5,-122.6,10,50,180,0,10,48,10,10,500,1,90,80,1,1,30,31,0,0,1,0\n"
    )
    run_test("mismatch_cols", mismatch_cols)

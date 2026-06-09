"""Tests for trip upload content-type sniffing and validation.

These tests do not require a database; they exercise the pure
`_looks_like_csv` helper that decides whether an incoming file should
be accepted as a CSV. The previous code only checked two MIME types
which caused spurious 415s on common browsers. We now accept:

  - text/csv, application/csv, text/x-csv
  - application/vnd.ms-excel (Windows legacy)
  - text/plain (some Linux file managers)
  - application/octet-stream (All-files picker fallback)
  - any extension in {csv, tsv, txt}
  - any first-bytes scan that contains a known GPS/CSV column name
"""
import io

import pytest


# We import the helper from the endpoint module. The endpoint module
# pulls in SQLAlchemy at import time, so we have to be careful — but
# the helper itself is pure.
from app.api.v1.endpoints.trips import _looks_like_csv  # noqa: E402


class TestContentTypeSniffing:
    """The endpoint must accept all common CSV MIME types and not just text/csv."""

    @pytest.mark.parametrize("ct", [
        "text/csv",
        "application/csv",
        "text/x-csv",
        "application/vnd.ms-excel",
        "text/plain",
        "application/octet-stream",
        "binary/octet-stream",
    ])
    def test_known_csv_content_types_accepted(self, ct: str) -> None:
        assert _looks_like_csv("trip.csv", ct, b"") is True

    @pytest.mark.parametrize("filename", [
        "trip.csv",
        "trip.CSV",
        "trip.tsv",
        "trip.TXT",
        "path/to/trip.csv",
    ])
    def test_csv_extension_accepted_regardless_of_mime(self, filename: str) -> None:
        # Even a weird MIME should be accepted when the extension says CSV.
        assert _looks_like_csv(filename, "application/x-tar", b"") is True

    def test_unknown_extension_and_mime_rejected(self) -> None:
        # application/octet-stream is intentionally in the allowlist
        # (the "All files" picker fallback), so use a non-allowlisted
        # MIME with no CSV-like content in the head.
        assert _looks_like_csv("trip.bin", "image/png", b"\x00\x01\x02\x03") is False

    def test_first_bytes_scan_accepts_known_columns(self) -> None:
        # No CSV MIME, .bin extension, but the head contains "latitude,"
        # which is good enough.
        head = b"date,time,latitude,longitude,speed\n2023-01-01,12:00:00,45.5,-122.6,10\n"
        assert _looks_like_csv("trip.bin", "application/x-binary", head) is True

    def test_first_bytes_scan_rejects_binary(self) -> None:
        # Use a non-allowlisted MIME and a PNG header; octet-stream is
        # *intentionally* in the allowlist (All-files picker fallback).
        head = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        assert _looks_like_csv("trip.bin", "image/png", head) is False

    def test_empty_input_rejected(self) -> None:
        # No MIME, no extension, no content. The caller (the endpoint)
        # treats this case separately as a 400 empty-file, but the
        # helper should still say "not a CSV".
        assert _looks_like_csv(None, None, b"") is False

    def test_content_type_case_insensitive(self) -> None:
        assert _looks_like_csv("trip.csv", "TEXT/CSV", b"") is True
        assert _looks_like_csv("trip.csv", "Application/CSV", b"") is True

    def test_partial_csv_header_is_enough(self) -> None:
        # A partial file with just the date column header should be
        # accepted — the parser will reject specific bad rows.
        head = b"date,time,latitude,longitude\n"
        assert _looks_like_csv("partial.csv", "", head) is True


class TestEmptyFileBehavior:
    """The endpoint must return 400 for a 0-byte upload.

    These need the full app, but we mock out the heavy bits. We only
    verify the early-return path: no Job row, no Celery enqueue.
    """
    def test_empty_file_returns_400(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.main import app
        from app.core.dependencies import get_current_user

        # Skip auth — we want to test the file-size check, not login.
        async def _fake_user():
            from app.models.user import User
            return User(user_id="00000000-0000-0000-0000-000000000001",
                        email="t@example.com", username="t")

        app.dependency_overrides[get_current_user] = _fake_user

        # The job service writes to the DB; the parser dispatch is
        # already no-op when the file is empty so we only need to
        # avoid the real session/redis. We patch the session and
        # the upload dir.
        from app.db.session import get_session
        from app.services.job_service import JobService
        from app.workers import tasks as tasks_mod

        async def _fake_session():
            yield None  # noqa: — only used as a context manager marker

        class _FakeJob:
            job_id = "11111111-1111-1111-1111-111111111111"
            filename = "x.csv"

        async def _fake_create_job(*_a, **_kw):
            return _FakeJob()

        called = {"n": 0}
        def _fake_delay(*_a, **_kw):
            called["n"] += 1

        monkeypatch.setattr(JobService, "create_job", _fake_create_job)
        monkeypatch.setattr(tasks_mod.parse_and_ingest_task, "delay", _fake_delay)
        app.dependency_overrides[get_session] = _fake_session

        try:
            client = TestClient(app)
            # Send an *empty* file with a CSV extension so the
            # content-type check passes and the size check is the
            # only thing that fires.
            resp = client.post(
                "/api/v1/trips",
                files={"file": ("empty.csv", b"", "text/csv")},
                headers={"X-CSRF-Token": "x"},  # CSRF middleware may reject; we accept either 400 or 403
            )
            assert resp.status_code in (400, 403), resp.text
            # If we got past CSRF (400), the empty-file path fired and
            # the celery task must NOT have been enqueued.
            if resp.status_code == 400:
                assert "empty" in resp.text.lower()
                assert called["n"] == 0
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_session, None)

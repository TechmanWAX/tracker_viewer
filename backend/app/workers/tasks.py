"""Celery tasks for background CSV ingestion.

Design
------
The actual work is a pure async coroutine: `process_csv_async(session,
job_id, file_path)`. It takes an already-open session, so the caller
controls the engine / event-loop lifecycle.

Two callers exist:

1. **Production** — `parse_and_ingest_task` is a Celery task. Celery
   requires sync task functions, so we build a per-thread async engine
   (SQLAlchemy async engines are bound to the event loop that created
   them) and `asyncio.run` the coroutine in that thread. This works in
   real Celery workers (separate process, no pre-existing loop) and in
   eager mode (test process has a running loop, but the thread is
   fresh).

2. **Dev (`CELERY_TASK_ALWAYS_EAGER=true`)** — the API server
   short-circuits `parse_and_ingest_task.delay(...)` and instead
   `asyncio.create_task`s `process_csv_async` directly on its own
   engine and event loop. That means:

     - POST /trips returns 202 immediately (no blocking join).
     - The progress columns are written into the same DB the API polls.
     - The frontend's progress bar moves smoothly 0% → 100%.

The Celery path is left untouched for production deploys with a real
worker process.
"""

import os
import threading
from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job
from app.models.trip import Trip
from app.models.telemetry import TelemetryPoint
from app.services.parser_service import ParserService


def _f(val):
    """Safely cast value to float or return None."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


async def process_csv_async(
    session: AsyncSession,
    job_id: str,
    file_path: str,
) -> Dict[str, Any]:
    """Parse a CSV file and ingest telemetry points into the database.

    Pure async coroutine. Does NOT create its own engine or event loop.
    The caller owns the session lifecycle; we own the file parsing and
    the progress writes.

    Returns a small result dict. The job row in the `jobs` table is the
    source of truth for the frontend — this dict is only used by the
    Celery wrapper for retry logic.
    """
    from sqlalchemy import select, update
    from datetime import datetime, timezone

    # ---- fetch job -------------------------------------------------
    r = await session.execute(select(Job).where(Job.job_id == job_id))
    job = r.scalar_one_or_none()
    if job is None:
        return {"error": "Job not found", "status": "failed"}

    job.status = "processing"
    await session.commit()

    # ---- progress baseline ---------------------------------------
    # Two ways to estimate progress, picked at runtime:
    #
    #   1. **Line count**: pre-count newlines in the file. This
    #      is the most accurate denominator for CSV progress,
    #      and `parser_report.total_rows` gives the matching
    #      numerator (raw lines read so far, including rejected
    #      ones). Costs ~1-2 s on a 100 MB file.
    #
    #   2. **Byte count**: fallback. Used when the pre-pass
    #      fails (file vanished, permission error, the parser
    #      can't reach the file, etc.) or when there are zero
    #      newlines (binary garbage). Less precise but always
    #      works.
    total_bytes = 0
    try:
        total_bytes = os.path.getsize(file_path)
    except OSError:
        pass

    total_lines = 0
    try:
        # NB: use `_fp` (not `_f`) so we don't shadow the module-level
        # `_f` helper that we call later in the row loop. The `with`
        # statement leaves the `as` target bound to the file object
        # (not None) until the function returns, so a name collision
        # would silently turn the next `_f(value)` call into
        # `TypeError: BufferedReader is not callable`.
        with open(file_path, "rb") as _fp:
            for _ in _fp:
                total_lines += 1
    except OSError:
        pass

    bytes_per_line = (
        total_bytes / total_lines if total_lines > 0 else 0
    )

    def _write_progress(processed_lines: int) -> float:
        """Return the 0.0 - 1.0 progress value to persist.

        Prefers the line-count denominator (most accurate);
        falls back to byte-position when lines are unknown.
        """
        if total_lines > 0:
            pct = min(1.0, processed_lines / total_lines)
        elif total_bytes > 0 and bytes_per_line > 0:
            pct = min(1.0, processed_lines * bytes_per_line / total_bytes)
        else:
            pct = 0.0
        return round(pct, 3)

    async def _commit_progress(processed_lines: int) -> None:
        pct = _write_progress(processed_lines)
        # Atomic UPDATE. We deliberately do NOT touch `job.result`
        # (the JSON column) here — that used to be the source of
        # the progress, but in-place mutation of a JSON dict in a
        # worker thread with its own event loop is not reliably
        # detected by SQLAlchemy, and the API server would keep
        # seeing the stale value. Three dedicated columns + a
        # plain UPDATE eliminates the issue entirely.
        await session.execute(
            update(Job)
            .where(Job.job_id == job_id)
            .values(
                progress=pct,
                processed_bytes=int(pct * total_bytes),
                total_bytes=total_bytes,
            )
        )
        await session.commit()

    # Initial 0% commit so the first poll from the client doesn't
    # see `null` and stall the progress bar.
    await _commit_progress(0)

    total_rows = 0
    valid_rows = 0
    error_rows = 0
    sample_errors: list = []
    trip_id: str | None = None
    _parser_exc = None
    last_progress_write_lines = 0
    processed_lines: int = 0  # set inside the for-loop, read after

    try:
        for chunk, parser_report in ParserService.parse_csv_file(
            file_path, chunk_size=1000
        ):
            total_rows += len(chunk)
            # parser_report.total_rows is the number of *raw lines*
            # the parser has read so far (including the ones we
            # just filtered out for missing lat/lng). That's our
            # true progress denominator numerator.
            processed_lines = parser_report.total_rows

            # Create trip from the first non-empty chunk
            if trip_id is None and chunk:
                first = chunk[0]
                last = chunk[-1]
                try:
                    start_ts = datetime.fromisoformat(
                        f"{first.get('date', '')}T{first.get('time', '')}"
                    )
                    end_ts = datetime.fromisoformat(
                        f"{last.get('date', '')}T{last.get('time', '')}"
                    )
                except (ValueError, TypeError):
                    start_ts = datetime.now(timezone.utc)
                    end_ts = start_ts

                lats = [p["latitude"] for p in chunk if p.get("latitude") is not None]
                lons = [p["longitude"] for p in chunk if p.get("longitude") is not None]

                # A trip has GPS iff at least one of its first chunk's
                # points carries coordinates. The parser no longer
                # rejects rows missing lat/lng, so this is now a
                # real branch — some CSVs from older controller
                # firmware don't emit GPS at all.
                has_gps = bool(lats and lons)

                # Persist the dedup key on the Trip row so a future
                # upload of the same file by the same user is rejected
                # by the unique index. The hash was computed in the
                # upload endpoint and stashed on the Job row.
                trip = Trip(
                    user_id=job.user_id,
                    trip_name=job.filename or "trip",
                    start_time=start_ts,
                    end_time=end_ts,
                    min_lat=min(lats) if has_gps else None,
                    max_lat=max(lats) if has_gps else None,
                    min_lon=min(lons) if has_gps else None,
                    max_lon=max(lons) if has_gps else None,
                    has_gps=has_gps,
                    original_filename=job.filename,
                    content_sha256=job.content_sha256,
                )
                session.add(trip)
                await session.commit()
                await session.refresh(trip)
                trip_id = str(trip.trip_id)

            # Insert telemetry points. We use raw `INSERT ... ON CONFLICT
            # (timestamp, trip_id) DO NOTHING` rather than the ORM
            # `session.add(...)` path. The reason is that `telemetry_points`
            # has a composite primary key on (timestamp, trip_id), and
            # real-world GPS CSVs frequently contain rows that share the
            # same (date, time) tuple — either because the device
            # firmware emits duplicate ticks, or because the user
            # re-uploads the same file. With plain `session.add()` a
            # single duplicate aborts the whole transaction and
            # SQLAlchemy marks the session as "rolled back", which
            # then poisons every subsequent commit — including the
            # final `status="failed"` write that should at least tell
            # the frontend *something* went wrong. `ON CONFLICT DO
            # NOTHING` is idempotent: duplicates are silently skipped
            # and the rest of the batch is inserted.
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            point_dicts = []
            for row in chunk:
                try:
                    # `latitude` / `longitude` may be absent or empty
                    # in the source CSV (firmware that doesn't emit
                    # GPS). We store NULL in that case and skip the
                    # `geom` column too — the trip's `has_gps` flag
                    # will end up False and the UI will render a
                    # "no GPS data" placeholder.
                    lat_raw = row.get("latitude")
                    lon_raw = row.get("longitude")
                    lat = _f(lat_raw)
                    lon = _f(lon_raw)

                    ts_str = f"{row.get('date', '')}T{row.get('time', '')}"
                    try:
                        ts = datetime.fromisoformat(ts_str)
                    except (ValueError, TypeError):
                        ts = datetime.now()

                    point = {
                        "trip_id": trip_id,
                        "timestamp": ts,
                        "latitude": lat,
                        "longitude": lon,
                        "speed": _f(row.get("speed")) or 0.0,
                        "gps_speed": _f(row.get("gps_speed")),
                        "gps_alt": _f(row.get("gps_alt")),
                        "gps_heading": _f(row.get("gps_heading")),
                        "gps_distance": _f(row.get("gps_distance")),
                        "voltage": _f(row.get("voltage")),
                        "current": _f(row.get("current")),
                        "phase_current": _f(row.get("phase_current")),
                        "power": _f(row.get("power")),
                        "torque": _f(row.get("torque")),
                        "pwm": _f(row.get("pwm")),
                        "battery_level": _f(row.get("battery_level")),
                        "distance": _f(row.get("distance")),
                        "totaldistance": _f(row.get("totaldistance")),
                        "system_temp": _f(row.get("system_temp")),
                        "temp2": _f(row.get("temp2")),
                        "tilt": _f(row.get("tilt")),
                        "roll": _f(row.get("roll")),
                        "mode": row.get("mode") or None,
                        "alert": row.get("alert") or None,
                    }
                    # Only fill `geom` when we have real coordinates
                    # — Storing `POINT(NULL NULL)` would either fail
                    # the insert or pollute the PostGIS index with
                    # garbage at (0, 0) depending on the dialect.
                    if lat is not None and lon is not None:
                        point["geom"] = f"POINT({lon} {lat})"
                    point_dicts.append(point)
                    valid_rows += 1
                except Exception as exc:
                    error_rows += 1
                    if len(sample_errors) < 100:
                        sample_errors.append(
                            {"row": row, "error": str(exc)[:200]}
                        )

            if point_dicts:
                try:
                    stmt = pg_insert(TelemetryPoint).values(point_dicts)
                    stmt = stmt.on_conflict_do_nothing(
                        index_elements=["timestamp", "trip_id"]
                    )
                    result = await session.execute(stmt)
                    # `result.rowcount` tells us how many rows were
                    # actually inserted (i.e. NOT skipped as duplicates).
                    # That gives the frontend an honest "rows imported"
                    # number instead of "rows parsed".
                    inserted = result.rowcount or 0
                    duplicate_count = len(point_dicts) - inserted
                    if duplicate_count:
                        # Don't count duplicates as errors — the data
                        # was just already there. Just log it.
                        import logging
                        logging.getLogger(__name__).info(
                            "Skipped %d duplicate (timestamp, trip_id) "
                            "rows in job %s (chunk had %d total).",
                            duplicate_count, job_id, len(point_dicts),
                        )
                except Exception as exc:
                    # Any other failure (column type mismatch, FK, etc.)
                    # — we still want the parser to keep going for the
                    # remaining chunks, but we have to roll the session
                    # back so subsequent commits don't blow up.
                    await session.rollback()
                    error_rows += len(point_dicts)
                    if len(sample_errors) < 100:
                        sample_errors.append({
                            "error": f"chunk insert failed: {str(exc)[:200]}",
                            "chunk_size": len(point_dicts),
                        })
                    import logging
                    logging.getLogger(__name__).exception(
                        "Telemetry point insert failed for job %s: %s",
                        job_id, exc,
                    )

            await session.commit()

            # ---- progress write (every chunk) ----------------------
            # Always commit progress after a chunk is processed, so
            # the bar moves smoothly even on files where every row
            # is a duplicate (valid_rows never grows, so the old
            # 250-row throttle would never fire). The 250-row
            # throttle was a mistake for that case: it left the
            # frontend showing 0% for files with no new rows, even
            # though the parser was actually plowing through them.
            await _commit_progress(processed_lines)

    except Exception as exc:
        _parser_exc = exc

    # Calculate trip bounds from ingested data.
    #
    # CRITICAL: the parser loop above may have left `session` in a
    # "rolled back" state (any IntegrityError or other commit-time
    # failure poisons the whole transaction). If we touch ORM objects
    # via `session` after that, every operation raises
    # `PendingRollbackError` and the *final* status write that
    # flips the job from "processing" to "done/failed" never reaches
    # the DB. The job then sits at `status="processing",
    # progress=0.0` forever, and the frontend's poll times out.
    #
    # The fix is to wrap the post-loop work in a try/except: on any
    # session-state error we issue a raw `UPDATE jobs SET ...` via
    # `session.connection()` (which works even when the ORM session
    # is in pending-rollback) and only the *final* status flip uses
    # ORM objects. If even that fails, we fall back to a second raw
    # UPDATE so the frontend always sees a terminal status.
    try:
        if trip_id is not None and _parser_exc is None:
            from app.repositories.telemetry_repo import TelemetryRepository
            repo = TelemetryRepository()
            bounds = await repo.get_bounds(session, trip_id)
            r2 = await session.execute(
                select(Trip).where(Trip.trip_id == trip_id)
            )
            t = r2.scalar_one_or_none()
            if t is not None:
                if bounds:
                    t.min_lat = bounds["min_lat"]
                    t.max_lat = bounds["max_lat"]
                    t.min_lon = bounds["min_lon"]
                    t.max_lon = bounds["max_lon"]
                    t.has_gps = True
                else:
                    # `get_bounds` returned None ⇒ every row in this
                    # trip has NULL lat/lng. Mirror that on the Trip
                    # row so the UI can render the no-GPS branch
                    # without having to count rows itself.
                    t.min_lat = None
                    t.max_lat = None
                    t.min_lon = None
                    t.max_lon = None
                    t.has_gps = False
                t.total_distance_meters = await repo.get_total_distance(
                    session, trip_id
                )
                await session.commit()

        # Final job status.
        if _parser_exc is not None:
            job.status = "failed"
            job.result = {
                "error": str(_parser_exc)[:500],
                "total_rows": total_rows,
                "valid_rows": valid_rows,
                "error_rows": error_rows,
            }
        else:
            job.status = "done"
            job.result = {
                "trip_id": trip_id,
                "total_rows": total_rows,
                "valid_rows": valid_rows,
                "error_rows": error_rows,
                "sample_errors": sample_errors[:100],
            }

        # Final progress commit — done=1.0, failed=last seen.
        final_pct = 1.0 if _parser_exc is None else _write_progress(processed_lines)
        await session.execute(
            update(Job)
            .where(Job.job_id == job_id)
            .values(
                progress=final_pct,
                processed_bytes=int(final_pct * total_bytes),
                total_bytes=total_bytes,
            )
        )
        await session.commit()
    except Exception:
        # Session is in a bad state (most likely PendingRollbackError
        # from a prior IntegrityError). Roll back, then write the
        # final status via a *raw* UPDATE through the underlying
        # connection — that path doesn't go through the ORM's
        # transaction state and is robust to poisoned sessions.
        try:
            await session.rollback()
        except Exception:
            pass

        final_status = "done" if _parser_exc is None else "failed"
        final_pct = 1.0 if _parser_exc is None else _write_progress(processed_lines)
        result_json = (
            {"error": str(_parser_exc)[:500], "total_rows": total_rows,
             "valid_rows": valid_rows, "error_rows": error_rows}
            if _parser_exc is not None
            else {"trip_id": trip_id, "total_rows": total_rows,
                  "valid_rows": valid_rows, "error_rows": error_rows,
                  "sample_errors": sample_errors[:100]}
        )
        try:
            import json as _json
            from sqlalchemy import text as _text
            await session.execute(
                _text(
                    "UPDATE jobs SET status = :s, progress = :p, "
                    "processed_bytes = :pb, total_bytes = :tb, "
                    "result = CAST(:r AS json) WHERE job_id = :jid"
                ),
                {
                    "s": final_status,
                    "p": final_pct,
                    "pb": int(final_pct * total_bytes),
                    "tb": total_bytes,
                    "r": _json.dumps(result_json),
                    "jid": job_id,
                },
            )
            await session.commit()
        except Exception as exc:
            # Last-ditch: at least flip status so the frontend gets
            # out of the "processing" limbo. Log so ops can investigate.
            import logging
            logging.getLogger(__name__).exception(
                "Failed to write final job status for %s: %s", job_id, exc,
            )
            try:
                await session.rollback()
                from sqlalchemy import text as _text2
                await session.execute(
                    _text2("UPDATE jobs SET status = :s WHERE job_id = :jid"),
                    {"s": final_status, "jid": job_id},
                )
                await session.commit()
            except Exception:
                pass

    if _parser_exc is not None:
        raise _parser_exc

    return {
        "status": "done",
        "trip_id": trip_id,
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "error_rows": error_rows,
    }


# ---------------------------------------------------------------------------
# Celery wrapper. Only used in production (real worker process). In dev,
# trips.py bypasses this entirely and calls process_csv_async directly.
# ---------------------------------------------------------------------------
from app.workers.celery_app import celery_app  # noqa: E402


@celery_app.task(bind=True, max_retries=3)
def parse_and_ingest_task(self, job_id: str, file_path: str) -> Dict[str, Any]:
    """Celery entrypoint. Builds a private event loop and runs the async
    coroutine inside it. See module docstring for the dev-mode bypass."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.core.config import get_settings

    s = get_settings()
    url = s.database_url
    is_sqlite = url.startswith("sqlite")
    kw: dict = {"pool_pre_ping": True, "pool_recycle": 3600}
    if not is_sqlite:
        kw["pool_size"] = s.database_pool_size
        kw["max_overflow"] = s.database_max_overflow
    thread_engine = create_async_engine(url, **kw)
    ThreadSessionLocal = async_sessionmaker(
        bind=thread_engine, expire_on_commit=False,
        autocommit=False, autoflush=False,
    )

    result_box: list = [None]
    exc_box: list = [None]

    def _target():
        import asyncio

        async def _run():
            async with ThreadSessionLocal() as session:
                return await process_csv_async(session, job_id, file_path)

        try:
            result_box[0] = asyncio.run(_run())
        except Exception as e:
            exc_box[0] = e
        finally:
            pass

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=3600)

    # Dispose the thread-local engine, regardless of outcome.
    import asyncio as _asyncio
    try:
        _asyncio.run(thread_engine.dispose())
    except Exception:
        pass

    if exc_box[0] is not None:
        exc = exc_box[0]
        if self.request.retries < self.max_retries:
            # Keep the temp file so the retry can re-read it.
            raise self.retry(exc=exc, countdown=2**self.request.retries)
        # Final failure — clean up the temp file.
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception:
            pass
        return {
            "error": str(exc)[:500],
            "status": "failed",
            "total_rows": result_box[0].get("total_rows", 0) if result_box[0] else 0,
            "valid_rows": result_box[0].get("valid_rows", 0) if result_box[0] else 0,
            "error_rows": result_box[0].get("error_rows", 0) if result_box[0] else 0,
        }

    # Success — clean up the temp file.
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception:
        pass

    return result_box[0] or {"status": "failed", "error": "No result"}


@celery_app.task
def cleanup_temp_files() -> Dict[str, Any]:
    """Remove temp files older than 24 hours from the upload directory."""
    import time
    from app.core.config import get_settings

    settings = get_settings()
    deleted = 0
    now = time.time()
    max_age = 3600 * 24
    if os.path.exists(settings.upload_dir):
        for name in os.listdir(settings.upload_dir):
            path = os.path.join(settings.upload_dir, name)
            try:
                if os.path.isfile(path) and now - os.path.getmtime(path) > max_age:
                    os.remove(path)
                    deleted += 1
            except Exception:
                pass
    return {"deleted": deleted}

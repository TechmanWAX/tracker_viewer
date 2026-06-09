"""Trip endpoints."""

import asyncio
import hashlib
import os
import shutil
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_current_user
from app.db.session import AsyncSessionLocal, get_session
from app.models.user import User
from app.schemas.trip import TripUpdate, Trip, TripList
from app.services.trip_service import TripService
from app.services.job_service import JobService

router = APIRouter()

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB
_HASH_CHUNK = 1024 * 1024  # 1 MB, matches the streaming chunk size

# Content-Type values browsers / OSes may send for a .csv upload. The
# original implementation only accepted the two most common ones, which
# made uploads from Chromium on Linux (which sends "application/csv")
# and from the "All files" file picker (which sends
# "application/octet-stream") fail with a confusing 415. The integration
# spec defines the wire contract as text/csv only, so we treat sniffing
# as authoritative and fall back to: extension + a first-bytes scan
# looking for header-like text. See _looks_like_csv for the exact rules.
_CSV_CONTENT_TYPES = frozenset({
    "text/csv",
    "application/csv",
    "text/x-csv",
    "application/vnd.ms-excel",
    "text/plain",          # some Linux file managers + sniffers
    "application/octet-stream",  # generic "All files" fallback
    "binary/octet-stream",
})

# Tiny set of column names that the parser actually requires. If the
# first line of the file contains at least *one* of these, the file is
# almost certainly a CSV. We use this to recover when both content_type
# and extension lie (e.g. .txt file uploaded from a terminal).
_CSV_HINTS = (
    "latitude", "longitude", "lat,", "lon,", "date,", "time,",
    "gps_speed", "speed,", "voltage", "altitude",
)


def _looks_like_csv(filename: Optional[str], content_type: Optional[str], head: bytes) -> bool:
    """Best-effort CSV detector.

    Returns True if any of the following hold:

    1. Browser-sent `content_type` is in the allow-list.
    2. Filename ends in `.csv` or `.tsv` (the parser handles either via
       csv.Sniffer).
    3. First ~4 KB of the file, decoded leniently, contains at least one
       of the well-known GPS/CSV column names.
    """
    if content_type and content_type.lower() in _CSV_CONTENT_TYPES:
        return True
    if filename:
        ext = Path(filename).suffix.lower()
        if ext in (".csv", ".tsv", ".txt"):
            return True
    if head:
        try:
            text = head[:4096].decode("utf-8", errors="replace")
        except Exception:
            return False
        lower = text.lower()
        return any(hint in lower for hint in _CSV_HINTS)
    return False


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_trip(
    request: Request,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Upload a CSV file to create a new trip (async job).

    Validation order (cheapest first):

    1. **Content-type / extension / first-bytes sniff** → 415 if not CSV.
       A single `application/octet-stream` from a sloppy browser no
       longer kills the upload.
    2. **Stream to disk in chunks** (capped at MAX_FILE_SIZE). We never
       load the whole file into RAM, and we compute a SHA-256 of the
       bytes as they go through (cheap: ~200ms for 100MB).
    3. **Empty file** → 400 instead of silently enqueuing a job that
       will fail with a confusing "missing headers" error from Celery.
    4. **Duplicate check** → 409 if the same user has already uploaded
       a file with the same name and the same SHA-256. Different
       content (or different filename) is allowed.
    5. **Enqueue Celery** with the path on disk. The task computes
       total line count + bytes for the progress bar.
    """
    settings = get_settings()

    # 1) Sniff the head *before* writing anything. We need the first
    #    chunk on disk-or-in-memory either way, so read up to 4 KB.
    head = await file.read(4096)
    if not _looks_like_csv(file.filename, file.content_type, head):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                "Only CSV files are supported. The uploaded file did not "
                "look like a CSV (checked Content-Type, extension, and "
                "the first 4 KB of content)."
            ),
        )

    # 2) Stream the file to disk, byte-counting + SHA-256-hashing as
    #    we go. Stops as soon as we exceed MAX_FILE_SIZE so we never
    #    fill the disk on a malicious 5 GB upload.
    os.makedirs(settings.upload_dir, exist_ok=True)

    # Create the job up-front so we have a stable job_id for the
    # temp-file name and the response. The hash is set on the job
    # *after* we finish streaming, so for a moment the Job row exists
    # in "pending" state with content_sha256=NULL. This is fine
    # because the worker reads the column only when it actually runs
    # (which can only happen after we've committed the hash below).
    job = await JobService.create_job(
        session,
        user_id=str(user.user_id),
        filename=file.filename or "unknown.csv",
    )
    temp_path = os.path.join(settings.upload_dir, f"{job.job_id}.csv")

    bytes_written = 0
    hasher = hashlib.sha256()
    try:
        with open(temp_path, "wb") as out:
            # Flush the head we already read so nothing is lost. We
            # also feed it into the hasher.
            if head:
                out.write(head)
                hasher.update(head)
                bytes_written += len(head)
            while True:
                chunk = await file.read(_HASH_CHUNK)
                if not chunk:
                    break
                if bytes_written + len(chunk) > MAX_FILE_SIZE:
                    # Write the partial chunk up to the cap so the
                    # task sees a file that's exactly the limit, then
                    # 413.
                    remaining = MAX_FILE_SIZE - bytes_written
                    if remaining > 0:
                        out.write(chunk[:remaining])
                        hasher.update(chunk[:remaining])
                        bytes_written += remaining
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=(
                            f"File exceeds the {MAX_FILE_SIZE // (1024*1024)} MB limit."
                        ),
                    )
                out.write(chunk)
                hasher.update(chunk)
                bytes_written += len(chunk)
    except HTTPException:
        # Clean up the half-written file and re-raise.
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise

    # 3) Reject empty files early. The parser would fail anyway with a
    #    "no header" error after spinning up a Celery worker, but the
    #    400 here gives the user a clear, immediate message and avoids
    #    polluting the jobs table with zombie rows.
    if bytes_written == 0:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty (0 bytes).",
        )

    # Hash is finalized now. We do this *after* the file is on disk
    # and validated as non-empty so the dedup check has a real key.
    content_sha256 = hasher.hexdigest()

    # 4) Duplicate detection. The (user_id, original_filename,
    #    content_sha256) triple is unique across the trips table (see
    #    the unique index ix_trips_user_filename_hash). If a trip
    #    with the same key already exists for this user we reject
    #    the upload with 409. The user can delete the old trip from
    #    the trips page and retry.
    original_filename = file.filename or "unknown.csv"
    existing = await TripService.get_duplicate_trip(
        session,
        user_id=str(user.user_id),
        original_filename=original_filename,
        content_sha256=content_sha256,
    )
    if existing is not None:
        # Clean up: drop the just-written file, drop the pending Job
        # row we created above (so it doesn't show up in the jobs
        # list as a zombie). Use a fresh session because the request
        # session is about to be returned to the pool.
        try:
            os.remove(temp_path)
        except OSError:
            pass
        try:
            await session.delete(job)
            await session.commit()
        except Exception:
            try:
                await session.rollback()
            except Exception:
                pass

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"You've already uploaded '{original_filename}' with the same "
                f"content. The existing trip is {existing.trip_id}. "
                f"Delete it from the trips page if you want to re-upload."
            ),
        )

    # Persist the hash on the Job row so the worker can copy it to
    # the Trip it creates. Without this, the unique index would only
    # kick in on a *second* upload of the same file (we'd never have
    # a chance to write the dedup key for the first one).
    job.content_sha256 = content_sha256
    try:
        await session.commit()
    except Exception:
        # If we can't even record the hash we shouldn't proceed —
        # the file is already on disk, the job row exists, and we
        # just lost the dedup key. Clean up and 500.
        try:
            os.remove(temp_path)
        except OSError:
            pass
        try:
            await session.rollback()
        except Exception:
            pass
        raise

    # 5) Enqueue.
    #
    # In dev (`CELERY_TASK_ALWAYS_EAGER=true`) we bypass Celery
    # entirely and run the parser as a real asyncio task on the
    # API server's own event loop. POST returns 202 immediately
    # and the frontend's poll loop can see the progress columns
    # move in real time. The engine/loop are shared with the API,
    # which is safe — the task is bound to the same loop the
    # request handlers use, and SQLAlchemy writes are picked up
    # by the next poll.
    #
    # In production (real Celery worker, no eager mode) we keep
    # the standard dispatch path: the message goes to Redis and
    # a worker process picks it up.
    if settings.celery_task_always_eager:
        from app.workers.tasks import process_csv_async

        async def _kickoff() -> None:
            try:
                async with AsyncSessionLocal() as bg_session:
                    await process_csv_async(bg_session, job.job_id, temp_path)
            except Exception as exc:
                # Don't crash the request loop on a background
                # failure — the job row is already in place, and
                # the worker's final progress commit before the
                # exception already wrote `status="failed"` into
                # the row. The frontend will see it on the next
                # poll. We only log here for ops visibility.
                import logging
                logging.getLogger(__name__).exception(
                    "Background CSV ingest failed for job %s: %s",
                    job.job_id, exc,
                )

        asyncio.create_task(_kickoff())
    else:
        from app.workers.tasks import parse_and_ingest_task
        parse_and_ingest_task.delay(job.job_id, temp_path)

    return {
        "job_id": str(job.job_id),
        "jobId": str(job.job_id),
        "status": "accepted",
        "status_url": f"/jobs/{job.job_id}",
        "statusUrl": f"/jobs/{job.job_id}",
        "message": "Upload accepted. Processing in background.",
        "bytes": bytes_written,
        "content_sha256": content_sha256,
    }


@router.get("", response_model=TripList)
async def list_trips(
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    limit: int = 20,
    offset: int = 0,
):
    """List all trips for the current user."""
    trips, total = await TripService.get_trips(session, str(user.user_id), limit, offset)
    
    return {
        "trips": trips,
        "total": total,
        "page": offset // limit + 1,
        "per_page": limit,
    }


@router.get("/{trip_id}", response_model=Trip)
async def get_trip(
    trip_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get a specific trip by ID."""
    trip = await TripService.get_trip(session, trip_id, str(user.user_id))
    
    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip not found",
        )
    
    return trip


@router.put("/{trip_id}", response_model=Trip)
async def update_trip(
    trip_id: str,
    trip_data: TripUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Update a trip's metadata."""
    trip = await TripService.get_trip(session, trip_id, str(user.user_id))
    
    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip not found",
        )
    
    trip = await TripService.update_trip(session, trip, trip_data)
    return trip


@router.delete("/{trip_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trip(
    trip_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Delete a trip and all its telemetry points."""
    trip = await TripService.get_trip(session, trip_id, str(user.user_id))
    
    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip not found",
        )
    
    await TripService.delete_trip(session, trip)
    return None
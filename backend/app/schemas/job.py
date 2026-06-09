"""Job-related Pydantic schemas."""

from datetime import datetime
from typing import Optional, Dict, Any, List

from pydantic import BaseModel, Field


class JobStatus(str):
    """Enum for job statuses."""
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    FAILED = "failed"


class JobBase(BaseModel):
    """Base job schema."""
    job_id: str
    status: str
    created_at: datetime


class JobCreate(BaseModel):
    """Schema for job creation request."""
    filename: str
    user_id: str


class JobResult(BaseModel):
    """Schema for job result details (final state, written when done/failed)."""
    trip_id: Optional[str] = None
    total_rows: int = 0
    valid_rows: int = 0
    error_rows: int = 0
    sample_errors: Optional[List[Dict[str, Any]]] = None
    parsing_report: Optional[str] = None
    error: Optional[str] = None


class Job(JobBase):
    """Schema for job responses.

    The top-level `progress` / `processed_bytes` / `total_bytes` fields
    are sourced from dedicated columns on the `jobs` table and are
    updated in real time by the Celery worker. The nested `result`
    object only carries the *final* outcome (trip_id, totals, errors)
    and is populated when the worker flips the status to done/failed.
    """
    user_id: str
    filename: str
    result: Optional[JobResult] = None
    # Live progress — read by the frontend's poll loop to drive the
    # progress bar. Null while the job is still pending.
    progress: Optional[float] = None
    processed_bytes: Optional[int] = None
    total_bytes: Optional[int] = None

    model_config = {"from_attributes": True}


class JobUpdate(BaseModel):
    """Schema for job status updates."""
    status: str
    result: Optional[Dict[str, Any]] = None
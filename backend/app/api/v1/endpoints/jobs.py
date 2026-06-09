"""Job endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_session
from app.models.user import User
from app.schemas.job import Job
from app.services.job_service import JobService

router = APIRouter()


@router.get("/{job_id}", response_model=Job)
async def get_job_status(
    job_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Get the status of a background job.

    Live parse progress comes from the dedicated `progress`,
    `processed_bytes`, and `total_bytes` columns (not from
    `result.progress`, which is unreliable across the worker / API
    server boundary). The columns are written by the Celery worker
    via an atomic UPDATE.
    """
    job = await JobService.get_job(session, job_id, str(user.user_id))

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    return {
        "job_id": str(job.job_id),
        "user_id": str(job.user_id),
        "status": job.status,
        "filename": job.filename,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "result": job.result,
        # Top-level progress fields — these are the live values.
        "progress": job.progress,
        "processed_bytes": job.processed_bytes,
        "total_bytes": job.total_bytes,
    }
"""Job service - manages background task lifecycle."""

from typing import Optional, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.job import Job
from app.schemas.job import JobStatus


class JobService:
    """Service for job status management."""

    @staticmethod
    async def create_job(
        session: AsyncSession,
        user_id: str,
        filename: str,
    ) -> Job:
        """Create a new job record."""
        job = Job(
            user_id=user_id,
            filename=filename,
            status=JobStatus.PENDING,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job

    @staticmethod
    async def get_job(
        session: AsyncSession,
        job_id: str,
        user_id: str,
    ) -> Optional[Job]:
        """Get job by ID (user ownership check)."""
        result = await session.execute(
            select(Job).where(
                Job.job_id == job_id,
                Job.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_job_status(
        session: AsyncSession,
        job: Job,
        status: str,
        result_data: Optional[Dict[str, Any]] = None,
    ) -> Job:
        """Update job status and result."""
        job.status = status
        
        if result_data is not None:
            job.result = result_data
        
        await session.commit()
        await session.refresh(job)
        return job

    @staticmethod
    async def get_job_status(
        session: AsyncSession,
        job_id: str,
        user_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Get job status and result."""
        job = await JobService.get_job(session, job_id, user_id)
        
        if job is None:
            return None
        
        return {
            "job_id": job.job_id,
            "status": job.status,
            "filename": job.filename,
            "created_at": job.created_at,
            "result": job.result,
        }
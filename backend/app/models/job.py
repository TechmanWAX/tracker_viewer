"""Job model for tracking background tasks."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Column,
    String,
    DateTime,
    JSON,
    Text,
    Float,
    BigInteger,
)
from sqlalchemy.dialects.postgresql import CHAR

from app.db.base import Base
from app.models.user import GUID

__all__ = ["Job"]


class Job(Base):
    """Model for tracking background job status."""

    __tablename__ = "jobs"

    job_id = Column(
        GUID(),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    user_id = Column(
        GUID(),
        nullable=False,
        index=True,
    )
    filename = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    result = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    # Live parsing progress, 0.0 - 1.0. Written by the Celery worker
    # via an atomic UPDATE so the API server can poll without race
    # conditions. Nullable while the job is still pending.
    progress = Column(Float, nullable=True)
    processed_bytes = Column(BigInteger, nullable=True)
    total_bytes = Column(BigInteger, nullable=True)
    # SHA-256 of the uploaded file (hex, 64 chars). Computed in the
    # upload endpoint while streaming the file to disk, written here
    # so the worker can persist it on the resulting Trip row. This is
    # also the key piece of data that makes the dedup check work
    # after a job completes — the constraint is on `trips`, but the
    # worker needs the value at insert time and we don't want to
    # re-hash the file from inside the worker.
    content_sha256 = Column(CHAR(64), nullable=True)

    def __repr__(self):
        return f"<Job {self.job_id}: {self.status}>"

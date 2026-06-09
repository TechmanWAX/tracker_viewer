"""Celery application configuration."""

import os

from celery import Celery
from celery.schedules import crontab

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "gps_tracker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

# In test/dev environments, run tasks synchronously in-process so we
# don't need a live Redis broker. Production sets BROKER_URL=redis://.
_eager = (
    os.environ.get("CELERY_TASK_ALWAYS_EAGER", "").lower() == "true"
    or str(get_settings().celery_task_always_eager).lower() == "true"
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_always_eager=_eager,
)

# Periodic tasks (beat schedule)
celery_app.conf.beat_schedule = {
    # Cleanup old temporary files
    "cleanup-temp-files": {
        "task": "app.workers.tasks.cleanup_temp_files",
        "schedule": crontab(hour=0, minute=0),  # Daily at midnight
    },
}
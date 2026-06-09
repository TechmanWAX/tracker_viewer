"""Trip model - imported from db-implementer."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    String,
    DateTime,
    Float,
    Index,
)
from sqlalchemy.dialects.postgresql import CHAR

from app.db.base import Base
from app.models.user import GUID

__all__ = ["Trip"]


class Trip(Base):
    """Trip metadata model."""

    __tablename__ = "trips"

    trip_id = Column(
        GUID(),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    user_id = Column(
        GUID(),
        nullable=False,
        index=True,
    )
    trip_name = Column(String(255), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    # Bounding box columns are nullable: trips ingested from CSV
    # files that don't include GPS coordinates have no bbox. The
    # UI uses `has_gps` to decide whether to render a map or a
    # "No GPS data" placeholder.
    min_lat = Column(Float, nullable=True)
    max_lat = Column(Float, nullable=True)
    min_lon = Column(Float, nullable=True)
    max_lon = Column(Float, nullable=True)
    total_distance_meters = Column(Float, nullable=True)
    # True iff at least one telemetry point in this trip has both
    # a non-NULL latitude and a non-NULL longitude. Computed at
    # upload time by the worker; never changes after the trip
    # is created (re-uploads always go through dedup).
    has_gps = Column(
        Boolean,
        nullable=False,
        server_default="true",
    )
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )
    # Upload-time metadata for duplicate detection.
    #
    # `original_filename` is the file name the user actually uploaded
    # (e.g. "2024-08-15_trip.csv"). It's distinct from `trip_name`
    # which is a human-friendly label the user can edit later.
    #
    # `content_sha256` is the hex SHA-256 of the file *bytes* —
    # computed during the streaming upload so we never have to re-read
    # the file. A CHAR(64) (PostgreSQL-only) is used because hex
    # digests are always exactly 64 chars; on SQLite the dialect
    # falls back to VARCHAR via the String fallback below.
    original_filename = Column(String(512), nullable=True)
    content_sha256 = Column(CHAR(64), nullable=True)

    # The duplicate-detection index: any user can have many trips
    # but may not have two with the same (filename, hash) pair.
    # Different filename or different content = allowed (it's
    # a genuinely different upload). The index also speeds up the
    # dedup check on the upload endpoint.
    __table_args__ = (
        Index(
            "ix_trips_user_filename_hash",
            "user_id",
            "original_filename",
            "content_sha256",
            unique=True,
        ),
    )

    def __repr__(self):
        return f"<Trip {self.trip_name}>"

"""Trip service."""

from typing import List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.trip import Trip
from app.models.telemetry import TelemetryPoint
from app.schemas.trip import TripCreate, TripUpdate


class TripService:
    """Service for trip management."""

    @staticmethod
    async def create_trip(
        session: AsyncSession,
        trip_data: TripCreate,
        user_id: str,
    ) -> Trip:
        """Create a new trip."""
        trip = Trip(
            user_id=user_id,
            trip_name=trip_data.trip_name,
        )
        session.add(trip)
        await session.commit()
        await session.refresh(trip)
        return trip

    @staticmethod
    async def get_duplicate_trip(
        session: AsyncSession,
        user_id: str,
        original_filename: Optional[str],
        content_sha256: Optional[str],
    ) -> Optional[Trip]:
        """Return the user's existing trip for this exact (filename, hash)
        pair, or None.

        Used by the upload endpoint to short-circuit re-uploads. The
        check is scoped to the current user — different users may
        legitimately upload files with the same name and content.

        Both arguments can be None (e.g. for trips created before the
        dedup columns existed). In that case we always return None
        because the unique index ignores NULL pairs and we don't
        want to suddenly reject every legacy row.
        """
        if not original_filename or not content_sha256:
            return None
        result = await session.execute(
            select(Trip).where(
                Trip.user_id == user_id,
                Trip.original_filename == original_filename,
                Trip.content_sha256 == content_sha256,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_trip(
        session: AsyncSession,
        trip_id: str,
        user_id: str,
    ) -> Optional[Trip]:
        """Get a trip by ID (user ownership check)."""
        result = await session.execute(
            select(Trip).where(
                Trip.trip_id == trip_id,
                Trip.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_trips(
        session: AsyncSession,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[List[Trip], int]:
        """Get list of trips for a user."""
        # Get total count
        count_result = await session.execute(
            select(func.count()).select_from(Trip).where(Trip.user_id == user_id)
        )
        total = count_result.scalar_one_or_none() or 0

        # Get trips
        result = await session.execute(
            select(Trip)
            .where(Trip.user_id == user_id)
            .order_by(Trip.start_time.desc())
            .offset(offset)
            .limit(limit)
        )
        trips = result.scalars().all()
        return trips, total

    @staticmethod
    async def update_trip(
        session: AsyncSession,
        trip: Trip,
        trip_data: TripUpdate,
    ) -> Trip:
        """Update trip information."""
        if trip_data.trip_name is not None:
            trip.trip_name = trip_data.trip_name

        await session.commit()
        await session.refresh(trip)
        return trip

    @staticmethod
    async def delete_trip(
        session: AsyncSession,
        trip: Trip,
    ) -> None:
        """Delete a trip."""
        await session.delete(trip)
        await session.commit()

    @staticmethod
    async def calculate_bounds(
        session: AsyncSession,
        trip_id: str,
    ) -> dict:
        """Calculate bounding box and total distance for a trip.

        Uses PostGIS ST_Y/ST_X on PostgreSQL, plain lat/lng columns elsewhere.

        For a trip without GPS data (every row has NULL lat/lng) the
        bbox fields come back as `None` instead of the previous
        placeholder `(0, 0, 0, 0)`. A `(0, 0)` box used to silently
        break the auto-fit logic on the frontend (it would zoom to
        "Null Island" in the Atlantic).

        `total_distance_meters` is the per-trip odometer delta
        (MAX - MIN of the `distance` column) — the column is a
        monotonically-increasing running total, not a per-tick
        increment, so SUM() would double-count. See
        `TelemetryRepository.get_total_distance` for the same
        logic in a reusable shape.
        """
        if session.bind.dialect.name == "postgresql":
            result = await session.execute(
                select(
                    func.min(func.ST_Y(TelemetryPoint.geom)).label("min_lat"),
                    func.max(func.ST_Y(TelemetryPoint.geom)).label("max_lat"),
                    func.min(func.ST_X(TelemetryPoint.geom)).label("min_lon"),
                    func.max(func.ST_X(TelemetryPoint.geom)).label("max_lon"),
                    func.max(TelemetryPoint.distance).label("max_d"),
                    func.min(TelemetryPoint.distance).label("min_d"),
                ).where(TelemetryPoint.trip_id == trip_id)
            )
        else:
            result = await session.execute(
                select(
                    func.min(TelemetryPoint.latitude).label("min_lat"),
                    func.max(TelemetryPoint.latitude).label("max_lat"),
                    func.min(TelemetryPoint.longitude).label("min_lon"),
                    func.max(TelemetryPoint.longitude).label("max_lon"),
                    func.max(TelemetryPoint.distance).label("max_d"),
                    func.min(TelemetryPoint.distance).label("min_d"),
                ).where(TelemetryPoint.trip_id == trip_id)
            )

        row = result.one_or_none()
        total_distance = None
        if row is not None and row.max_d is not None and row.min_d is not None:
            total_distance = row.max_d - row.min_d

        if row is None or row.min_lat is None:
            # No GPS data — return None for the bbox fields so the
            # UI can render a "no GPS data" placeholder instead of
            # auto-fitting to a (0, 0) rectangle.
            return {
                "min_lat": None,
                "max_lat": None,
                "min_lon": None,
                "max_lon": None,
                "total_distance_meters": total_distance,
            }

        return {
            "min_lat": row.min_lat,
            "max_lat": row.max_lat,
            "min_lon": row.min_lon,
            "max_lon": row.max_lon,
            "total_distance_meters": total_distance,
        }
"""Telemetry repository - dialect-aware (PostGIS / SQLite lat/lng)."""

from datetime import datetime
from typing import Optional, List, Dict, Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from app.models.telemetry import TelemetryPoint
from app.repositories.base_repo import BaseRepository


def _is_postgres(session: AsyncSession) -> bool:
    """Return True if the underlying dialect is PostgreSQL."""
    return session.bind.dialect.name == "postgresql"


class TelemetryRepository(BaseRepository[TelemetryPoint]):
    """Repository for telemetry database operations."""

    def __init__(self):
        super().__init__(TelemetryPoint)

    async def bulk_insert(
        self,
        session: AsyncSession,
        points: List[Dict[str, Any]],
    ) -> int:
        if not points:
            return 0

        instances = [TelemetryPoint(**point) for point in points]
        session.add_all(instances)
        await session.commit()
        return len(instances)

    async def get_points_by_trip(
        self,
        session: AsyncSession,
        trip_id: str,
        limit: int = 1000,
        offset: int = 0,
    ) -> List[TelemetryPoint]:
        result = await session.execute(
            select(TelemetryPoint)
            .where(TelemetryPoint.trip_id == trip_id)
            .order_by(TelemetryPoint.timestamp.asc())
            .offset(offset)
            .limit(limit)
        )
        return result.scalars().all()

    async def get_points_in_bbox(
        self,
        session: AsyncSession,
        trip_id: str,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        limit: int = 1000,
    ) -> List[TelemetryPoint]:
        # Filter on the float lat/lon columns.  A bounding box query on
        # points is mathematically equivalent to ST_Intersects(envelope, pt)
        # since every point's "bbox" is the point itself.  This avoids
        # constructing an envelope polygon (which can't be ST_Intersected
        # against a Point column without a cast).
        result = await session.execute(
            select(TelemetryPoint)
            .where(
                TelemetryPoint.trip_id == trip_id,
                TelemetryPoint.longitude >= min_lon,
                TelemetryPoint.latitude >= min_lat,
                TelemetryPoint.longitude <= max_lon,
                TelemetryPoint.latitude <= max_lat,
            )
            .order_by(TelemetryPoint.timestamp.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_points_by_time_range(
        self,
        session: AsyncSession,
        trip_id: str,
        from_ts: datetime,
        to_ts: datetime,
        limit: int = 1000,
    ) -> List[TelemetryPoint]:
        result = await session.execute(
            select(TelemetryPoint)
            .where(
                TelemetryPoint.trip_id == trip_id,
                TelemetryPoint.timestamp >= from_ts,
                TelemetryPoint.timestamp < to_ts,
            )
            .order_by(TelemetryPoint.timestamp.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_bounds(
        self,
        session: AsyncSession,
        trip_id: str,
    ) -> Optional[Dict[str, float]]:
        if _is_postgres(session):
            # `geom` is a GEOGRAPHY column, but PostGIS only exposes
            # ST_X/ST_Y for the GEOMETRY type. Casting to geometry
            # via `::geometry` is the canonical way to get the
            # coordinate accessors on a geography column. For WGS84
            # points (the only thing we ever store here) the cast
            # is a no-op semantically — geography already stores
            # lon/lat the same way as geometry(Point, 4326).
            result = await session.execute(
                text(
                    """
                    SELECT
                        MIN(ST_Y(geom::geometry)) AS min_lat,
                        MAX(ST_Y(geom::geometry)) AS max_lat,
                        MIN(ST_X(geom::geometry)) AS min_lon,
                        MAX(ST_X(geom::geometry)) AS max_lon
                    FROM telemetry_points
                    WHERE trip_id = :trip_id
                    """
                ),
                {"trip_id": trip_id},
            )
        else:
            result = await session.execute(
                select(
                    func.min(TelemetryPoint.latitude).label("min_lat"),
                    func.max(TelemetryPoint.latitude).label("max_lat"),
                    func.min(TelemetryPoint.longitude).label("min_lon"),
                    func.max(TelemetryPoint.longitude).label("max_lon"),
                ).where(TelemetryPoint.trip_id == trip_id)
            )

        row = result.one_or_none()
        if row is None or row.min_lat is None:
            return None

        return {
            "min_lat": row.min_lat,
            "max_lat": row.max_lat,
            "min_lon": row.min_lon,
            "max_lon": row.max_lon,
        }

    async def get_total_distance(
        self,
        session: AsyncSession,
        trip_id: str,
    ) -> Optional[float]:
        """Distance traveled during this trip, in meters.

        The `distance` column on telemetry_points is the device's
        running trip odometer — it starts at some non-zero value
        when the trip begins and increments monotonically. So the
        trip distance is `MAX - MIN`, not `SUM` (which would
        double-count every prior reading and produce absurd
        numbers like 767 km for a 4-minute trip). If the column
        is entirely NULL for the trip (older firmware, missing
        header) we return None.
        """
        result = await session.execute(
            select(
                func.max(TelemetryPoint.distance).label("max_d"),
                func.min(TelemetryPoint.distance).label("min_d"),
            ).where(TelemetryPoint.trip_id == trip_id)
        )
        row = result.one_or_none()
        if row is None or row.max_d is None or row.min_d is None:
            return None
        return row.max_d - row.min_d

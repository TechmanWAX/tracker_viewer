"""Trip repository."""

from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.trip import Trip
from app.repositories.base_repo import BaseRepository


class TripRepository(BaseRepository[Trip]):
    """Repository for trip database operations."""

    def __init__(self):
        super().__init__(Trip)

    async def get_by_user(
        self,
        session: AsyncSession,
        user_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Trip]:
        """Get trips for a user."""
        result = await session.execute(
            select(Trip)
            .where(Trip.user_id == user_id)
            .order_by(Trip.start_time.desc())
            .offset(offset)
            .limit(limit)
        )
        return result.all()

    async def get_total_count(
        self,
        session: AsyncSession,
        user_id: str,
    ) -> int:
        """Get total count of trips for a user."""
        result = await session.execute(
            select(func.count()).select_from(Trip).where(Trip.user_id == user_id)
        )
        return result.scalar_one_or_none() or 0

    async def get_by_id_and_user(
        self,
        session: AsyncSession,
        trip_id: str,
        user_id: str,
    ) -> Optional[Trip]:
        """Get trip by ID with user ownership check."""
        result = await session.execute(
            select(Trip).where(
                Trip.trip_id == trip_id,
                Trip.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()
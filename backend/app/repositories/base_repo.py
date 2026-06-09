"""Base repository class."""

from typing import Generic, List, Optional, TypeVar, Type
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import AsyncResult

T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Base repository with common CRUD operations."""

    def __init__(self, model: Type[T]):
        self.model = model

    async def get_by_id(
        self,
        session: AsyncSession,
        id_value: str,
    ) -> Optional[T]:
        """Get a single record by ID."""
        return await session.get(self.model, id_value)

    async def get_all(
        self,
        session: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> List[T]:
        """Get all records with pagination."""
        result: AsyncResult = await session.execute(
            select(self.model).offset(offset).limit(limit)
        )
        return result.all()

    async def create(
        self,
        session: AsyncSession,
        instance: T,
    ) -> T:
        """Create a new record."""
        session.add(instance)
        await session.commit()
        await session.refresh(instance)
        return instance

    async def update(
        self,
        session: AsyncSession,
        instance: T,
    ) -> T:
        """Update an existing record."""
        await session.commit()
        await session.refresh(instance)
        return instance

    async def delete(
        self,
        session: AsyncSession,
        instance: T,
    ) -> None:
        """Delete a record."""
        await session.delete(instance)
        await session.commit()
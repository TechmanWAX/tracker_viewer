"""Database session management for async SQLAlchemy."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings

_settings = get_settings()
_url = _settings.database_url
_is_sqlite = _url.startswith("sqlite")

# Create async engine.  aiosqlite does not accept pool_size/max_overflow,
# so those kwargs are passed only for non-SQLite dialects (e.g. asyncpg).
_engine_kwargs: dict = {
    "pool_pre_ping": True,
    "pool_recycle": 3600,
}
if not _is_sqlite:
    _engine_kwargs["pool_size"] = _settings.database_pool_size
    _engine_kwargs["max_overflow"] = _settings.database_max_overflow

engine: AsyncEngine = create_async_engine(_url, **_engine_kwargs)

# Create session factory
AsyncSessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session per request."""
    session: AsyncSession = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()
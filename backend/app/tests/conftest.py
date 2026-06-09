"""Test configuration and fixtures."""

import asyncio
import os
import tempfile
from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.core.config import get_settings
from app.db.session import engine, get_session
from app.main import app

# Test database URL
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5432/test_gps_tracker"
)

# Create test engine
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for tests."""
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_db():
    """Create test database and tables."""
    from app.db.base import Base
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session(test_db) -> AsyncGenerator[AsyncSession, None]:
    """Get database session for tests."""
    AsyncSessionLocal = sessionmaker(
        bind=test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    
    session = AsyncSessionLocal()
    try:
        yield session
    finally:
        await session.close()


@pytest.fixture
def client(db_session) -> TestClient:
    """Get test client."""
    def override_get_session():
        return db_session
    
    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def temp_csv_file():
    """Create a temporary CSV file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
        f.write("""date,time,latitude,longitude,gps_speed,gps_alt,gps_heading,gps_distance,speed,voltage,phase_current,current,power,torque,pwm,battery_level,distance,totaldistance,system_temp,temp2,tilt,roll,mode,alert
2023-01-01,12:00:00,45.523,-122.676,10.5,50.0,180.0,0.1,10.5,48.0,10.0,10.0,500,1.2,90,85,1.0,1.0,30.0,31.0,0.1,0.1,1,0
2023-01-01,12:00:01,45.524,-122.677,11.2,50.0,180.0,0.2,11.2,48.0,10.5,10.5,510,1.3,91,84,1.1,1.1,30.1,31.1,0.2,0.2,1,0
""")
        temp_path = f.name
    
    yield temp_path
    
    os.unlink(temp_path)
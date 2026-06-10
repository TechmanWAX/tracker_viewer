"""Public (no-auth) trip endpoints — shared trip viewing."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.models.trip import Trip
from app.models.telemetry import TelemetryPoint
from app.schemas.trip import Trip as TripSchema
from app.schemas.telemetry import TelemetryPoint as TelemetryPointSchema, TelemetryPointList
from app.repositories.telemetry_repo import TelemetryRepository

router = APIRouter(prefix="/public")


@router.get("/trips/{token}", response_model=TripSchema)
async def get_shared_trip(
    token: str,
    session: AsyncSession = Depends(get_session),
):
    """Get trip metadata by share token. No auth required."""
    r = await session.execute(
        select(Trip).where(Trip.share_token == token, Trip.is_shared == True)
    )
    trip = r.scalar_one_or_none()
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    return TripSchema.model_validate(trip)


@router.get("/trips/{token}/points", response_model=TelemetryPointList)
async def get_shared_trip_points(
    token: str,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=1000, ge=1, le=50000),
    offset: int = Query(default=0, ge=0),
):
    """Get telemetry points for a shared trip. No auth required."""
    r = await session.execute(
        select(Trip.trip_id).where(Trip.share_token == token, Trip.is_shared == True)
    )
    trip_id = r.scalar_one_or_none()
    if trip_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")

    repo = TelemetryRepository()
    points = await repo.get_points_by_trip(session, trip_id, limit, offset)

    total_row = await session.execute(
        select(func.count(TelemetryPoint.timestamp)).where(TelemetryPoint.trip_id == trip_id)
    )
    total_count = total_row.scalar() or 0

    return {
        "trip_id": trip_id,
        "points": [TelemetryPointSchema.model_validate(p) for p in points],
        "total": total_count,
    }


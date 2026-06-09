"""Telemetry endpoints."""

from typing import List, Optional

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.db.session import get_session
from app.models.user import User
from app.schemas.telemetry import (
    TelemetryPointList,
)
from app.services.trip_service import TripService
from app.repositories.telemetry_repo import TelemetryRepository

router = APIRouter()

# The map dashboard needs up to 50k points for large trips. The
# RDP-simplification in MapView culls the polyline to
# RDP_HARD_CAP (5000), so the final DOM node count stays
# bounded. Only recharts charts also see the full dataset,
# but they decimate in `toChartData` > 10k points.
MAX_LIMIT = 50000


@router.get("/{trip_id}/points", response_model=TelemetryPointList)
async def get_trip_points(
    trip_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    bbox: Optional[str] = Query(
        None,
        description="Bounding box: minLon,minLat,maxLon,maxLat"
    ),
    from_ts: Optional[str] = Query(
        None,
        description="Start timestamp (ISO format)"
    ),
    to_ts: Optional[str] = Query(
        None,
        description="End timestamp (ISO format)"
    ),
    limit: int = Query(default=1000, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
):
    """Get telemetry points for a trip with optional filtering."""
    # Check trip ownership
    trip = await TripService.get_trip(session, trip_id, str(user.user_id))
    
    if trip is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Trip not found",
        )
    
    repo = TelemetryRepository()
    
    # Parse query parameters
    from datetime import datetime
    from_ts_dt = None
    to_ts_dt = None
    
    if from_ts:
        try:
            from_ts_dt = datetime.fromisoformat(from_ts.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid from_ts format. Use ISO 8601 format.",
            )
    
    if to_ts:
        try:
            to_ts_dt = datetime.fromisoformat(to_ts.replace("Z", "+00:00"))
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid to_ts format. Use ISO 8601 format.",
            )
    
    # Parse bounding box
    if bbox:
        try:
            parts = bbox.split(",")
            if len(parts) != 4:
                raise ValueError("bbox must have 4 values")
            min_lon, min_lat, max_lon, max_lat = map(float, parts)
            
            points = await repo.get_points_in_bbox(
                session, trip_id, min_lon, min_lat, max_lon, max_lat, limit
            )
        except ValueError as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid bbox format: {str(e)}",
            )
    elif from_ts_dt or to_ts_dt:
        points = await repo.get_points_by_time_range(
            session, trip_id, from_ts_dt or trip.start_time,
            to_ts_dt or trip.end_time, limit
        )
    else:
        points = await repo.get_points_by_trip(session, trip_id, limit, offset)
    
    # Convert to schema. `total` is the trip-wide count (needed by
    # the UI when `limit` truncates the result — e.g. the map
    # fetches 50k of a 100k-point trip). This is a single cheap
    # COUNT on the indexed (trip_id, timestamp) PK, not a full
    # table scan.
    from sqlalchemy import func as _func
    from app.models.telemetry import TelemetryPoint as _TP
    total_row = await session.execute(
        select(_func.count(_TP.timestamp)).where(_TP.trip_id == trip_id)
    )
    total_count = total_row.scalar() or 0

    from app.schemas.telemetry import TelemetryPoint as TelemetryPointSchema
    return {
        "trip_id": trip_id,
        "points": [TelemetryPointSchema.model_validate(p) for p in points],
        "total": total_count,
    }
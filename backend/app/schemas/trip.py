"""Trip-related Pydantic schemas."""

from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel, Field


class TripBase(BaseModel):
    """Base trip schema."""
    trip_name: str = Field(..., min_length=1, max_length=255)


class TripCreate(TripBase):
    """Schema for trip creation (upload)."""
    pass


class TripUpdate(BaseModel):
    """Schema for trip updates."""
    trip_name: Optional[str] = Field(None, min_length=1, max_length=255)


class Trip(TripBase):
    """Schema for trip responses."""
    trip_id: str
    user_id: str
    start_time: datetime
    end_time: datetime
    # Bounding box is None for trips that have no GPS data.
    min_lat: Optional[float] = None
    max_lat: Optional[float] = None
    min_lon: Optional[float] = None
    max_lon: Optional[float] = None
    total_distance_meters: Optional[float] = None
    # True iff at least one row in this trip has lat/lng.
    has_gps: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}


class TripList(BaseModel):
    """Schema for trip list responses."""
    trips: List[Trip]
    total: int
    page: int
    per_page: int
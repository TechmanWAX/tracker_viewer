"""API v1 router aggregator."""

from fastapi import APIRouter

from app.api.v1.endpoints import auth, trips, telemetry, jobs, public

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(trips.router, prefix="/trips", tags=["trips"])
api_router.include_router(telemetry.router, prefix="/trips", tags=["telemetry"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(public.router, tags=["public"])
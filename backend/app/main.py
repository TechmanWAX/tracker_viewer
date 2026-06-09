"""FastAPI application factory and main entry point."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from app.api.v1.api import api_router
from app.core.config import get_settings
from app.middleware.rate_limit import setup_rate_limiting
from app.middleware.csrf_guard import setup_csrf_middleware

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Application lifespan context manager."""
        # Startup
        os.makedirs(settings.upload_dir, exist_ok=True)

        # Production-readiness gate. In dev (APP_BASE_URL points
        # at localhost) the dev defaults are intentionally
        # permissive, so we don't spam warnings on every reload —
        # we just log a one-liner saying the check ran. In prod
        # (any non-localhost APP_BASE_URL) every issue is logged
        # at WARNING and the process refuses to start, so a
        # missed-rotation at deploy time fails loud, not silent.
        issues = settings.validate_production_readiness()
        if settings.looks_like_production:
            for issue in issues:
                log.warning("PROD-READINESS: %s", issue)
            if issues:
                raise RuntimeError(
                    "Refusing to start: production-readiness check "
                    f"failed ({len(issues)} issue(s)). See warnings "
                    "above. To run with these settings, point "
                    "APP_BASE_URL at a localhost URL."
                )
        elif issues:
            log.info(
                "production-readiness check: %d dev-default(s) in use "
                "(suppressed). Run with APP_BASE_URL pointing at a "
                "non-localhost host to surface them.",
                len(issues),
            )

        yield
        # Shutdown
        pass

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="GPS Trip Tracker API - FastAPI with TimescaleDB",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )

    # Setup rate limiting
    setup_rate_limiting(app)

    # Setup CSRF middleware
    setup_csrf_middleware(app)

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # Include API router
    app.include_router(api_router)

    # Global exception handler for rate limiting
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": "Rate limit exceeded. Please try again later.",
                "retry_after": getattr(exc, "retry_after", 60),
            },
        )

    # Health check endpoint
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "version": settings.app_version}

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
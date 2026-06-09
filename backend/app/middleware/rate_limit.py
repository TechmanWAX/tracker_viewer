"""Rate limiting middleware using SlowAPI."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.core.config import get_settings


# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
)


def get_rate_limit_config() -> dict:
    """Get rate limit configuration."""
    settings = get_settings()
    return {
        "per_minute": f"{settings.rate_limit_requests}/{settings.rate_limit_window_seconds}s",
        "per_hour": f"{settings.rate_limit_requests * 10}/{settings.rate_limit_window_seconds * 60}s",
    }


async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Handle rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={
            "detail": "Rate limit exceeded. Please try again later.",
            "retry_after": getattr(exc, "retry_after", 60),
        },
    )


def setup_rate_limiting(app):
    """Setup rate limiting middleware for the app."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
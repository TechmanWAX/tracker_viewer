"""CSRF protection middleware using double-submit pattern."""

import secrets
from typing import Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import get_settings


CSRF_HEADER = "X-CSRF-Token"
CSRF_COOKIE = "csrf_token"


class CSRFGuardMiddleware(BaseHTTPMiddleware):
    """CSRF protection middleware using double-submit cookie pattern."""

    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with CSRF validation."""
        # Re-read settings on every request so tests can toggle CSRF
        # via env var without recreating the middleware.
        from app.core.config import get_settings
        settings = get_settings()

        # Skip CSRF check entirely when disabled (used in tests / dev)
        if not settings.csrf_enabled:
            return await call_next(request)

        # Skip CSRF check for safe methods
        if request.method in ["GET", "HEAD", "OPTIONS"]:
            response = await call_next(request)
            return response

        # Login/register are entry points — they issue the csrf_token cookie,
        # so they can't require one. Other /auth/* (logout, refresh) require it.
        if request.url.path.endswith(("/auth/login", "/auth/register", "/auth/resend-verification", "/auth/verify-email")):
            response = await call_next(request)
            return response

        # Skip CSRF check for API key authentication
        # (CSRF is only for cookie-based auth)
        
        # Get CSRF token from header
        header_token = request.headers.get(CSRF_HEADER)
        
        # Get CSRF token from cookie
        cookie_token = request.cookies.get(CSRF_COOKIE)
        
        # Validate tokens match
        if header_token and cookie_token:
            if not secrets.compare_digest(header_token, cookie_token):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF token validation failed"},
                )
        elif request.method in ["POST", "PUT", "PATCH", "DELETE"]:
            # For state-changing methods, require CSRF token
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token required"},
            )

        response = await call_next(request)
        return response


def setup_csrf_middleware(app):
    """Setup CSRF middleware for the app."""
    app.add_middleware(CSRFGuardMiddleware)
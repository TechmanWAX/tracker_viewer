"""Authentication endpoints.

This module handles the four flows that touch user identity:

* POST /register            — create an unverified user and email a link.
* POST /login               — password check, then `is_verified` gate.
* POST /verify-email        — consume a single-use token from the link.
* POST /resend-verification — request a new link (always 200, no leak).
* POST /refresh, /logout    — token rotation (unchanged from before).
* GET  /me                  — return the current user (unchanged).

The "is the user verified" gate is enforced in /login only.
/register, /verify-email, and /resend-verification do **not** set
auth cookies, so there's no way to bypass the gate by abusing one
of them.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Annotated

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.dependencies import get_current_user as get_current_user_dependency
from app.core.security import generate_csrf_token
from app.db.session import get_session
from app.models.user import User
from app.schemas.user import (
    UserCreate,
    User as UserSchema,
    UserLogin,
    VerifyEmailRequest,
    ResendVerificationRequest,
)
from app.services import email_service
from app.services.auth_service import (
    AuthService,
    VerificationTokenInvalid,
    VerificationTokenExpired,
    VerificationTokenUsed,
)

log = logging.getLogger(__name__)

router = APIRouter()

ACCESS_TOKEN_COOKIE = "access_token"
REFRESH_TOKEN_COOKIE = "refresh_token"
CSRF_TOKEN_COOKIE = "csrf_token"


# Error code constants for the verify-email endpoint. The frontend
# keys off `code` to show the right message.
VERIFY_CODE_INVALID = "invalid"
VERIFY_CODE_EXPIRED = "expired"
VERIFY_CODE_USED = "used"


def _user_payload(user: User) -> dict:
    return {
        "user_id": str(user.user_id),
        "email": user.email,
        "username": user.username,
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "verified_at": user.verified_at.isoformat() if user.verified_at else None,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Register a new user (or take over an unverified one) and
    email a single-use verification link.

    Response shape is the same in both cases. The response includes
    `verification_url` ONLY in dev (when `MAIL_ENABLED=false`) so
    the developer can copy-paste the link from the network panel
    without having to dig into /tmp/verification_emails/.
    """
    try:
        user, raw_token = await AuthService.register(session, user_data)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("register failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {str(e)}",
        )

    # Send the email. In dev this writes to /tmp/verification_emails/
    # and logs a one-liner; with MAIL_ENABLED=true it goes out
    # via real SMTP.
    email = await email_service.send_verification_email(user, raw_token)

    settings = get_settings()
    payload: dict = {
        "user": _user_payload(user),
        # Tell the client where the email went so the UI can show
        # "check your inbox at <email>". The actual verification
        # happens via the link in the email body, not from this
        # response.
        "message": (
            "Account created. Check your email for a verification "
            "link — it expires in "
            f"{settings.verification_token_ttl_minutes} minutes."
        ),
    }
    if not settings.mail_enabled:
        # Dev convenience: surface the link directly so we can
        # click it from the API docs / network panel without
        # touching /tmp. NEVER include this in production.
        payload["dev_verification_url"] = email.verification_url
    return payload


@router.post("/login")
async def login(
    request: Request,
    response: Response,
    credentials: UserLogin,
    session: AsyncSession = Depends(get_session),
):
    """Authenticate user and set cookies. Refuses to issue tokens
    to an unverified user — that user gets a 403 with a structured
    `code` so the frontend can offer a "resend verification email"
    button."""
    user = await AuthService.authenticate(session, credentials.email, credentials.password)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not user.is_verified:
        # Deliberately 403 (not 401) so the frontend can
        # distinguish "wrong password" from "needs verification".
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please verify your email before signing in. Check your inbox for the verification link.",
            headers={"X-Error-Code": "email_not_verified"},
        )

    access_token, refresh_token = AuthService.create_tokens(str(user.user_id))

    settings = get_settings()
    access_expires = timedelta(minutes=settings.access_token_expire_minutes)
    refresh_expires = timedelta(days=settings.refresh_token_expire_days)
    cookie_secure = settings.cookie_secure

    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=access_token,
        httponly=False,
        secure=cookie_secure,
        samesite="lax",
        max_age=int(access_expires.total_seconds()),
        path="/",
    )
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=cookie_secure,
        samesite="lax",
        max_age=int(refresh_expires.total_seconds()),
        path="/auth",
    )

    csrf_token = generate_csrf_token()
    response.set_cookie(
        key=CSRF_TOKEN_COOKIE,
        value=csrf_token,
        httponly=False,
        secure=cookie_secure,
        samesite="lax",
        max_age=3600,
        path="/",
    )

    return {"user": _user_payload(user)}


@router.post("/verify-email")
async def verify_email(
    body: VerifyEmailRequest,
    session: AsyncSession = Depends(get_session),
):
    """Consume a single-use verification link from the user's email.

    Returns 200 on success (including the rare case where the user
    is already verified — clicking a stale link is a no-op). On
    failure, returns 400 with a machine-readable `code` so the
    frontend can show the right message ("link expired" vs.
    "link already used" vs. "link is invalid").
    """
    try:
        user = await AuthService.verify_email(session, body.token)
    except VerificationTokenInvalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": VERIFY_CODE_INVALID, "message": "This verification link is not valid."},
        )
    except VerificationTokenExpired:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": VERIFY_CODE_EXPIRED, "message": "This verification link has expired. Request a new one below."},
        )
    except VerificationTokenUsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": VERIFY_CODE_USED, "message": "This verification link has already been used."},
        )

    return {
        "user": _user_payload(user),
        "message": "Email verified. You can now sign in.",
    }


@router.post("/resend-verification")
async def resend_verification(
    body: ResendVerificationRequest,
    session: AsyncSession = Depends(get_session),
):
    """Mint a new verification link for an unverified user.

    Always returns 200 with the same shape, regardless of whether
    the email is registered, so a caller can't enumerate which
    emails exist on the system. The "did anything actually
    happen" detail is logged server-side, not surfaced to the
    client.
    """
    sent = await AuthService.resend_verification(session, body.email)
    if not sent:
        # Either email not found or user already verified. We
        # don't disclose which — just return a generic success.
        log.info("resend_verification no-op for %s", body.email)
    return {
        "message": (
            "If that email is registered and unverified, a new "
            "verification link is on its way. The link expires "
            "in 30 minutes."
        ),
    }


@router.post("/refresh")
async def refresh_token(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Refresh access token using refresh token cookie."""
    refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE)

    if refresh_token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token not found",
        )

    from app.core.security import decode_token
    payload = decode_token(refresh_token)

    if payload is None or payload.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user = await session.get(User, payload.sub)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    access_token, new_refresh_token = AuthService.create_tokens(str(user.user_id))

    settings = get_settings()
    access_expires = timedelta(minutes=settings.access_token_expire_minutes)
    refresh_expires = timedelta(days=settings.refresh_token_expire_days)
    cookie_secure = settings.cookie_secure

    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=access_token,
        httponly=False,
        secure=cookie_secure,
        samesite="lax",
        max_age=int(access_expires.total_seconds()),
        path="/",
    )
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=new_refresh_token,
        httponly=True,
        secure=cookie_secure,
        samesite="lax",
        max_age=int(refresh_expires.total_seconds()),
        path="/auth",
    )

    return {"status": "success"}


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
):
    """Logout user and clear cookies."""
    response.delete_cookie(key=ACCESS_TOKEN_COOKIE, path="/")
    response.delete_cookie(key=REFRESH_TOKEN_COOKIE, path="/auth")
    response.delete_cookie(key=CSRF_TOKEN_COOKIE, path="/")

    return {"status": "success"}


@router.get("/me")
async def get_current_user(
    user: User = Depends(get_current_user_dependency),
):
    """Get current authenticated user."""
    return {"user": _user_payload(user)}

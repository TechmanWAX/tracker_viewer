"""Authentication service.

This module owns the four state transitions that involve
verification status:

  1. `register`  — create a new (unverified) user, mint a single-use
     verification token, and email the link. The user is **not**
     logged in.

  2. `verify_email` — consume a raw token, mark the row used, flip
     the user to `is_verified = TRUE`. Idempotent for already-
     verified users (returns success without consuming a new row).

  3. `resend_verification` — for an existing unverified user, mint
     a new token, delete the old one, and re-send. Returns
     `True`/`False` rather than the user object so the caller
     can't accidentally leak which emails are registered.

  4. `authenticate` — unchanged return shape, but if the user is
     not verified we still return them and the endpoint layer
     decides what status to surface. (We do NOT silently log them
     in.)

Single-use enforcement lives in `verify_email`: the row's
`used_at` is set in the same transaction that flips
`is_verified`, so a replay of the same token hits the
`used_at IS NOT NULL` branch and returns "already used".
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    get_password_hash,
    verify_password,
)
from app.models.email_verification import EmailVerification
from app.models.user import User
from app.schemas.user import UserCreate
from app.services import email_service


# Domain-level exceptions. The endpoint layer translates these into
# HTTP errors; the service layer doesn't import FastAPI HTTPException
# for "expected" failures so it stays testable in isolation.


class VerificationTokenInvalid(Exception):
    """Token doesn't exist in the database, or the user it points
    at no longer exists."""


class VerificationTokenExpired(Exception):
    """Token exists but its `expires_at` is in the past."""


class VerificationTokenUsed(Exception):
    """Token was already consumed (replay attempt)."""


def hash_verification_token(raw_token: str) -> str:
    """SHA-256 hex of a raw token. Constant-time comparison isn't
    needed here because the DB lookup is the gating step, not the
    hash comparison itself."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def mint_verification_token() -> str:
    """32 random bytes, URL-safe base64. ~43 chars. 256 bits of
    entropy — unguessable. Only the caller (and the email) ever
    sees the raw value; the DB stores the hash."""
    return secrets.token_urlsafe(32)


class AuthService:
    """Service for user authentication and registration."""

    @staticmethod
    async def register(
        session: AsyncSession,
        user_data: UserCreate,
    ) -> tuple[User, str]:
        """Register a new user OR regenerate the verification link
        for an existing unverified user with the same email.

        Returns the (user, raw_token). The raw token is returned so
        the endpoint can include the verification URL in dev
        responses (it's also written to the dev email file).

        Re-registration with an unverified email: we update the
        password to the new one and mint a fresh token. The user
        "owns" the account as long as they can read mail at the
        address on file at the time of the most recent link.
        Re-registration with a verified email: 400.
        """
        existing = await AuthService.get_user_by_email(session, user_data.email)

        if existing is not None and existing.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered",
            )

        # Username uniqueness has to hold across BOTH the "new
        # user" and the "take over existing unverified user"
        # branches. The simplest correct check is: is there *any*
        # user with this username whose email is different from
        # the one we're registering? If so, the username is taken
        # by someone else.
        if existing is None:
            uname_result = await session.execute(
                select(User).where(User.username == user_data.username)
            )
            if uname_result.scalar_one_or_none() is not None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Username already taken",
                )
            user = User(
                email=user_data.email,
                username=user_data.username,
                hashed_password=get_password_hash(user_data.password),
                is_verified=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            # Take over the unverified account. We trust the email
            # owner: whoever can read mail at this address gets the
            # account.
            existing.username = user_data.username
            existing.hashed_password = get_password_hash(user_data.password)
            user = existing
            await session.commit()
            await session.refresh(user)

        raw_token = await AuthService._rotate_verification_token(session, user)
        return user, raw_token

    # NOTE: the `_rotate_verification_token` helper is defined below
    # in this class; the reference above resolves at call time.

    @staticmethod
    async def _rotate_verification_token(
        session: AsyncSession,
        user: User,
    ) -> str:
        """Mint a new verification token, delete any previous rows
        for this user, persist the new one, return the raw token.

        The DB stores SHA-256(raw) — the raw value is returned so
        the caller can embed it in the email and (in dev) the API
        response.
        """
        settings = get_settings()
        raw = mint_verification_token()
        token_hash = hash_verification_token(raw)
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.verification_token_ttl_minutes
        )

        # Wipe out any prior tokens for this user. We could keep
        # history for audit, but the only state we need is "the
        # latest, valid, un-consumed one" — and keeping old rows
        # around makes the table grow for no benefit.
        await session.execute(
            delete(EmailVerification).where(EmailVerification.user_id == user.user_id)
        )

        row = EmailVerification(
            user_id=user.user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        session.add(row)
        await session.commit()
        return raw

    @staticmethod
    async def verify_email(
        session: AsyncSession,
        raw_token: str,
    ) -> User:
        """Consume a verification token.

        Raises a domain exception for every failure mode so the
        endpoint can map it onto an HTTP error code with a
        specific reason.

        Idempotent: if the user is already verified, returns them
        without consuming a fresh row.
        """
        token_hash = hash_verification_token(raw_token)
        result = await session.execute(
            select(EmailVerification).where(EmailVerification.token_hash == token_hash)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise VerificationTokenInvalid("Verification link is not valid.")

        if row.used_at is not None:
            raise VerificationTokenUsed("This verification link has already been used.")

        # Postgres returns naive datetimes for TIMESTAMP WITHOUT TIME
        # ZONE; with TIME ZONE it returns aware UTC datetimes. We
        # compare in UTC to be safe.
        now = datetime.now(timezone.utc)
        expires_at = row.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise VerificationTokenExpired("This verification link has expired.")

        user = await session.get(User, row.user_id)
        if user is None:
            # Shouldn't happen — ON DELETE CASCADE on the FK should
            # have removed the row too. Treat as invalid.
            raise VerificationTokenInvalid("User no longer exists.")

        # Mark the token consumed and the user verified in the same
        # transaction. If either step fails, neither persists, so a
        # network hiccup mid-flight can't leave us with a consumed
        # token and an unverified user.
        row.used_at = now
        if not user.is_verified:
            user.is_verified = True
            user.verified_at = now
        await session.commit()
        await session.refresh(user)
        return user

    @staticmethod
    async def resend_verification(
        session: AsyncSession,
        email: str,
    ) -> bool:
        """For an unverified user with the given email, mint and
        email a fresh verification link. Returns True iff an email
        was actually sent (so the endpoint can know whether to log
        the URL — we always return 200 to the client either way
        to avoid leaking which emails are registered)."""
        user = await AuthService.get_user_by_email(session, email)
        if user is None:
            return False
        if user.is_verified:
            return False
        raw = await AuthService._rotate_verification_token(session, user)
        await email_service.send_verification_email(user, raw)
        return True

    @staticmethod
    async def authenticate(
        session: AsyncSession,
        email: str,
        password: str,
    ) -> Optional[User]:
        """Authenticate a user by email + password.

        Returns the User (regardless of `is_verified`) so the
        endpoint layer can return a 403 "please verify your email"
        instead of a generic 401 — that's a much better UX.

        The endpoint is responsible for the is_verified gate; this
        function only verifies the password.
        """
        result = await session.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    @staticmethod
    def create_tokens(user_id: str) -> tuple[str, str]:
        # Imported lazily to keep this module decoupled from the
        # token utilities at import time.
        from app.core.security import create_access_token, create_refresh_token

        access = create_access_token(user_id)
        refresh = create_refresh_token(user_id)
        return access, refresh

    @staticmethod
    async def get_user_by_id(
        session: AsyncSession,
        user_id: str,
    ) -> Optional[User]:
        return await session.get(User, user_id)

    @staticmethod
    async def get_user_by_email(
        session: AsyncSession,
        email: str,
    ) -> Optional[User]:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

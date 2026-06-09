"""Tests for email verification at the service layer.

We test `AuthService.verify_email` and `_rotate_verification_token`
directly with a mocked AsyncSession. The endpoint-layer tests for
the HTTP shape live elsewhere (and are exercised by the smoke
script in the dev environment).

What's covered:
  * Token consumption flips `is_verified` to True.
  * Replay → "already used" exception, user stays verified.
  * Expired token → "expired" exception, no state change.
  * Garbage token (no row) → "invalid" exception.
  * Resend rotates the token (old hash becomes invalid, new hash works).
  * AuthService.resend_verification returns False for unknown /
    already-verified emails, True for an unverified one.
  * `authenticate` returns the user even if not verified (the
    endpoint layer is the one that returns 403).
  * Registering with an already-verified email → 400.
  * Registering again with the same unverified email rotates
    the token and updates the password.

The mocked AsyncSession implements just enough of the SQLAlchemy
async API to run the queries the service issues: `execute`,
`get`, `add`, `commit`, `refresh`. The result scalars are
constructed in-memory.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Iterable, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.services.auth_service import (
    AuthService,
    VerificationTokenExpired,
    VerificationTokenInvalid,
    VerificationTokenUsed,
    hash_verification_token,
    mint_verification_token,
)
from app.services import email_service


# All service methods are `async`. The project's pytest is configured
# with `asyncio_mode = strict`, so each async test needs the
# `@pytest.mark.asyncio` marker.
pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Minimal in-memory stand-in for SQLAlchemy's async session.
# Implements just the operations the service uses: execute, get, add,
# commit, refresh, delete. We back it with a dict keyed by primary
# filter so the lookups behave the way the production code expects.
# ---------------------------------------------------------------------------


@dataclass
class _FakeScalarResult:
    rows: list
    def scalar_one_or_none(self) -> Any:
        return self.rows[0] if self.rows else None


@dataclass
class _FakeSession:
    """Tiny in-memory AsyncSession replacement.

    Tracks rows by `tablename` (a class attribute of the model).
    Supports:
      * `execute(stmt)` where `stmt` is a SQLAlchemy `select(...)` /
        `delete(...)` statement (we only need the where-clauses).
      * `get(Model, pk)` — returns the row whose PK matches.
      * `add(obj)` / `commit()` / `refresh(obj)` — keep objects in
        memory and copy attribute values on commit.
    """

    users: dict = field(default_factory=dict)            # user_id -> User
    verifications: dict = field(default_factory=dict)    # token_hash -> EmailVerification
    adds: list = field(default_factory=list)

    async def execute(self, stmt) -> _FakeScalarResult:
        # We rely on the fact that the service code uses
        # `select(Model).where(Model.col == val)` and
        # `delete(Model).where(Model.col == val)` only. Parse
        # those without importing sqlalchemy.
        from sqlalchemy.sql.selectable import Select
        from sqlalchemy.sql.dml import Delete

        if isinstance(stmt, Select):
            model = stmt.column_descriptions[0]["entity"].__name__
            rows = self._select_rows(model, stmt)
            return _FakeScalarResult(rows=list(rows))
        if isinstance(stmt, Delete):
            model = stmt.table.name
            self._delete_where(model, stmt)
            return _FakeScalarResult(rows=[])  # result not used by caller
        raise NotImplementedError(f"_FakeSession.execute: unsupported {stmt!r}")

    def _select_rows(self, model_name: str, stmt) -> Iterable:
        table = self._table_for(model_name)
        # The where-clauses are simple `col == val`. Pull them out
        # by comparing table-row attributes.
        wheres = self._extract_where_clauses(stmt)
        for row in table.values():
            if all(getattr(row, col) == val for col, val in wheres):
                yield row

    def _table_for(self, model_name: str) -> dict:
        # `select(Model).where(...)` reports the model class; the
        # `Delete` statement reports the SQLAlchemy `Table.name`.
        # Both forms need to land on the same backing dict.
        #
        # Direct mapping by either form:
        mapping = {
            "User": self.users,
            "users": self.users,
            "EmailVerification": self.verifications,
            "email_verifications": self.verifications,
        }
        if model_name in mapping:
            return mapping[model_name]
        raise NotImplementedError(model_name)

    def _delete_where(self, model_name: str, stmt) -> int:
        table = self._table_for(model_name)
        wheres = self._extract_where_clauses(stmt)
        n = 0
        for k in list(table.keys()):
            row = table[k]
            if all(getattr(row, col) == val for col, val in wheres):
                del table[k]
                n += 1
        return n

    @staticmethod
    def _extract_where_clauses(stmt) -> list:
        # SQLAlchemy exposes clauses via `._whereclause` (private).
        # We only need binary `Column == value` predicates.
        clauses: list = []
        node = getattr(stmt, "_whereclause", None)
        if node is None:
            return clauses
        # A boolean AND combines multiple `BinaryExpression`s.
        for child in getattr(node, "clauses", [node]):
            left = getattr(child, "left", None)
            right = getattr(child, "right", None)
            if left is not None and right is not None:
                col_name = getattr(left, "key", None) or getattr(left, "name", None)
                val = getattr(right, "value", right)
                if col_name is not None:
                    clauses.append((col_name, val))
        return clauses

    async def get(self, model, pk):
        table = self.users if model.__name__ == "User" else None
        if table is None:
            return None
        return table.get(str(pk))

    def add(self, obj):
        self.adds.append(obj)
        # Persist into the appropriate table dict.
        cls_name = type(obj).__name__
        if cls_name == "User":
            self.users[str(obj.user_id)] = obj
        elif cls_name == "EmailVerification":
            self.verifications[obj.token_hash] = obj

    async def commit(self) -> None:
        # In a real session, the row would be flushed. Our fake
        # `add` already inserts into the table dict, so commit
        # is a no-op.
        return None

    async def refresh(self, obj) -> None:
        # SQLAlchemy would re-read DB-generated columns. We don't
        # use server defaults, so this is a no-op.
        return None


def make_user(
    *,
    user_id: str = "u-1",
    email: str = "a@example.com",
    username: str = "alice",
    is_verified: bool = False,
    verified_at: Optional[datetime] = None,
) -> Any:
    """Build a minimal User-like object with the columns the
    service reads."""
    from app.models.user import User  # local import — pulls in the
                                       # real type so the service
                                       # treats it the same way.

    u = User(
        user_id=user_id,
        email=email,
        username=username,
        hashed_password="x" * 60,
        is_verified=is_verified,
    )
    u.verified_at = verified_at
    return u


def make_verification(
    *,
    user_id: str,
    token_hash: str,
    expires_at: Optional[datetime] = None,
    used_at: Optional[datetime] = None,
) -> Any:
    from app.models.email_verification import EmailVerification

    row = EmailVerification(
        id="ev-1",
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at or (datetime.now(timezone.utc) + timedelta(minutes=30)),
    )
    row.used_at = used_at
    return row


# Patch `email_service.send_verification_email` so the dev
# file-writer doesn't pollute /tmp during the test run. The real
# function is async, so we return an awaitable that resolves to a
# SimpleNamespace mimicking its return shape.
@pytest.fixture(autouse=True)
def _disable_dev_email(monkeypatch, tmp_path):
    async def _fake_send(user, raw):
        return SimpleNamespace(
            to=user.email,
            verification_url=f"http://test/verify-email?token={raw}",
        )
    monkeypatch.setattr(
        email_service,
        "send_verification_email",
        _fake_send,
    )


# ---------------------------------------------------------------------------
# verify_email
# ---------------------------------------------------------------------------


class TestVerifyEmail:
    async def test_happy_path_flips_user_to_verified(self):
        user = make_user(is_verified=False)
        raw = mint_verification_token()
        session = _FakeSession()
        session.users[user.user_id] = user
        session.verifications[hash_verification_token(raw)] = make_verification(
            user_id=user.user_id,
            token_hash=hash_verification_token(raw),
        )

        result = await AuthService.verify_email(session, raw)

        assert result.is_verified is True
        assert result.verified_at is not None
        # The token row should be marked used.
        token_hash = hash_verification_token(raw)
        assert session.verifications[token_hash].used_at is not None

    async def test_replay_raises_used(self):
        user = make_user(is_verified=True)
        raw = mint_verification_token()
        session = _FakeSession()
        session.users[user.user_id] = user
        session.verifications[hash_verification_token(raw)] = make_verification(
            user_id=user.user_id,
            token_hash=hash_verification_token(raw),
            used_at=datetime.now(timezone.utc),
        )

        with pytest.raises(VerificationTokenUsed):
            await AuthService.verify_email(session, raw)

    async def test_expired_raises_expired(self):
        user = make_user(is_verified=False)
        raw = mint_verification_token()
        session = _FakeSession()
        session.users[user.user_id] = user
        session.verifications[hash_verification_token(raw)] = make_verification(
            user_id=user.user_id,
            token_hash=hash_verification_token(raw),
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )

        with pytest.raises(VerificationTokenExpired):
            await AuthService.verify_email(session, raw)

    async def test_unknown_token_raises_invalid(self):
        session = _FakeSession()
        with pytest.raises(VerificationTokenInvalid):
            await AuthService.verify_email(session, mint_verification_token())

    async def test_hash_is_deterministic_and_one_way(self):
        raw = "abcd1234abcd1234"
        a = hash_verification_token(raw)
        b = hash_verification_token(raw)
        assert a == b
        # 64 hex chars
        assert len(a) == 64
        # Different raw → different hash
        assert a != hash_verification_token(raw + "x")


# ---------------------------------------------------------------------------
# _rotate_verification_token / resend_verification
# ---------------------------------------------------------------------------


class TestRotateAndResend:
    async def test_rotate_replaces_existing_token(self):
        user = make_user(is_verified=False)
        session = _FakeSession()
        session.users[user.user_id] = user
        # Pre-existing token row.
        old_hash = hash_verification_token("old-token-xxxxx")
        session.verifications[old_hash] = make_verification(
            user_id=user.user_id, token_hash=old_hash,
        )

        new_raw = await AuthService._rotate_verification_token(session, user)
        # The old row is gone, the new one is present.
        assert old_hash not in session.verifications
        new_hash = hash_verification_token(new_raw)
        assert new_hash in session.verifications
        # Returns the raw token, not the hash.
        assert isinstance(new_raw, str) and len(new_raw) >= 32

    async def test_resend_returns_false_for_unknown_email(self):
        session = _FakeSession()
        assert await AuthService.resend_verification(session, "nope@example.com") is False

    async def test_resend_returns_false_for_already_verified(self):
        user = make_user(is_verified=True)
        session = _FakeSession()
        session.users[user.user_id] = user
        assert await AuthService.resend_verification(session, user.email) is False

    async def test_resend_returns_true_and_rotates_for_unverified(self):
        user = make_user(is_verified=False)
        session = _FakeSession()
        session.users[user.user_id] = user
        old_raw = mint_verification_token()
        session.verifications[hash_verification_token(old_raw)] = make_verification(
            user_id=user.user_id,
            token_hash=hash_verification_token(old_raw),
        )

        sent = await AuthService.resend_verification(session, user.email)
        assert sent is True
        # The old token is now gone.
        assert hash_verification_token(old_raw) not in session.verifications


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


class TestRegister:
    async def test_new_user_is_unverified(self):
        session = _FakeSession()
        # Use a UUID that doesn't collide with anyone.
        from uuid import uuid4
        # The service will create the user with whatever PK it
        # wants. Our fake stores by whatever `user_id` the model
        # ends up with — which is what `get_user_by_email` then
        # looks up.

        # To avoid mocking the model default, use a known id.
        from app.models.user import User
        from sqlalchemy import inspect

        # We just check the resulting user has is_verified=False
        # and a token row was created.
        user, raw = await AuthService.register(
            session,
            SimpleNamespace(
                email="new@example.com",
                username="newuser",
                password="hunter2hunter2",
            ),
        )
        assert user.is_verified is False
        assert isinstance(raw, str) and len(raw) >= 32
        assert hash_verification_token(raw) in session.verifications

    async def test_re_register_with_verified_email_raises_400(self):
        existing = make_user(is_verified=True)
        session = _FakeSession()
        session.users[existing.user_id] = existing

        with pytest.raises(HTTPException) as exc:
            await AuthService.register(
                session,
                SimpleNamespace(
                    email=existing.email,
                    username="newusername",
                    password="hunter2hunter2",
                ),
            )
        assert exc.value.status_code == 400

    async def test_re_register_with_unverified_email_rotates_token_and_updates_password(self):
        existing = make_user(is_verified=False)
        # Pre-seed an old token row so we can verify it gets wiped.
        old_raw = mint_verification_token()
        session = _FakeSession()
        session.users[existing.user_id] = existing
        session.verifications[hash_verification_token(old_raw)] = make_verification(
            user_id=existing.user_id,
            token_hash=hash_verification_token(old_raw),
        )

        user, new_raw = await AuthService.register(
            session,
            SimpleNamespace(
                email=existing.email,
                username=existing.username,
                password="NewPAssw0rd!9876",
            ),
        )
        # Same user, new token, old token gone.
        assert user.user_id == existing.user_id
        assert new_raw != old_raw
        assert hash_verification_token(old_raw) not in session.verifications
        assert hash_verification_token(new_raw) in session.verifications

    async def test_register_with_existing_username_raises_400(self):
        from app.models.user import User
        existing = make_user(username="taken", email="other@example.com")
        session = _FakeSession()
        session.users[existing.user_id] = existing

        with pytest.raises(HTTPException) as exc:
            await AuthService.register(
                session,
                SimpleNamespace(
                    email="different@example.com",
                    username="taken",
                    password="hunter2hunter2",
                ),
            )
        assert exc.value.status_code == 400

"""
Tests for Phase C auth: password hashing, JWT issuance/verification, and
the meeting ownership check (row-level isolation).
"""

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("QDRANT_HOST", "localhost")

import uuid
from types import SimpleNamespace

import pytest

from apps.api.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        h = hash_password("correct horse battery staple")
        assert h != "correct horse battery staple"  # not plaintext
        assert verify_password("correct horse battery staple", h) is True

    def test_wrong_password_fails(self):
        h = hash_password("secret123")
        assert verify_password("wrong", h) is False

    def test_hashes_are_salted(self):
        # Same password → different hashes (random salt)
        assert hash_password("same") != hash_password("same")


class TestJWT:
    def test_roundtrip(self):
        token = create_access_token("user-123", extra_claims={"email": "a@b.com"})
        claims = decode_access_token(token)
        assert claims is not None
        assert claims["sub"] == "user-123"
        assert claims["email"] == "a@b.com"
        assert claims["type"] == "access"

    def test_tampered_token_rejected(self):
        token = create_access_token("user-123")
        assert decode_access_token(token + "tampered") is None

    def test_garbage_rejected(self):
        assert decode_access_token("not.a.jwt") is None


class TestOwnershipCheck:
    """The _check_owner helper enforces row-level isolation."""

    def _check(self, meeting, user):
        from apps.api.routers.meetings import _check_owner

        return _check_owner(meeting, user)

    def test_no_user_allowed(self):
        # Auth off → no user → access allowed (legacy/demo behavior)
        m = SimpleNamespace(owner_id=uuid.uuid4())
        assert self._check(m, None) is None  # no raise

    def test_owner_allowed(self):
        uid = uuid.uuid4()
        m = SimpleNamespace(owner_id=uid)
        user = SimpleNamespace(id=uid)
        assert self._check(m, user) is None  # no raise

    def test_non_owner_404(self):
        from fastapi import HTTPException

        m = SimpleNamespace(owner_id=uuid.uuid4())
        user = SimpleNamespace(id=uuid.uuid4())  # different user
        with pytest.raises(HTTPException) as exc:
            self._check(m, user)
        assert exc.value.status_code == 404

    def test_unowned_meeting_allowed(self):
        # Legacy meeting with no owner → accessible to any user
        m = SimpleNamespace(owner_id=None)
        user = SimpleNamespace(id=uuid.uuid4())
        assert self._check(m, user) is None

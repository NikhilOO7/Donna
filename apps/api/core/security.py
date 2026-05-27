"""
Password hashing (Argon2) and JWT issuance/verification.

Argon2 is the modern default for password storage; PyJWT signs short-lived
HS256 access tokens. Both libraries are already project dependencies.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from apps.api.core.config import settings

logger = logging.getLogger(__name__)

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except VerifyMismatchError:
        return False
    except Exception as e:
        logger.warning(f"Password verification error: {e}")
        return False


def create_access_token(
    subject: str, extra_claims: Optional[Dict[str, Any]] = None
) -> str:
    """Mint a signed JWT. ``subject`` is the user id (``sub`` claim)."""
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Return the JWT claims, or None if invalid/expired."""
    try:
        return jwt.decode(
            token, settings.jwt_secret, algorithms=[settings.jwt_algorithm]
        )
    except jwt.ExpiredSignatureError:
        logger.info("JWT expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.info(f"Invalid JWT: {e}")
        return None

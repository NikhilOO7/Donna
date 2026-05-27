"""
Authentication for the Voice Document Intelligence API.

Two principals:

* **Users** — JWT bearer tokens (``Authorization: Bearer <jwt>``), issued
  by ``/api/v1/auth/login``. Carry a user id and own meetings.
* **Service** — the static ``X-API-Key`` header, used by trusted internal
  callers like the voice worker that post utterances without a user
  session.

``verify_api_key`` is kept for service-to-service calls. ``get_current_user``
resolves a user from the JWT. ``require_user`` enforces a logged-in user
(used on owner-scoped endpoints when ``REQUIRE_AUTH`` is on).
"""

import logging
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.config import settings
from apps.api.core.database import get_db
from apps.api.core.security import decode_access_token

logger = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
BEARER = HTTPBearer(auto_error=False)


async def verify_api_key(
    api_key: Optional[str] = Security(API_KEY_HEADER),
) -> Optional[str]:
    """Verify the static service API key (X-API-Key).

    In development with ``require_api_key=False`` this is a no-op.
    """
    if not settings.require_api_key:
        return api_key

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key required. Pass it via X-API-Key header.",
        )
    if api_key != settings.api_key:
        logger.warning("Invalid API key attempt")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key"
        )
    return api_key


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(BEARER),
    session: AsyncSession = Depends(get_db),
):
    """Resolve the User from a JWT bearer token, or None if absent/invalid."""
    if credentials is None or not credentials.credentials:
        return None

    claims = decode_access_token(credentials.credentials)
    if not claims or not claims.get("sub"):
        return None

    from uuid import UUID

    from apps.api.models.user import User

    try:
        uid = UUID(claims["sub"])
    except (ValueError, TypeError):
        return None

    result = await session.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        return None
    return user


async def require_user(current_user=Depends(get_current_user)):
    """Dependency that 401s when no valid user is present.

    When ``REQUIRE_AUTH`` is off (dev/demo), a missing user is allowed
    through as ``None`` so existing un-authenticated flows keep working.
    """
    if current_user is None and settings.require_auth:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def get_service_or_user(
    api_key: Optional[str] = Security(API_KEY_HEADER),
    credentials: Optional[HTTPAuthorizationCredentials] = Security(BEARER),
    session: AsyncSession = Depends(get_db),
):
    """Accept EITHER a valid service API key OR a user JWT.

    Used by endpoints callable both by the voice worker (API key) and by
    the browser (user JWT) — e.g. posting utterances. Returns the User
    when a JWT was used, else None for service callers.
    """
    # Service key path
    if api_key and settings.api_key and api_key == settings.api_key:
        return None

    user = await get_current_user(credentials=credentials, session=session)
    if user is not None:
        return user

    # Neither principal — only reject when auth is enforced
    if settings.require_auth or settings.require_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (Bearer token or X-API-Key)",
        )
    return None

"""
Simple API key authentication for the Voice Document Intelligence API.
"""

import logging
from typing import Optional

from fastapi import Security, HTTPException, status
from fastapi.security import APIKeyHeader

from apps.api.core.config import settings

logger = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: Optional[str] = Security(API_KEY_HEADER)) -> Optional[str]:
    """
    Verify the API key from the X-API-Key header.
    In development mode with require_api_key=False, authentication is skipped.
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
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key",
        )

    return api_key

"""
Rate limiting for API endpoints using slowapi with Redis backend.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from apps.api.core.config import settings


def _key_func(request: Request) -> str:
    """Extract client identifier for rate limiting."""
    # Use API key if present, otherwise fall back to IP
    api_key = request.headers.get("X-API-Key")
    if api_key:
        return f"apikey:{api_key}"
    return get_remote_address(request)


limiter = Limiter(
    key_func=_key_func,
    storage_uri=settings.redis_url,
    strategy="fixed-window",
    # Applied to every route via SlowAPIMiddleware; health/metrics are exempted
    # with @limiter.exempt. Expensive routes add their own stricter @limiter.limit.
    default_limits=[settings.rate_limit_default],
)


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Custom handler for rate limit exceeded errors."""
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": str(exc.detail),
            "status_code": 429,
        },
    )

"""
Rate limiting for authentication endpoints using slowapi.

Tracks login attempts by client IP address and enforces a limit
of 5 attempts per minute per IP.
"""
import logging
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Rate limiter: 5 requests per minute per IP
limiter = Limiter(key_func=get_remote_address)


async def rate_limit_error_handler(request, exc: RateLimitExceeded) -> JSONResponse:
    """Custom error handler for rate limit exceeded responses."""
    logger.warning(
        f"Rate limit exceeded for IP {request.client.host if request.client else 'unknown'}"
    )
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": "Too many login attempts. Please try again later.",
            "status_code": status.HTTP_429_TOO_MANY_REQUESTS,
        },
    )

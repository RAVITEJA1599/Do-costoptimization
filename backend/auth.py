"""
JWT authentication: signup/login endpoints, password hashing with bcrypt,
token generation with PyJWT, and FastAPI dependency for protected routes.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from config import config
from db import create_user, get_user_by_email, get_user_by_id, get_all_users, delete_user, update_user_password
from models import UsersListResponse, UserItem
from rate_limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])
_bearer = HTTPBearer(auto_error=False)

TOKEN_EXPIRY_DAYS = 7
ALGORITHM = "HS256"


# ── Request / response models ─────────────────────────────────────────────────

class AuthRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TokenResponse(BaseModel):
    token: str


# ── Token helpers ─────────────────────────────────────────────────────────────

def _create_token(user_id: str, email: str) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(days=TOKEN_EXPIRY_DAYS),
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm=ALGORITHM)


def _decode_token(token: str) -> dict:
    """Raises jwt.InvalidTokenError on bad/expired tokens."""
    return jwt.decode(token, config.JWT_SECRET, algorithms=[ALGORITHM])


def verify_token(token: str) -> Optional[dict]:
    """Return the JWT payload dict, or None if the token is missing, expired, or invalid.

    Used by the WebSocket endpoint which cannot raise HTTPException during handshake.
    Never logs the token value.
    """
    try:
        return _decode_token(token)
    except jwt.InvalidTokenError:
        return None


# ── FastAPI auth dependencies ─────────────────────────────────────────────────

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """
    Required auth dependency — returns JWT payload or raises 401.
    Usage:  current_user: dict = Depends(get_current_user)
    """
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = _decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    user = await get_user_by_id(payload.get("user_id", ""))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Session expired, please log in again")
    return payload


async def get_current_user_optional(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> Optional[dict]:
    """
    Optional auth dependency — returns JWT payload or None (never 401).
    Used by POST /api/analyze so it works both authenticated and unauthenticated.
    """
    if not credentials:
        return None
    try:
        return _decode_token(credentials.credentials)
    except jwt.InvalidTokenError:
        return None


# ── Auth endpoints ────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(request: Request, body: AuthRequest):
    """Verify credentials and return a JWT token.

    Rate limited to 5 attempts per minute per IP address.
    """
    email = body.email.strip().lower()

    user = await get_user_by_email(email)
    if not user or not bcrypt.checkpw(body.password.encode(), user.password_hash.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    token = _create_token(user.id, user.email)
    logger.info(f"User logged in: {email}")
    return TokenResponse(token=token)


@router.post("/create-user", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def create_user_admin(
    body: AuthRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a new user (admin only - requires authentication)."""
    email = body.email.strip().lower()

    if "@" not in email or len(email) < 5:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Invalid email address")
    if len(body.password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail="Password must be at least 8 characters")

    existing = await get_user_by_email(email)
    if existing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    password_hash = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    user = await create_user(email, password_hash)

    token = _create_token(user.id, user.email)
    logger.info(f"New user created by {current_user.get('email')}: {email}")
    return TokenResponse(token=token)


@router.get("/users", response_model=UsersListResponse)
async def list_users(
    current_user: dict = Depends(get_current_user),
):
    """Get all users (requires authentication)."""
    users = await get_all_users()
    user_items = [
        UserItem(
            id=user.id,
            email=user.email,
            created_at=user.created_at.isoformat(),
        )
        for user in users
    ]
    return UsersListResponse(users=user_items, count=len(user_items))


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    """Change the current user's password."""
    email = current_user.get("email")
    user = await get_user_by_email(email)
    if not user or not bcrypt.checkpw(body.current_password.encode(), user.password_hash.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail="New password must be at least 8 characters")
    new_hash = bcrypt.hashpw(body.new_password.encode(), bcrypt.gensalt()).decode()
    await update_user_password(email, new_hash)
    logger.info(f"Password changed for user: {email}")
    return {"message": "Password updated successfully"}


@router.delete("/users/{user_id}")
async def delete_user_endpoint(
    user_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Delete a user by ID (requires authentication)."""
    success = await delete_user(user_id)
    if not success:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    logger.info(f"User {user_id} deleted by {current_user.get('email')}")
    return {"message": "User deleted successfully"}

"""
Authentication endpoints: register, login, current user.

Issues JWT access tokens; passwords are Argon2-hashed. Meeting ownership
and row-level isolation build on the user identity established here.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.auth import require_user
from apps.api.core.database import get_db
from apps.api.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from apps.api.models.user import (
    TokenResponse,
    User,
    UserLogin,
    UserRegister,
    UserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: UserRegister, session: AsyncSession = Depends(get_db)):
    """Create a user account and return an access token."""
    email = body.email.lower()

    existing = await session.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=email,
        full_name=body.full_name or "",
        hashed_password=hash_password(body.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    token = create_access_token(subject=str(user.id), extra_claims={"email": email})
    logger.info(f"User registered: {email}")
    return TokenResponse(
        access_token=token, user=UserResponse.model_validate(user)
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin, session: AsyncSession = Depends(get_db)):
    """Authenticate and return an access token."""
    email = body.email.lower()
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()

    # Same error + a verify call whether or not the user exists, to avoid
    # leaking which emails are registered via timing/response differences.
    if user is None:
        # Burn a hash verification to keep timing roughly constant.
        verify_password(body.password, hash_password("dummy-timing-guard"))
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    token = create_access_token(subject=str(user.id), extra_claims={"email": email})
    return TokenResponse(
        access_token=token, user=UserResponse.model_validate(user)
    )


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(require_user)):
    """Return the currently authenticated user."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return UserResponse.model_validate(current_user)

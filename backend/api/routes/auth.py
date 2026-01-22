"""
Authentication routes.

Handles user registration and login with JWT tokens.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from backend.api.dependencies import create_access_token, get_current_user
from backend.persistence.database import DatabaseService, get_db_service
from backend.persistence.models import User, UserCreate

logger = logging.getLogger(__name__)

router = APIRouter()


class TokenResponse(BaseModel):
    """Response model for authentication tokens."""

    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str


class UserResponse(BaseModel):
    """Response model for user data."""

    id: str
    username: str


@router.post("/register", response_model=TokenResponse)
async def register(
    user_data: UserCreate,
    db: DatabaseService = Depends(get_db_service),
):
    """
    Register a new user.

    Returns access token on successful registration.
    """
    logger.info(f"Registration attempt for username: {user_data.username}")

    user = await db.create_user(user_data.username, user_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already exists",
        )

    token = create_access_token(user)

    logger.info(f"User registered: {user.id}")
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: DatabaseService = Depends(get_db_service),
):
    """
    Authenticate user and return access token.

    Uses OAuth2 password flow.
    """
    logger.info(f"Login attempt for username: {form_data.username}")

    user = await db.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = create_access_token(user)

    logger.info(f"User logged in: {user.id}")
    return TokenResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """
    Get current authenticated user info.
    """
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
    )

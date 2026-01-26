"""
FastAPI dependencies for authentication and database access.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from backend.core.config import config
from backend.persistence.database import DatabaseService, get_db_service
from backend.persistence.models import User

logger = logging.getLogger(__name__)

# OAuth2 scheme for JWT tokens
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


class TokenData(BaseModel):
    """JWT token payload data."""

    user_id: str
    username: str
    exp: datetime


def create_access_token(user: User) -> str:
    """
    Create JWT access token for a user.

    Args:
        user: User to create token for

    Returns:
        Encoded JWT token
    """
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=config.auth.access_token_expire_minutes
    )

    payload = {
        "sub": user.id,
        "username": user.username,
        "exp": expire,
    }

    return jwt.encode(
        payload,
        config.auth.secret_key,
        algorithm=config.auth.algorithm,
    )


def decode_token(token: str) -> Optional[TokenData]:
    """
    Decode and validate JWT token.

    Args:
        token: JWT token string

    Returns:
        TokenData if valid, None otherwise
    """
    try:
        payload = jwt.decode(
            token,
            config.auth.secret_key,
            algorithms=[config.auth.algorithm],
        )

        return TokenData(
            user_id=payload.get("sub"),
            username=payload.get("username"),
            exp=datetime.fromtimestamp(payload.get("exp"), tz=timezone.utc),
        )
    except JWTError as e:
        logger.debug(f"Token decode error: {e}")
        return None


async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: DatabaseService = Depends(get_db_service),
) -> User:
    """
    Get current authenticated user from JWT token.

    Raises HTTPException if not authenticated.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not token:
        raise credentials_exception

    token_data = decode_token(token)
    if not token_data:
        raise credentials_exception

    # Check if token is expired
    if token_data.exp < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Get user from database
    user = await db.get_user_by_id(token_data.user_id)
    if not user:
        raise credentials_exception

    return user

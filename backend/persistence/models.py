"""
Pydantic models for the persistence layer.

These models define the data structures for users, runs, and approvals.
"""

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field


# --- User Models ---

class UserCreate(BaseModel):
    """Request model for user registration."""

    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6)


class User(BaseModel):
    """User entity model."""

    id: str
    username: str
    created_at: datetime

    class Config:
        from_attributes = True


# --- Run Models ---

class RunCreate(BaseModel):
    """Request model for creating a new run."""

    title: str = Field(..., min_length=1, max_length=500)


class Run(BaseModel):
    """Run entity model."""

    id: str
    user_id: str
    title: str
    status: Literal["active", "paused", "completed", "failed", "awaiting_confirmation", "interrupted"] = "active"
    created_at: datetime
    total_tokens: int = 0

    class Config:
        from_attributes = True


class RunUpdate(BaseModel):
    """Request model for updating a run."""

    title: Optional[str] = None
    status: Optional[Literal["active", "paused", "completed", "failed", "awaiting_confirmation", "interrupted"]] = None


# --- Approval Models ---

class Approval(BaseModel):
    """Approval entity model for command execution."""

    command_hash: str
    run_id: str
    command_text: str
    approved: int = 0  # 0 = pending, 1 = approved, -1 = denied

    class Config:
        from_attributes = True


class ApprovalResponse(BaseModel):
    """Request model for responding to an approval."""

    approved: bool

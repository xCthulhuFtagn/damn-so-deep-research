"""
Run management routes.

CRUD operations for research runs.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.api.dependencies import get_current_user
from backend.persistence.database import DatabaseService, get_db_service
from backend.persistence.models import Run, RunCreate, RunUpdate, User

logger = logging.getLogger(__name__)

router = APIRouter()


class RunResponse(BaseModel):
    """Response model for run data."""

    id: str
    title: str
    status: str
    created_at: str
    total_tokens: int


class RunListResponse(BaseModel):
    """Response model for list of runs."""

    runs: List[RunResponse]
    total: int


@router.get("", response_model=RunListResponse)
async def list_runs(
    current_user: User = Depends(get_current_user),
    db: DatabaseService = Depends(get_db_service),
):
    """
    List all runs for the current user.
    """
    runs = await db.get_user_runs(current_user.id)

    return RunListResponse(
        runs=[
            RunResponse(
                id=r.id,
                title=r.title,
                status=r.status,
                created_at=r.created_at.isoformat(),
                total_tokens=r.total_tokens,
            )
            for r in runs
        ],
        total=len(runs),
    )


@router.post("", response_model=RunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    run_data: RunCreate,
    current_user: User = Depends(get_current_user),
    db: DatabaseService = Depends(get_db_service),
):
    """
    Create a new research run.
    """
    logger.info(f"Creating run for user {current_user.id}: {run_data.title[:50]}")

    run = await db.create_run(current_user.id, run_data.title)

    return RunResponse(
        id=run.id,
        title=run.title,
        status=run.status,
        created_at=run.created_at.isoformat(),
        total_tokens=run.total_tokens,
    )


@router.get("/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: DatabaseService = Depends(get_db_service),
):
    """
    Get a specific run by ID.
    """
    run = await db.get_run(run_id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    # Check ownership
    if run.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this run",
        )

    return RunResponse(
        id=run.id,
        title=run.title,
        status=run.status,
        created_at=run.created_at.isoformat(),
        total_tokens=run.total_tokens,
    )


@router.patch("/{run_id}", response_model=RunResponse)
async def update_run(
    run_id: str,
    update_data: RunUpdate,
    current_user: User = Depends(get_current_user),
    db: DatabaseService = Depends(get_db_service),
):
    """
    Update a run's title or status.
    """
    run = await db.get_run(run_id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    if run.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to modify this run",
        )

    updated = await db.update_run(
        run_id,
        title=update_data.title,
        status=update_data.status,
    )

    return RunResponse(
        id=updated.id,
        title=updated.title,
        status=updated.status,
        created_at=updated.created_at.isoformat(),
        total_tokens=updated.total_tokens,
    )


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: DatabaseService = Depends(get_db_service),
):
    """
    Delete a run.
    """
    run = await db.get_run(run_id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    if run.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this run",
        )

    await db.delete_run(run_id)
    logger.info(f"Deleted run {run_id}")

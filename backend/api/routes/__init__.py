"""
API routes package.
"""

from fastapi import APIRouter

from backend.api.routes import auth, runs, research, approvals

# Create main router
api_router = APIRouter()

# Include sub-routers
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(runs.router, prefix="/runs", tags=["runs"])
api_router.include_router(research.router, prefix="/research", tags=["research"])
api_router.include_router(approvals.router, prefix="/approvals", tags=["approvals"])

__all__ = ["api_router"]

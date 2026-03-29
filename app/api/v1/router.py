"""API v1 router — aggregates all endpoint routers."""
from fastapi import APIRouter

from api.v1.endpoints.health import router as health_router
from api.v1.endpoints.report import router as report_router

router = APIRouter()
router.include_router(health_router)
router.include_router(report_router)

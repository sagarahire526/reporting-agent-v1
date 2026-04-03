"""API v1 router — aggregates all endpoint routers."""
from fastapi import APIRouter

from api.v1.endpoints.health import router as health_router
from api.v1.endpoints.sse_report import router as sse_report_router

router = APIRouter()
router.include_router(health_router)
router.include_router(sse_report_router)

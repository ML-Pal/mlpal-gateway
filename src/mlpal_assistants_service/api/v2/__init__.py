"""API v2 router (universal Anthropic-Messages endpoint + curated catalog)."""

from fastapi import APIRouter

from mlpal_assistants_service.api.v2.catalog import router as catalog_router
from mlpal_assistants_service.api.v2.feedback import router as feedback_router
from mlpal_assistants_service.api.v2.messages import router as messages_router

router = APIRouter()
router.include_router(messages_router, prefix="/messages", tags=["Messages v2"])
router.include_router(catalog_router, tags=["Catalog v2"])
router.include_router(feedback_router, tags=["Feedback v2"])

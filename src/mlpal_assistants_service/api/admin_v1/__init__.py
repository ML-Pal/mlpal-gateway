"""Management / control-plane API at `/admin/v1`.

The canonical home for control-plane operations — issuing and managing keys +
their policies/budgets, and operational admin (cache invalidation, model pause).
Kept separate from the inference surface (OpenAI-wire `/v1/*`, Anthropic-wire
`/v2/messages`) so the "one API for your app teams" is inference-only and
administration is a distinct, clearly-scoped surface the SDK targets via
`client.admin.*`.

These reuse the same handlers as the legacy `/v1/keys` and `/v1/admin` routes,
which remain mounted for backward compatibility. See docs/API_SURFACE.md.
"""

from fastapi import APIRouter

from mlpal_assistants_service.api.v1.admin import router as admin_ops_router
from mlpal_assistants_service.api.v1.keys import router as keys_router

router = APIRouter()
router.include_router(keys_router, prefix="/keys", tags=["Management: Keys"])
# admin_ops paths are already /cache/* and /models/{tag}/pause — mount without an
# extra prefix so they read as /admin/v1/cache/invalidate, not /admin/v1/admin/...
router.include_router(admin_ops_router, tags=["Management: Admin"])

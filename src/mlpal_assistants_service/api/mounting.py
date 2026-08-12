"""API composition root — one place that decides the public route surface.

The design principle: a path version denotes a contract revision, never a wire
dialect. So the whole data plane lives under `/v1`, and the two wires are told
apart by RESOURCE, not version:

  * `POST /v1/messages`          — Anthropic-wire (native, universal core)
  * `POST /v1/chat/completions`  — OpenAI-wire, plus /v1/embeddings, /v1/images,
                                   /v1/audio/* (these modalities have no place in
                                   the Anthropic Messages wire, so v1 is their home)
  * `GET  /v1/catalog`, `POST /v1/feedback`, `/v1/usage/*` — MLPal surfaces
  * `/admin/v1/*` — control plane, versioned INDEPENDENTLY of the data plane

`/v2` is reserved for a genuine future breaking revision of the whole surface.

`/v1/messages` is the universal translating core in EVERY deployment — managed
and self-hosted serve the identical canonical surface, so clients (yodex, the
SDK) need no per-deployment path logic. Two transitional seams remain:

  * `settings.serve_legacy_v2_aliases` (managed default True): keeps the
    historical `/v2/{messages,catalog,feedback}` paths answering — same
    handlers, deprecated — until live consumers (yodex) finish moving to /v1
    and alias traffic drains to zero. The OSS build scrubs this to False:
    nothing is mounted under /v2 there.
  * `settings.enable_bedrock_mantle_messages` (default False): mounts the
    Bedrock-mantle Claude-Code passthrough at the scoped `/mantle/v1/messages`.
    Prod usage_logs showed zero mantle traffic (30d, 2026-08); it no longer
    owns /v1/messages anywhere and exists only behind this explicit opt-in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from mlpal_assistants_service.core.config import Settings


def mount_api(app: FastAPI, settings: Settings) -> None:
    """Attach every router to `app` per the versioning policy above."""
    from mlpal_assistants_service.api.admin_v1 import router as admin_v1_router
    from mlpal_assistants_service.api.v1 import router as v1_router
    from mlpal_assistants_service.api.v1.feed import router as feed_router
    from mlpal_assistants_service.api.v2.catalog import router as catalog_router
    from mlpal_assistants_service.api.v2.feedback import router as feedback_router
    from mlpal_assistants_service.api.v2.messages import router as universal_messages_router

    v1 = settings.api_v1_prefix  # "/v1"

    # OpenAI-wire modalities + models + usage + legacy key mgmt (no messages).
    app.include_router(v1_router, prefix=v1)
    # The canonical native-inference surface — identical in every deployment.
    app.include_router(universal_messages_router, prefix=f"{v1}/messages", tags=["Messages"])
    # MLPal curation surfaces, canonical under /v1.
    app.include_router(catalog_router, prefix=v1, tags=["Catalog"])
    # Public feed: lets other gateways subscribe to this deployment's catalog.
    app.include_router(feed_router, prefix=v1, tags=["Catalog"])
    app.include_router(feedback_router, prefix=v1, tags=["Feedback"])
    # Control plane, independently versioned.
    app.include_router(admin_v1_router, prefix="/admin/v1")

    if settings.serve_legacy_v2_aliases:
        # Same handlers at the historical paths — remove once alias traffic
        # (tracked per-path in usage_logs cc_metadata.api) drains to zero.
        app.include_router(
            universal_messages_router, prefix="/v2/messages", tags=["Messages (deprecated /v2)"]
        )
        app.include_router(catalog_router, prefix="/v2", tags=["Catalog (deprecated /v2)"])
        app.include_router(feedback_router, prefix="/v2", tags=["Feedback (deprecated /v2)"])

    if settings.enable_bedrock_mantle_messages:
        # Imported here (not at module top) so the self-hosted build can omit
        # the Bedrock-mantle module entirely without breaking mounting.
        try:
            from mlpal_assistants_service.api.v1.messages import router as bedrock_messages_router
        except ImportError as e:
            raise RuntimeError(
                "MLPAL_ENABLE_BEDROCK_MANTLE_MESSAGES=true but the Bedrock-mantle "
                "module is not part of this build (it is excluded from the "
                "self-hosted distribution). Unset the flag."
            ) from e

        app.include_router(
            bedrock_messages_router, prefix="/mantle/v1/messages", tags=["Messages (mantle)"]
        )

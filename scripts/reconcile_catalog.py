#!/usr/bin/env python
"""Reconcile the model registry + pricing against the curated feed.

Feed = desired state; the DB converges (insert / update / soft-retire),
scoped to feed-owned rows (operator `local` models are never touched), with
effective-dated pricing. Idempotent — safe to run on every boot.

  python scripts/reconcile_catalog.py                    # bundled catalog/*.json
  python scripts/reconcile_catalog.py --registry-url URL --pricing-url URL

This replaces the old hardcoded seed_model_registry.py / seed_model_pricing.py:
the model set is now data (catalog/registry.json, catalog/pricing.json), and a
refresh is a data pull, not a code change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import urllib.request
from pathlib import Path

import mlpal_assistants_service
from mlpal_assistants_service.db.session import session_context
from mlpal_assistants_service.services.catalog_sync import reconcile

CATALOG_DIR = Path(mlpal_assistants_service.__file__).resolve().parent / "catalog"


def _load(name: str, url: str | None) -> list[dict]:
    if url:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 — operator-supplied
            return json.load(resp)
    return json.loads((CATALOG_DIR / name).read_text())


async def _run(args: argparse.Namespace) -> None:
    registry = _load("registry.json", args.registry_url)
    pricing = _load("pricing.json", args.pricing_url)
    print(f"[reconcile] feed: {len(registry)} models, {len(pricing)} prices")
    async with session_context() as session:
        summary = await reconcile(session, registry, pricing)
    print(f"[reconcile] {summary}")


def main() -> None:
    p = argparse.ArgumentParser(description="Reconcile model registry + pricing from the feed.")
    p.add_argument("--registry-url", help="Fetch registry.json from a URL instead of the bundled copy.")
    p.add_argument("--pricing-url", help="Fetch pricing.json from a URL instead of the bundled copy.")
    asyncio.run(_run(p.parse_args()))


if __name__ == "__main__":
    main()

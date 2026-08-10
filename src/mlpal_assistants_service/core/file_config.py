"""File-based configuration layer (config/gateway.yaml).

Env vars stay the primary operational interface; the YAML file carries
documented defaults an operator can edit without touching the environment.
Read once at import and cached — settings that must change at runtime (like the
capture toggle) layer a Redis override on top (see services/capture.py).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# repo root / config/gateway.yaml — overridable for tests and containers.
# parents: [0]=core [1]=mlpal_assistants_service [2]=src [3]=repo root
_DEFAULT_PATH = Path(__file__).resolve().parents[3] / "config" / "gateway.yaml"


@lru_cache(maxsize=1)
def load_file_config() -> dict[str, Any]:
    """Parse gateway.yaml; missing or invalid file degrades to {} with a log
    line (file config is a defaults layer, never a boot requirement)."""
    path = Path(os.environ.get("MLPAL_CONFIG_FILE", str(_DEFAULT_PATH)))
    try:
        data = yaml.safe_load(path.read_text())
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:  # noqa: BLE001 — a bad config file must not crash boot
        logger.warning("Could not parse %s: %s — using defaults", path, e)
        return {}


def file_config_section(section: str) -> dict[str, Any]:
    value = load_file_config().get(section)
    return value if isinstance(value, dict) else {}

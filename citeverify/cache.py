"""Tiny JSON file cache for API and LLM responses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import Settings


def _key(*parts: str) -> str:
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return digest[:32]


def _path(settings: Settings, namespace: str, key: str) -> Path:
    return settings.cache_dir / namespace / f"{_key(key)}.json"


def read_cache(settings: Settings, namespace: str, key: str) -> dict[str, Any] | None:
    path = _path(settings, namespace, key)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_cache(
    settings: Settings, namespace: str, key: str, value: dict[str, Any]
) -> None:
    path = _path(settings, namespace, key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        # A cache failure must never break the analysis.
        pass

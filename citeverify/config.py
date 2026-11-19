"""Configuration loaded from environment variables and .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _path_from_env(name: str, default: str) -> Path:
    value = os.getenv(name, "").strip()
    path = Path(value) if value else ROOT / default
    if not path.is_absolute():
        path = ROOT / path
    return path


@dataclass(frozen=True)
class Settings:
    llm_api_key: str | None
    llm_model: str
    llm_base_url: str | None
    crossref_mailto: str
    cache_dir: Path
    demo_report_path: Path
    gold_set_path: Path

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def user_agent(self) -> str:
        return f"CiteVerify/0.1 (mailto:{self.crossref_mailto})"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    api_key = os.getenv("LLM_API_KEY", "").strip() or None
    base_url = os.getenv("LLM_BASE_URL", "").strip() or None
    # Gemini's OpenAI-compatible endpoint does not serve OpenAI model names, and
    # older Gemini models get retired. Keep the fallback valid for the endpoint
    # that is actually configured instead of defaulting to gpt-4o-mini.
    default_model = (
        "gemini-3.5-flash-lite"
        if base_url and "generativelanguage.googleapis.com" in base_url
        else "gpt-4o-mini"
    )
    model = os.getenv("LLM_MODEL", default_model).strip() or default_model
    mailto = os.getenv("CROSSREF_MAILTO", "team@example.com").strip() or "team@example.com"

    return Settings(
        llm_api_key=api_key,
        llm_model=model,
        llm_base_url=base_url,
        crossref_mailto=mailto,
        cache_dir=_path_from_env("CITEVERIFY_CACHE_DIR", ".cache/citeverify"),
        demo_report_path=_path_from_env(
            "CITEVERIFY_DEMO_REPORT", "data/demo/demo_report.json"
        ),
        gold_set_path=_path_from_env("CITEVERIFY_GOLD_SET", "data/gold_set.json"),
    )

"""Thin, retrying JSON wrapper around an OpenAI-compatible chat model."""

from __future__ import annotations

import json
import re
import time
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from .config import Settings

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - only relevant before install
    OpenAI = None  # type: ignore[assignment]

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """Raised when no API key is configured or the SDK is missing."""


class LLMError(RuntimeError):
    """Raised when the model cannot return valid structured output."""


RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}

RETRYABLE_MARKERS = (
    "rate limit",
    "rate_limit",
    "quota",
    "timeout",
    "timed out",
    "overloaded",
    "temporarily unavailable",
    "service unavailable",
)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def is_retryable_error(exc: Exception) -> bool:
    """True for transport, quota, and rate-limit errors worth backing off on."""
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status in RETRYABLE_STATUS:
        return True
    message = str(exc).casefold()
    return any(marker in message for marker in RETRYABLE_MARKERS)


def parse_json_object(text: str) -> dict:
    text = _strip_code_fence(text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object.")
    return value


class LLMClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self.settings.llm_api_key and OpenAI is not None)

    def _get_client(self):
        if not self.available:
            raise LLMUnavailable(
                "Set LLM_API_KEY in .env, or use the demo report. "
                "New-paper analysis needs an LLM."
            )
        if self._client is None:
            kwargs = {"api_key": self.settings.llm_api_key, "timeout": 90.0}
            if self.settings.llm_base_url:
                kwargs["base_url"] = self.settings.llm_base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        max_attempts: int = 3,
    ) -> T:
        """Ask the model for JSON and validate it against a Pydantic schema."""
        client = self._get_client()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        last_error: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            raw = ""
            try:
                response = client.chat.completions.create(
                    model=self.settings.llm_model,
                    messages=messages,
                    temperature=0,
                    response_format={"type": "json_object"},
                )
                raw = response.choices[0].message.content or ""
                data = parse_json_object(raw)
                return schema.model_validate(data)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_error = exc
                messages.extend(
                    [
                        {"role": "assistant", "content": raw or "{}"},
                        {
                            "role": "user",
                            "content": (
                                "That output was invalid. Return ONLY a valid JSON "
                                f"object matching the requested schema. Error: {exc}"
                            ),
                        },
                    ]
                )
            except Exception as exc:  # API/network errors
                last_error = exc
                # Free tiers rate-limit hard; backing off beats losing a verdict.
                if is_retryable_error(exc) and attempt < max_attempts:
                    time.sleep(min(2 ** (attempt - 1), 8))
                    continue
                break

        raise LLMError(f"The model did not return usable JSON: {last_error}")

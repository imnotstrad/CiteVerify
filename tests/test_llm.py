from pathlib import Path

from pydantic import BaseModel

from citeverify.config import Settings
from citeverify.llm import LLMClient, is_retryable_error, parse_json_object


class _Out(BaseModel):
    ok: bool = False


def _settings() -> Settings:
    return Settings(
        llm_api_key="test-key",
        llm_model="test-model",
        llm_base_url=None,
        crossref_mailto="team@example.com",
        cache_dir=Path(".cache/test"),
        demo_report_path=Path("data/demo/demo_report.json"),
        gold_set_path=Path("data/gold_set.json"),
    )


def _stub_client(fail_first: Exception | None = None):
    calls = {"n": 0}

    class _Message:
        content = '{"ok": true}'

    class _Choice:
        message = _Message()

    class _Response:
        choices = [_Choice()]

    class _Completions:
        def create(self, **kwargs):
            calls["n"] += 1
            if fail_first is not None and calls["n"] == 1:
                raise fail_first
            return _Response()

    class _Chat:
        completions = _Completions()

    class _Stub:
        chat = _Chat()

    return _Stub(), calls


def test_is_retryable_error_detects_rate_limits_and_status_codes():
    quota = RuntimeError("429 You exceeded your current quota")
    status = RuntimeError("boom")
    status.status_code = 503
    auth = RuntimeError("401 invalid api key")

    assert is_retryable_error(quota)
    assert is_retryable_error(status)
    assert not is_retryable_error(auth)


def test_parse_json_object_survives_code_fence():
    assert parse_json_object('```json\n{"ok": true}\n```') == {"ok": True}


def test_rate_limit_error_is_retried(monkeypatch):
    client = LLMClient(_settings())
    stub, calls = _stub_client(RuntimeError("429 rate limit reached"))
    monkeypatch.setattr(client, "_get_client", lambda: stub)
    monkeypatch.setattr("citeverify.llm.time.sleep", lambda seconds: None)

    result = client.complete_json(system="s", user="u", schema=_Out)

    assert result.ok is True
    assert calls["n"] == 2


def test_non_retryable_error_fails_fast(monkeypatch):
    client = LLMClient(_settings())
    stub, calls = _stub_client(RuntimeError("401 invalid api key"))
    monkeypatch.setattr(client, "_get_client", lambda: stub)
    monkeypatch.setattr("citeverify.llm.time.sleep", lambda seconds: None)

    try:
        client.complete_json(system="s", user="u", schema=_Out)
    except Exception:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected failure")

    assert calls["n"] == 1

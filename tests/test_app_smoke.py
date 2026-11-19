"""Smoke-test the Streamlit screens against a recording fake of `streamlit`.

This does not render pixels. It runs each screen's code, and checks the wiring that
matters: arrows disabled at the ends, "Try a new PDF" on every card, the PDF button
only on the last card, and the reading screen moving on to the cards.
"""

from __future__ import annotations

import importlib
import sys
import types
from unittest.mock import MagicMock

import pytest

from citeverify.config import get_settings
from citeverify.report import load_demo_report


class FakeState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


def _make_streamlit():
    st = MagicMock(name="streamlit")
    st.session_state = FakeState()
    st.buttons = []
    st.downloads = []

    def columns(spec, **_kwargs):
        count = spec if isinstance(spec, int) else len(spec)
        return [MagicMock() for _ in range(count)]

    def button(label, **kwargs):
        st.buttons.append((label, kwargs))
        return False

    def download_button(label, **kwargs):
        st.downloads.append((label, kwargs))
        return False

    st.columns.side_effect = columns
    st.tabs.side_effect = lambda labels: [MagicMock() for _ in labels]
    st.button.side_effect = button
    st.download_button.side_effect = download_button
    st.text_input.return_value = ""
    st.text_area.return_value = ""
    st.toggle.return_value = False
    st.checkbox.return_value = False
    st.file_uploader.return_value = None
    st.empty.return_value = MagicMock()
    return st


@pytest.fixture()
def app(monkeypatch):
    fake = _make_streamlit()
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    # Third-party packages that may be missing in a minimal environment.
    for name in ("pymupdf", "httpx", "tenacity", "rapidfuzz", "rapidfuzz.fuzz", "openai"):
        try:
            importlib.import_module(name)
        except ImportError:
            stub = types.ModuleType(name)
            if name == "httpx":
                stub.HTTPError = Exception
            if name == "tenacity":
                stub.retry = lambda *a, **k: (lambda fn: fn)
                stub.retry_if_exception_type = lambda *a, **k: None
                stub.stop_after_attempt = lambda *a, **k: None
                stub.wait_exponential = lambda *a, **k: None
            if name == "rapidfuzz":
                stub.fuzz = types.ModuleType("rapidfuzz.fuzz")
            monkeypatch.setitem(sys.modules, name, stub)
    for mod in [m for m in sys.modules if m == "app" or m.startswith("citeverify.")]:
        if mod == "citeverify.config":
            continue
        monkeypatch.delitem(sys.modules, mod, raising=False)
    module = importlib.import_module("app")
    module.init_state()
    return module, fake


def _labels(fake):
    return [label for label, _ in fake.buttons]


def _button(fake, key):
    matches = [kw for _label, kw in fake.buttons if kw.get("key") == key]
    assert matches, f"no button with key {key!r}"
    return matches[-1]


def _open_demo(module, fake, index):
    st = module.st
    st.session_state.report = module.load_demo_report(get_settings().demo_report_path)
    st.session_state.report_mode = "demo"
    st.session_state.claim_index = index
    fake.buttons.clear()
    fake.downloads.clear()
    module.main()


def _total(module):
    return len(load_demo_report(get_settings().demo_report_path).results)


def test_home_screen_renders(app):
    module, fake = app
    module.main()
    labels = _labels(fake)
    assert "Research claims" in labels
    assert any("demo" in label.lower() for label in labels)
    fake.file_uploader.assert_called()


def test_first_card_greys_out_left_arrow_only(app):
    module, fake = app
    _open_demo(module, fake, 0)
    assert _button(fake, "previous_claim")["disabled"] is True
    assert _button(fake, "next_claim")["disabled"] is False


def test_middle_card_has_both_arrows_enabled(app):
    module, fake = app
    _open_demo(module, fake, 4)
    assert _button(fake, "previous_claim")["disabled"] is False
    assert _button(fake, "next_claim")["disabled"] is False


def test_last_card_greys_out_right_arrow_and_offers_pdf(app):
    module, fake = app
    _open_demo(module, fake, _total(module) - 1)
    assert _button(fake, "next_claim")["disabled"] is True
    assert _button(fake, "previous_claim")["disabled"] is False
    assert "Create PDF with suggested fixes" in [label for label, _ in fake.downloads]


def test_pdf_button_absent_before_the_last_card(app):
    module, fake = app
    _open_demo(module, fake, 0)
    assert fake.downloads == []


def test_every_card_has_try_new_pdf(app):
    module, fake = app
    for index in range(_total(module)):
        _open_demo(module, fake, index)
        assert "Try a new PDF" in _labels(fake), f"missing on card {index + 1}"


def test_both_themes_render(app):
    module, fake = app
    for dark in (False, True):
        module.st.session_state.dark_mode = dark
        _open_demo(module, fake, 0)


def test_go_home_resets_and_clears_uploader(app):
    module, fake = app
    _open_demo(module, fake, 3)
    before = module.st.session_state.uploader_nonce
    module.go_home()
    state = module.st.session_state
    assert state.report is None and state.claim_index == 0
    assert state.stage == "home"
    assert state.uploader_nonce == before + 1


def test_empty_paste_is_rejected_and_paste_starts_reading(app):
    module, fake = app
    module.st.session_state.home_pasted = "   "
    module.on_analyze_text()
    assert module.st.session_state.stage == "home"
    assert module.st.session_state.home_error
    module.st.session_state.home_pasted = "Some paper text [1]."
    module.on_analyze_text()
    assert module.st.session_state.stage == "reading"
    assert module.st.session_state.pending["kind"] == "text"


def test_reading_stage_runs_pipeline_and_shows_cards(app, monkeypatch):
    module, fake = app
    # Use the app's own (reloaded) model classes so pydantic sees matching types.
    demo = module.load_demo_report(get_settings().demo_report_path)
    claims = [r.claim for r in demo.results]
    refs = [r.reference for r in demo.results if r.reference]
    paper = types.SimpleNamespace(title="Paper", pages=[1, 2], filename="p.pdf")

    monkeypatch.setattr(module, "extract_text", lambda text, filename: paper)
    monkeypatch.setattr(
        module, "extract_claims_and_references", lambda p, llm, max_claims: ("Paper", claims, refs)
    )
    monkeypatch.setattr(module, "resolve_all", lambda r, s: r)

    def fake_verify(cl, rf, llm, progress=None):
        for i, c in enumerate(cl, start=1):
            if progress:
                progress(i, len(cl), c)
        return demo.results

    monkeypatch.setattr(module, "verify_claims", fake_verify)

    state = module.st.session_state
    state.stage = "reading"
    state.pending = {"kind": "text", "text": "x", "max_claims": 6}
    module.main()

    assert not state.analysis_error, state.analysis_error
    assert state.report is not None and state.report_mode == "live"
    assert state.stage == "home" and state.pending is None
    assert state.verify_seconds is not None
    fake.rerun.assert_called()


def test_reading_failure_shows_friendly_401_and_retry(app, monkeypatch):
    module, fake = app
    paper = types.SimpleNamespace(title="Paper", pages=[], filename="p.pdf")
    monkeypatch.setattr(module, "extract_text", lambda text, filename: paper)

    def boom(*args, **kwargs):
        raise RuntimeError("Error code: 401 - Incorrect API key provided")

    monkeypatch.setattr(module, "extract_claims_and_references", boom)
    state = module.st.session_state
    state.stage = "reading"
    state.pending = {"kind": "text", "text": "x"}
    module.main()
    assert "LLM_BASE_URL" in state.analysis_error
    fake.buttons.clear()
    module.main()  # second run shows the error screen
    assert "← Try another paper" in _labels(fake)

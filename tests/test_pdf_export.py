from __future__ import annotations

import io

import pytest

from citeverify.config import get_settings
from citeverify.models import Claim, ClaimResult, Confidence, Reference, Report, Verdict
from citeverify.report import load_demo_report


def _pdf_text(data: bytes) -> str:
    pypdf = pytest.importorskip("pypdf")
    pytest.importorskip("reportlab")
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_pdf_for_demo_report_has_fixes_and_corrections():
    pytest.importorskip("reportlab")
    from citeverify.pdf_export import build_fixes_pdf

    report = load_demo_report(get_settings().demo_report_path)
    data = build_fixes_pdf(report)
    assert data.startswith(b"%PDF")
    text = _pdf_text(data)
    assert "Suggested fixes" in text
    assert "Claim 1" in text
    assert "Reference list corrections" in text
    assert "Vaswani, A., et al." in text


def test_pdf_with_no_claims_and_odd_characters():
    pytest.importorskip("reportlab")
    from citeverify.pdf_export import build_fixes_pdf

    empty = Report(paper_title="Empty <paper> & co")
    assert build_fixes_pdf(empty).startswith(b"%PDF")

    odd = Report(
        paper_title="Greek α β & <tags>",
        results=[
            ClaimResult(
                claim=Claim(id="c1", text="Effect of α on β <b>bold</b> & more", citation_marker="[1]"),
                reference=Reference(id="r1", raw="Doe, J. (2020). A study. Journal of Things, 5(1), 1-10."),
                verdict=Verdict.UNSUPPORTED,
                confidence=Confidence.LOW,
                reason="Source says nothing about it.",
                suggested_fix="Remove the claim or cite a different source.",
            )
        ],
    )
    data = build_fixes_pdf(odd)
    text = _pdf_text(data)
    assert "Suggested fix" in text
    assert "Remove the claim" in text

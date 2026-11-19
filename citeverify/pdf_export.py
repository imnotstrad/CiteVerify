"""Build a PDF report with the suggested fixes for each claim and reference.

Uses reportlab (pure Python wheel). The import is lazy so the rest of the app still
runs if the package is missing; callers should catch PDFUnavailable.

Text is limited to the Windows-1252 character set that the built-in PDF fonts cover.
Anything outside it (for example Greek letters) is replaced with "?".
"""

from __future__ import annotations

import io
import re
from xml.sax.saxutils import escape

from .citefix import correct_citation
from .models import ClaimResult, Report, Verdict
from .report import CONFIDENCE_LABELS, VERDICT_LABELS


class PDFUnavailable(RuntimeError):
    """Raised when reportlab is not installed."""


def _safe(text: str | None) -> str:
    """Escape for reportlab's mini-markup and keep to characters the base fonts have."""
    cleaned = (text or "").encode("cp1252", "replace").decode("cp1252")
    return escape(" ".join(cleaned.split()))


def _italics(text: str) -> str:
    """Turn the *italic* markers from correct_citation() into <i> tags."""
    return re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)


def _needs_attention(result: ClaimResult) -> bool:
    return result.verdict != Verdict.SUPPORTED or bool(result.suggested_fix)


def build_fixes_pdf(report: Report) -> bytes:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            HRFlowable,
            KeepTogether,
            Paragraph,
            SimpleDocTemplate,
            Spacer,
        )
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise PDFUnavailable(
            "PDF export needs the 'reportlab' package. Add it to requirements.txt."
        ) from exc

    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontSize=10, leading=14, alignment=TA_LEFT)
    small = ParagraphStyle("small", parent=body, fontSize=8.5, leading=12, textColor=colors.HexColor("#555555"))
    h1 = ParagraphStyle("h1", parent=base["Title"], fontSize=20, leading=24, alignment=TA_LEFT, spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=base["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=6)
    h3 = ParagraphStyle("h3", parent=base["Heading3"], fontSize=11, spaceBefore=10, spaceAfter=3)
    quote = ParagraphStyle("quote", parent=body, leftIndent=10, textColor=colors.HexColor("#134E4A"), fontName="Helvetica-Oblique")
    fix = ParagraphStyle("fix", parent=body, leftIndent=10, textColor=colors.HexColor("#7A2E0E"))

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"CiteVerify: suggested fixes for {report.paper_title}"[:200].encode("cp1252", "replace").decode("cp1252"),
        author="CiteVerify",
    )

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#777777"))
        canvas.drawString(20 * mm, 10 * mm, "CiteVerify: evidence for human review, not a final verdict.")
        canvas.drawRightString(A4[0] - 20 * mm, 10 * mm, f"Page {document.page}")
        canvas.restoreState()

    story: list = []
    story.append(Paragraph("Suggested fixes", h1))
    story.append(Paragraph(_safe(report.paper_title), body))
    story.append(
        Paragraph(
            f"Generated {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}"
            + (f" &middot; {_safe(report.filename)}" if report.filename else ""),
            small,
        )
    )
    story.append(Spacer(1, 6))
    story.append(HRFlowable(width="100%", color=colors.HexColor("#CCCCCC")))

    # Summary
    summary = report.summary
    parts = [
        f"{VERDICT_LABELS[v]}: {summary[v.value]}" for v in Verdict if summary.get(v.value)
    ]
    story.append(Paragraph("Summary", h2))
    story.append(
        Paragraph(
            f"{summary['total']} claim(s) checked. " + ("; ".join(parts) + "." if parts else ""),
            body,
        )
    )

    # Claims
    story.append(Paragraph("Claims", h2))
    if not report.results:
        story.append(Paragraph("No claims were found in this report.", body))
    for index, result in enumerate(report.results, start=1):
        verdict = VERDICT_LABELS.get(result.verdict, result.verdict.value)
        confidence = CONFIDENCE_LABELS.get(result.confidence, result.confidence.value)
        block = [
            Paragraph(f"Claim {index}: {_safe(verdict)} ({_safe(confidence)} confidence)", h3),
            Paragraph(f"<b>Claim:</b> {_safe(result.claim.text)}", body),
        ]
        source = result.source_title or "Unknown source"
        if result.source_year:
            source += f" ({result.source_year})"
        block.append(Paragraph(f"<b>Source:</b> {_safe(source)}", body))
        if result.claim.citation_marker:
            block.append(Paragraph(f"<b>Cited as:</b> {_safe(result.claim.citation_marker)}", small))
        if result.evidence_quote:
            block.append(Paragraph(f"&ldquo;{_safe(result.evidence_quote)}&rdquo;", quote))
        if result.reason:
            block.append(Paragraph(f"<b>Why:</b> {_safe(result.reason)}", body))
        if result.suggested_fix:
            block.append(Paragraph(f"<b>Suggested fix:</b> {_safe(result.suggested_fix)}", fix))
        elif _needs_attention(result):
            block.append(
                Paragraph("<b>Suggested fix:</b> none proposed. Review this claim against the source.", fix)
            )
        if result.flags:
            block.append(
                Paragraph("<b>Flags:</b> " + _safe(", ".join(f.replace("_", " ") for f in result.flags)), small)
            )
        if result.source_url:
            block.append(Paragraph(_safe(result.source_url), small))
        story.append(KeepTogether(block))

    # Reference corrections
    corrections = []
    seen: set[str] = set()
    for result in report.results:
        ref = result.reference
        if not ref or not (ref.raw or "").strip() or ref.raw in seen:
            continue
        seen.add(ref.raw)
        fixed = correct_citation(ref.raw)
        if fixed["issues"] or fixed["corrected"] != ref.raw:
            corrections.append(fixed)

    if corrections:
        story.append(Paragraph("Reference list corrections (APA 7)", h2))
        story.append(
            Paragraph(
                "Automatic suggestions. Check each against the original source before using it.",
                small,
            )
        )
        for fixed in corrections:
            block = [
                Paragraph(f"<b>Original:</b> {_safe(fixed['original'])}", body),
                Paragraph(f"<b>Suggested:</b> {_italics(_safe(fixed['corrected']))}", body),
            ]
            for issue in fixed["issues"]:
                block.append(Paragraph(f"&bull; {_safe(issue)}", small))
            block.append(Spacer(1, 6))
            story.append(KeepTogether(block))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()

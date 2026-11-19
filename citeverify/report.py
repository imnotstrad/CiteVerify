"""Report assembly and export helpers."""

from __future__ import annotations

import json
from pathlib import Path

from .citefix import correct_citation
from .models import ClaimResult, Confidence, Report, Verdict
from .reliability import reliability_for_reference

VERDICT_LABELS = {
    Verdict.SUPPORTED: "Supported",
    Verdict.PARTIALLY_SUPPORTED: "Partially supported",
    Verdict.UNSUPPORTED: "Unsupported",
    Verdict.CONTRADICTED: "Contradicted",
    Verdict.UNVERIFIABLE: "Unverifiable",
}

CONFIDENCE_LABELS = {
    Confidence.HIGH: "High",
    Confidence.MEDIUM: "Medium",
    Confidence.LOW: "Low",
}


def build_report(
    paper_title: str,
    filename: str | None,
    results: list[ClaimResult],
    mode: str = "live",
) -> Report:
    return Report(
        paper_title=paper_title,
        filename=filename,
        results=results,
        mode=mode,
        limitations=[
            "Evidence is compared at abstract level by default; full-text checks are future work.",
            "Citation-to-reference matching is heuristic and can miss unusual citation styles.",
            "Confidence labels are a rubric, not a calibrated probability.",
            "This is evidence for human review, not a final verdict on a paper.",
        ],
    )


def load_demo_report(path: Path) -> Report:
    if not path.exists():
        raise FileNotFoundError(
            f"Demo report not found at {path}. Run: python scripts/make_demo.py"
        )
    return Report.model_validate_json(path.read_text(encoding="utf-8"))


def report_to_markdown(report: Report) -> str:
    lines: list[str] = [
        f"# CiteVerify report: {report.paper_title}",
        "",
        f"Generated: {report.generated_at.isoformat()}",
        f"Mode: {report.mode}",
        "",
        "## Summary",
        "",
    ]
    for key, value in report.summary.items():
        if key in {"total", "flagged"}:
            lines.append(f"- **{key.title()}**: {value}")
        else:
            try:
                label = VERDICT_LABELS[Verdict(key)]
            except ValueError:
                label = key
            lines.append(f"- **{label}**: {value}")
    lines.extend(["", "## Claims", ""])

    for index, result in enumerate(report.results, start=1):
        verdict = VERDICT_LABELS.get(result.verdict, result.verdict.value)
        confidence = CONFIDENCE_LABELS.get(result.confidence, result.confidence.value)
        lines.extend(
            [
                f"### {index}. {verdict}",
                "",
                f"**Claim:** {result.claim.text}",
                "",
                f"**Citation:** {result.claim.citation_marker or 'unknown'}",
                "",
                f"**Source:** {result.source_title or 'Unknown source'}"
                + (f" ({result.source_year})" if result.source_year else ""),
                "",
                f"**Confidence:** {confidence}",
                "",
            ]
        )
        if result.evidence_quote:
            lines.extend([f"> {result.evidence_quote}", ""])
        if result.reason:
            lines.extend([f"**Why:** {result.reason}", ""])
        if result.suggested_fix:
            lines.extend([f"**Suggested fix:** {result.suggested_fix}", ""])
        if result.source_url:
            lines.extend([f"**Source link:** {result.source_url}", ""])
        if result.flags:
            lines.extend([f"**Flags:** {', '.join(result.flags)}", ""])
        if result.reference:
            analysis = reliability_for_reference(result.reference)
            lines.extend(
                [
                    f"**Source reliability:** {analysis['score']}/100 ({analysis['grade']}, "
                    "abstract and metadata only)",
                    "",
                ]
            )
            if (result.reference.raw or "").strip():
                lines.extend(
                    [
                        f"**Suggested citation (APA 7):** "
                        f"{correct_citation(result.reference.raw)['corrected']}",
                        "",
                    ]
                )

    if report.limitations:
        lines.extend(["## Limitations", ""])
        lines.extend(f"- {item}" for item in report.limitations)
        lines.append("")

    return "\n".join(lines)


def report_to_json(report: Report) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False)

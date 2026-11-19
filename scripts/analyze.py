"""Run the CiteVerify pipeline on a PDF from the command line.

Usage:
    python scripts/analyze.py path/to/paper.pdf
    python scripts/analyze.py paper.pdf --max-claims 12 --out-dir data/runs
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from citeverify.config import get_settings
from citeverify.extract import extract_claims_and_references
from citeverify.ingest import extract_pdf
from citeverify.llm import LLMClient
from citeverify.models import Verdict
from citeverify.report import build_report, report_to_json, report_to_markdown
from citeverify.resolve import resolve_all
from citeverify.verify import verify_claims


def _slug(value: str, limit: int = 60) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (cleaned or "paper")[:limit]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether a paper's citations support its claims."
    )
    parser.add_argument("pdf", type=Path, help="Path to the paper PDF")
    parser.add_argument("--max-claims", type=int, default=8)
    parser.add_argument("--out-dir", type=Path, default=Path(".cache/runs"))
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"File not found: {args.pdf}")
        return 2

    settings = get_settings()
    llm = LLMClient(settings)
    if not llm.available:
        print("No LLM_API_KEY configured. Add it to .env or use the demo report.")
        return 2

    started = time.perf_counter()

    def elapsed() -> str:
        return f"{time.perf_counter() - started:6.1f}s"

    print(f"[{elapsed()}] ingesting {args.pdf.name}")
    paper = extract_pdf(args.pdf.read_bytes(), args.pdf.name)
    print(f"[{elapsed()}]   title      : {paper.title}")
    print(f"[{elapsed()}]   pages      : {len(paper.pages)}")
    print(f"[{elapsed()}]   references : {len(paper.references_text)} chars")

    print(f"[{elapsed()}] extracting claims and references (LLM)")
    title, claims, references = extract_claims_and_references(
        paper, llm, max_claims=args.max_claims
    )
    print(f"[{elapsed()}]   title   : {title}")
    print(f"[{elapsed()}]   claims  : {len(claims)}")
    print(f"[{elapsed()}]   refs    : {len(references)}")

    print(f"[{elapsed()}] resolving sources (Crossref/OpenAlex)")

    def on_resolved(index: int, total: int, reference) -> None:
        mark = "ok " if reference.resolved else "-- "
        print(f"[{elapsed()}]   {mark}{index}/{total} {(reference.title or reference.raw)[:70]}")

    references = resolve_all(references, settings, progress=on_resolved)
    resolved = sum(1 for reference in references if reference.resolved)
    print(f"[{elapsed()}]   resolved {resolved}/{len(references)}")

    print(f"[{elapsed()}] verifying claims (LLM, 1 call each)")
    results = verify_claims(claims, references, llm)

    report = build_report(title, paper.filename, results, mode="live")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = _slug(title)
    md_path = args.out_dir / f"{stem}.md"
    json_path = args.out_dir / f"{stem}.json"
    md_path.write_text(report_to_markdown(report), encoding="utf-8")
    json_path.write_text(report_to_json(report), encoding="utf-8")

    summary = report.summary
    print(f"\n[{elapsed()}] done\n")
    print("summary")
    for verdict in Verdict:
        print(f"  {verdict.value:20s} {summary[verdict.value]}")
    print(f"  {'total':20s} {summary['total']}")
    print(f"  {'flagged':20s} {summary['flagged']}")

    anchored = sum(1 for result in results if result.evidence_quote)
    abstained = sum(1 for result in results if result.verdict == Verdict.UNVERIFIABLE)
    rate = (abstained / len(results) * 100) if results else 0.0
    print("\nhealth")
    print(f"  quotes anchored      {anchored}/{len(results)}")
    print(f"  abstention rate      {rate:.0f}%")

    reasons: dict[str, int] = {}
    for result in results:
        for flag in result.flags:
            reasons[flag] = reasons.get(flag, 0) + 1
    if reasons:
        print("  flags")
        for flag, count in sorted(reasons.items(), key=lambda item: -item[1]):
            print(f"    {flag:20s} {count}")

    print(f"\nwrote {md_path}")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Evaluate the verifier against the hand-labelled gold set.

This is a small sanity check, not a benchmark. It uses the abstracts stored in
data/gold_set.json, so it does not depend on Crossref/OpenAlex at evaluation time.

Run:
    python scripts/evaluate.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from citeverify.config import get_settings
from citeverify.doi import doi_url
from citeverify.llm import LLMClient, LLMUnavailable
from citeverify.models import Claim, Reference
from citeverify.verify import verify_claim

VERDICT_LABELS = {
    "supported": "Supported",
    "partially_supported": "Partial",
    "unsupported": "Unsupported",
    "contradicted": "Contradicted",
    "unverifiable": "Unverifiable",
}


def main() -> int:
    settings = get_settings()
    llm = LLMClient(settings)
    if not llm.available:
        print("LLM_API_KEY is not configured. Copy .env.example to .env and add a key.")
        return 2

    gold_path = settings.gold_set_path
    if not gold_path.exists():
        print(f"Gold set not found at {gold_path}. Run: python scripts/make_demo.py")
        return 2

    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    cases = gold.get("cases", [])
    rows: list[dict] = []
    correct = 0
    quote_ok = 0

    for case in cases:
        source = case["source"]
        reference = Reference(
            id="source",
            raw=f"{source['title']} ({source['year']})",
            doi=source.get("doi"),
            title=source.get("title"),
            authors=source.get("authors", []),
            year=source.get("year"),
            url=source.get("url") or doi_url(source.get("doi")),
            abstract=source.get("abstract"),
            resolved=True,
            provider="gold_set",
        )
        claim_data = case["claim"]
        claim = Claim(
            id=claim_data.get("id", case["id"]),
            text=claim_data["text"],
            section=claim_data.get("section", "Unknown"),
            citation_marker=claim_data.get("citation_marker", ""),
            reference_id="source",
        )
        result = verify_claim(claim, reference, llm)
        expected = case["expected_verdict"]
        is_correct = result.verdict.value == expected
        correct += int(is_correct)

        expected_quote = (case.get("expected_evidence_contains") or "").strip()
        has_quote = bool(
            expected_quote
            and result.evidence_quote
            and expected_quote.casefold() in result.evidence_quote.casefold()
        )
        quote_ok += int(has_quote)

        rows.append(
            {
                "id": case["id"],
                "claim": claim.text,
                "expected": expected,
                "got": result.verdict.value,
                "correct": is_correct,
                "quote_ok": has_quote,
                "confidence": result.confidence.value,
                "evidence_quote": result.evidence_quote,
                "reason": result.reason,
            }
        )
        print(
            f"{case['id']:>8}  {VERDICT_LABELS.get(expected, expected):<13} "
            f"-> {VERDICT_LABELS.get(result.verdict.value, result.verdict.value):<13} "
            f"{'OK' if is_correct else 'MISS'}"
        )

    total = len(rows)
    accuracy = correct / total if total else 0.0
    quote_rate = quote_ok / total if total else 0.0
    output = {
        "total": total,
        "accuracy": round(accuracy, 4),
        "quote_validity": round(quote_rate, 4),
        "rows": rows,
    }
    out_path = ROOT / "data" / "gold_set_results.json"
    out_path.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print(f"Accuracy:       {correct}/{total} ({accuracy:.0%})")
    print(f"Quote validity: {quote_ok}/{total} ({quote_rate:.0%})")
    print(f"Wrote {out_path}")
    return 0 if accuracy >= 0.8 else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except LLMUnavailable as exc:
        print(exc)
        raise SystemExit(2)

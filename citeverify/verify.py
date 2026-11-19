"""Source-grounded claim verification."""

from __future__ import annotations

import re
from typing import Callable

from pydantic import BaseModel, Field

from .doi import doi_url
from .llm import LLMClient
from .models import (
    FLAG_MISSING_DOI,
    FLAG_NO_ABSTRACT,
    FLAG_QUOTE_NOT_FOUND,
    FLAG_RETRACTED,
    FLAG_UNRESOLVED,
    Claim,
    ClaimResult,
    Confidence,
    Reference,
    Verdict,
)

SYSTEM_PROMPT = """You are a forensic citation verifier.
Use ONLY the SOURCE TEXT provided. Do not use outside knowledge.
Your job is to decide whether the source supports the claim, not whether the claim
is true in general. Return only a JSON object."""

VERIFICATION_PROMPT = """CLAIM:
{claim}

CITATION MARKER:
{marker}

SOURCE TITLE:
{source_title}

SOURCE TEXT:
{source_text}

Decide whether the SOURCE TEXT supports the CLAIM.
Return JSON:
{{
  "verdict": "supported | partially_supported | unsupported | contradicted | unverifiable",
  "confidence": "high | medium | low",
  "evidence_quote": "verbatim quote from SOURCE TEXT, or empty string",
  "reason": "one or two sentences explaining the verdict",
  "suggested_fix": "one actionable fix for the citing sentence, or null"
}}

Rubric:
- supported: the source directly states the claim or a near-equivalent statement.
- partially_supported: the source supports only part of the claim, a weaker version,
  or a different population/condition.
- unsupported: the source does not address the claim, or the claim is broader than
  the evidence.
- contradicted: the source explicitly states the opposite.
- unverifiable: the source text is insufficient to decide.

Rules:
- evidence_quote must be copied verbatim from SOURCE TEXT. Never paraphrase it.
- If you cannot find a supporting or contradicting quote, use unverifiable.
- high confidence requires a direct quote. Medium means indirect support.
- Do not use the paper title as evidence. Use the source text.
"""

RETRY_SUFFIX = """

Your previous quote could not be found verbatim in SOURCE TEXT.
Try again. Either return a quote that appears exactly in SOURCE TEXT, or set
verdict to "unverifiable" and evidence_quote to "".
"""


class VerificationError(RuntimeError):
    """Raised when verification cannot be completed."""


class VerificationPayload(BaseModel):
    verdict: Verdict
    confidence: Confidence
    evidence_quote: str = ""
    reason: str = ""
    suggested_fix: str | None = None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def quote_in_source(quote: str | None, source_text: str | None) -> bool:
    if not quote or not source_text:
        return False
    needle = _norm(quote).strip("\"'“”‘’ ")
    haystack = _norm(source_text)
    if not needle:
        return False
    if needle in haystack:
        return True
    # Allow an ellipsis to join two exact fragments.
    parts = [part.strip() for part in re.split(r"\.\.\.|…", needle) if part.strip()]
    return len(parts) > 1 and all(part in haystack for part in parts)


def _flags(*values: str | None) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _unverifiable(
    claim: Claim,
    reference: Reference | None,
    reason: str,
    flags: list[str],
    confidence: Confidence = Confidence.LOW,
) -> ClaimResult:
    return ClaimResult(
        claim=claim,
        reference=reference,
        verdict=Verdict.UNVERIFIABLE,
        confidence=confidence,
        evidence_quote=None,
        reason=reason,
        suggested_fix=None,
        source_url=(reference.url if reference else None)
        or (doi_url(reference.doi) if reference else None),
        source_title=reference.title if reference else None,
        source_year=reference.year if reference else None,
        flags=flags,
    )


def verify_claim(
    claim: Claim,
    reference: Reference | None,
    llm: LLMClient,
) -> ClaimResult:
    if reference is None:
        return _unverifiable(
            claim,
            None,
            "No reference could be matched to this citation marker.",
            [FLAG_UNRESOLVED],
        )

    base_flags = []
    if not reference.doi:
        base_flags.append(FLAG_MISSING_DOI)
    if reference.is_retracted:
        base_flags.append(FLAG_RETRACTED)

    if not reference.resolved:
        return _unverifiable(
            claim,
            reference,
            "The cited source could not be resolved through Crossref or OpenAlex.",
            _flags(*base_flags, FLAG_UNRESOLVED),
        )

    source_text = (reference.abstract or "").strip()
    if len(source_text) < 80:
        return _unverifiable(
            claim,
            reference,
            "No usable abstract was found. This claim needs the full source text.",
            _flags(*base_flags, FLAG_NO_ABSTRACT),
        )

    prompt = VERIFICATION_PROMPT.format(
        claim=claim.text,
        marker=claim.citation_marker,
        source_title=reference.title or "Unknown source",
        source_text=source_text,
    )

    try:
        payload = llm.complete_json(
            system=SYSTEM_PROMPT,
            user=prompt,
            schema=VerificationPayload,
        )
        quote = (payload.evidence_quote or "").strip() or None
        if payload.verdict != Verdict.UNVERIFIABLE and not quote_in_source(
            quote, source_text
        ):
            payload = llm.complete_json(
                system=SYSTEM_PROMPT,
                user=prompt + RETRY_SUFFIX,
                schema=VerificationPayload,
            )
            quote = (payload.evidence_quote or "").strip() or None
    except Exception as exc:
        return _unverifiable(
            claim,
            reference,
            f"Verification failed for this claim: {exc}",
            _flags(*base_flags),
            confidence=Confidence.LOW,
        )

    if payload.verdict == Verdict.UNVERIFIABLE:
        if quote and not quote_in_source(quote, source_text):
            quote = None
        return ClaimResult(
            claim=claim,
            reference=reference,
            verdict=Verdict.UNVERIFIABLE,
            confidence=payload.confidence,
            evidence_quote=quote,
            reason=(payload.reason or "The source text is insufficient to decide.").strip(),
            suggested_fix=payload.suggested_fix,
            source_url=doi_url(reference.doi) or reference.url,
            source_title=reference.title,
            source_year=reference.year,
            flags=_flags(*base_flags),
        )

    if not quote or not quote_in_source(quote, source_text):
        return _unverifiable(
            claim,
            reference,
            "The model produced a verdict but could not anchor it to a verbatim quote.",
            _flags(*base_flags, FLAG_QUOTE_NOT_FOUND),
        )

    return ClaimResult(
        claim=claim,
        reference=reference,
        verdict=payload.verdict,
        confidence=payload.confidence,
        evidence_quote=quote,
        reason=(payload.reason or "").strip(),
        suggested_fix=payload.suggested_fix,
        source_url=doi_url(reference.doi) or reference.url,
        source_title=reference.title,
        source_year=reference.year,
        flags=_flags(*base_flags),
    )


def verify_claims(
    claims: list[Claim],
    references: list[Reference],
    llm: LLMClient,
    progress: Callable[[int, int, Claim], None] | None = None,
) -> list[ClaimResult]:
    by_id = {reference.id: reference for reference in references}
    results: list[ClaimResult] = []
    total = len(claims)
    for index, claim in enumerate(claims, start=1):
        result = verify_claim(claim, by_id.get(claim.reference_id), llm)
        results.append(result)
        if progress:
            progress(index, total, claim)
    return results

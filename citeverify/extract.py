"""Extract cited claims and references from a paper."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from .doi import doi_url, normalize_doi
from .llm import LLMClient
from .models import Claim, PaperText, Reference


class ExtractionError(RuntimeError):
    """Raised when no usable claims could be extracted."""


class ExtractedReference(BaseModel):
    raw: str = ""
    doi: str | None = None
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None


class ExtractedClaim(BaseModel):
    text: str
    section: str = "Unknown"
    citation_marker: str = ""
    reference_index: int | None = None
    page: int | None = None


class ExtractionPayload(BaseModel):
    paper_title: str = ""
    references: list[ExtractedReference] = Field(default_factory=list)
    claims: list[ExtractedClaim] = Field(default_factory=list)


SYSTEM_PROMPT = """You extract citation-checkable claims from research papers.
You must return only a JSON object. Do not add commentary.
Be conservative: a claim must be a factual statement with an in-text citation."""

EXTRACTION_PROMPT = """Extract the paper title, the reference list, and up to {max_claims} factual
claims that have in-text citations.

Return JSON with exactly this shape:
{{
  "paper_title": "string",
  "references": [
    {{
      "raw": "full reference text",
      "doi": "DOI or null",
      "title": "paper title or null",
      "authors": ["Author One", "Author Two"],
      "year": 2020
    }}
  ],
  "claims": [
    {{
      "text": "exact sentence from the paper",
      "section": "Abstract / Introduction / Discussion / etc.",
      "citation_marker": "[12] or (Smith, 2020)",
      "reference_index": 12,
      "page": 3
    }}
  ]
}}

Rules:
- Keep references in the same order as the paper's reference list.
- reference_index is 1-based and must point into that list. Use null if you cannot match it.
- Only include claims that have a citation. Skip uncited background statements.
- Prefer claims from the abstract, introduction, discussion, and conclusion.
- Do not invent references, DOIs, pages, or claims.
- If the reference section is missing, return an empty references array and still extract claims.

PAPER TITLE (if visible):
{paper_title}

PAPER TEXT:
{paper_text}

REFERENCE SECTION:
{reference_text}
"""


def _trim(value: str | None, limit: int = 5000) -> str:
    return (value or "").strip()[:limit]


def _numeric_reference_id(marker: str, references: list[Reference]) -> str | None:
    match = re.search(r"\[(\d+)\]", marker or "")
    if not match:
        return None
    index = int(match.group(1)) - 1
    if 0 <= index < len(references):
        return references[index].id
    return None


def extract_claims_and_references(
    paper: PaperText,
    llm: LLMClient,
    max_claims: int = 8,
) -> tuple[str, list[Claim], list[Reference]]:
    if not llm.available:
        from .llm import LLMUnavailable

        raise LLMUnavailable(
            "Set LLM_API_KEY in .env to analyze a new paper. "
            "The demo report works without a key."
        )

    prompt = EXTRACTION_PROMPT.format(
        max_claims=max_claims,
        paper_title=paper.title,
        paper_text=_trim(paper.full_text, 30000),
        reference_text=_trim(paper.references_text or paper.full_text[-15000:], 15000),
    )
    payload = llm.complete_json(
        system=SYSTEM_PROMPT,
        user=prompt,
        schema=ExtractionPayload,
    )

    references: list[Reference] = []
    for index, item in enumerate(payload.references):
        doi = normalize_doi(item.doi) or normalize_doi(item.raw)
        references.append(
            Reference(
                id=f"ref_{index + 1}",
                raw=item.raw.strip(),
                doi=doi,
                title=(item.title or "").strip() or None,
                authors=[author.strip() for author in item.authors if author.strip()],
                year=item.year,
                url=doi_url(doi),
            )
        )

    claims: list[Claim] = []
    seen: set[str] = set()
    for item in payload.claims:
        text = re.sub(r"\s+", " ", item.text).strip()
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())

        reference_id: str | None = None
        if item.reference_index is not None:
            index = item.reference_index - 1
            if 0 <= index < len(references):
                reference_id = references[index].id
        if reference_id is None:
            reference_id = _numeric_reference_id(item.citation_marker, references)

        claims.append(
            Claim(
                id=f"claim_{len(claims) + 1}",
                text=text,
                section=(item.section or "Unknown").strip(),
                citation_marker=(item.citation_marker or "").strip(),
                reference_id=reference_id,
                page=item.page,
            )
        )
        if len(claims) >= max_claims:
            break

    if not claims:
        raise ExtractionError(
            "No cited claims were found. Try a paper with clearly numbered citations, "
            "or paste the text and reference list explicitly."
        )

    title = (payload.paper_title or paper.title).strip() or paper.title
    return title, claims, references

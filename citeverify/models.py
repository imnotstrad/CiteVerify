"""Pydantic models shared by the pipeline, UI, and evaluation script."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, computed_field


class Verdict(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
    UNVERIFIABLE = "unverifiable"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Flag names used across the pipeline and UI.
FLAG_RETRACTED = "retracted"
FLAG_UNRESOLVED = "unresolved"
FLAG_NO_ABSTRACT = "no_abstract"
FLAG_MISSING_DOI = "missing_doi"
FLAG_QUOTE_NOT_FOUND = "quote_not_found"


class PageText(BaseModel):
    number: int
    text: str


class PaperText(BaseModel):
    title: str
    pages: list[PageText]
    references_text: str = ""
    filename: str | None = None

    @property
    def full_text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text.strip())


class Reference(BaseModel):
    id: str
    raw: str
    doi: str | None = None
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    url: str | None = None
    abstract: str | None = None
    is_retracted: bool = False
    resolved: bool = False
    provider: str | None = None
    match_score: float | None = None


class Claim(BaseModel):
    id: str
    text: str
    section: str = "Unknown"
    citation_marker: str
    reference_id: str | None = None
    page: int | None = None


class ClaimResult(BaseModel):
    claim: Claim
    reference: Reference | None = None
    verdict: Verdict
    confidence: Confidence
    evidence_quote: str | None = None
    reason: str
    suggested_fix: str | None = None
    source_url: str | None = None
    source_title: str | None = None
    source_year: int | None = None
    flags: list[str] = Field(default_factory=list)


class Report(BaseModel):
    paper_title: str
    filename: str | None = None
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    results: list[ClaimResult] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    mode: str = "live"

    @computed_field
    @property
    def summary(self) -> dict[str, int]:
        counts = {verdict.value: 0 for verdict in Verdict}
        for result in self.results:
            counts[result.verdict.value] += 1
        counts["total"] = len(self.results)
        counts["flagged"] = sum(1 for result in self.results if result.flags)
        return counts

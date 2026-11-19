"""DOI normalization helpers."""

from __future__ import annotations

import re

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)


def normalize_doi(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    candidate = PREFIX_RE.sub("", candidate)
    match = DOI_RE.search(candidate)
    if not match:
        return None
    doi = match.group(0)
    doi = doi.rstrip(".,;")
    # Drop an unmatched closing parenthesis that often comes from prose.
    if doi.count("(") < doi.count(")"):
        doi = doi.rstrip(")")
    return doi.lower()


def extract_doi(text: str | None) -> str | None:
    if not text:
        return None
    return normalize_doi(text)


def doi_url(doi: str | None) -> str | None:
    normalized = normalize_doi(doi)
    return f"https://doi.org/{normalized}" if normalized else None

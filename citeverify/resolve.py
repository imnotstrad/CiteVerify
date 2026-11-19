"""Resolve references against Crossref and OpenAlex."""

from __future__ import annotations

import html
import re
from typing import Callable
from urllib.parse import quote, urlencode

import httpx
from rapidfuzz import fuzz
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from .cache import read_cache, write_cache
from .config import Settings
from .doi import doi_url, extract_doi, normalize_doi
from .models import Reference

CROSSREF_WORK = "https://api.crossref.org/works/{doi}"
CROSSREF_SEARCH = "https://api.crossref.org/works"
OPENALEX_WORK = "https://api.openalex.org/works/doi:{doi}"


class ResolutionError(RuntimeError):
    """Raised when a DOI cannot be resolved through the available APIs."""


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=2),
    retry=retry_if_exception_type(httpx.HTTPError),
    reraise=True,
)
def _get_json(
    url: str,
    settings: Settings,
    params: dict | None = None,
) -> dict:
    key = url + ("?" + urlencode(params) if params else "")
    cached = read_cache(settings, "http", key)
    if cached is not None:
        return cached

    headers = {
        "User-Agent": settings.user_agent,
        "Accept": "application/json",
    }
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

    if not isinstance(data, dict):
        raise ResolutionError("Unexpected API response.")
    write_cache(settings, "http", key, data)
    return data


def _first(value) -> str | None:
    if isinstance(value, list) and value:
        return str(value[0]).strip() or None
    if isinstance(value, str):
        return value.strip() or None
    return None


def _clean_jats(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:8000] or None


def _crossref_year(message: dict) -> int | None:
    parts = (message.get("issued") or {}).get("date-parts") or []
    if parts and parts[0] and parts[0][0]:
        try:
            return int(parts[0][0])
        except (TypeError, ValueError):
            return None
    return None


def _crossref_authors(message: dict) -> list[str]:
    authors: list[str] = []
    for author in message.get("author") or []:
        name = " ".join(
            part for part in [author.get("given"), author.get("family")] if part
        ).strip()
        if name:
            authors.append(name)
    return authors


def _reconstruct_abstract(inverted_index: dict | None) -> str | None:
    if not inverted_index:
        return None
    positions: list[tuple[int, str]] = []
    for word, indexes in inverted_index.items():
        for index in indexes or []:
            positions.append((int(index), word))
    if not positions:
        return None
    return " ".join(word for _, word in sorted(positions))[:8000]


def _openalex_authors(work: dict) -> list[str]:
    authors: list[str] = []
    for authorship in work.get("authorships") or []:
        name = (authorship.get("author") or {}).get("display_name")
        if name:
            authors.append(name)
    return authors


def crossref_search(title: str, settings: Settings) -> tuple[str | None, float]:
    query = re.sub(r"\s+", " ", title).strip()[:350]
    if len(query) < 8:
        return None, 0.0
    data = _get_json(
        CROSSREF_SEARCH,
        settings,
        params={"query.bibliographic": query, "rows": 5},
    )
    items = (data.get("message") or {}).get("items") or []
    best_doi: str | None = None
    best_score = 0.0
    for item in items:
        item_title = _first(item.get("title"))
        if not item_title or not item.get("DOI"):
            continue
        score = fuzz.token_set_ratio(query, item_title)
        if score > best_score:
            best_score = float(score)
            best_doi = normalize_doi(item.get("DOI"))
    if best_doi and best_score >= 88:
        return best_doi, best_score
    return None, best_score


def _merge_crossref(reference: Reference, data: dict, doi: str) -> Reference:
    message = data.get("message") or {}
    merged = reference.model_copy(
        update={
            "doi": doi,
            "title": _first(message.get("title")) or reference.title,
            "authors": _crossref_authors(message) or reference.authors,
            "year": _crossref_year(message) or reference.year,
            "url": doi_url(doi),
            "abstract": _clean_jats(message.get("abstract")) or reference.abstract,
            "provider": "crossref",
            "resolved": True,
        }
    )
    return merged


def _merge_openalex(reference: Reference, work: dict, doi: str) -> Reference:
    title = work.get("title") or work.get("display_name")
    merged = reference.model_copy(
        update={
            "doi": doi,
            "title": title or reference.title,
            "authors": _openalex_authors(work) or reference.authors,
            "year": work.get("publication_year") or reference.year,
            "url": doi_url(doi),
            "abstract": _reconstruct_abstract(work.get("abstract_inverted_index"))
            or reference.abstract,
            "is_retracted": bool(work.get("is_retracted")),
            "provider": "openalex",
            "resolved": True,
        }
    )
    return merged


def resolve_reference(reference: Reference, settings: Settings) -> Reference:
    doi = normalize_doi(reference.doi) or extract_doi(reference.raw)
    match_score: float | None = None

    if not doi:
        search_text = reference.title or reference.raw
        try:
            doi, match_score = crossref_search(search_text, settings)
        except Exception:
            doi, match_score = None, None

    if not doi:
        return reference.model_copy(update={"resolved": False})

    crossref: Reference | None = None
    openalex: Reference | None = None

    try:
        data = _get_json(
            CROSSREF_WORK.format(doi=quote(doi, safe="")),
            settings,
        )
        crossref = _merge_crossref(reference, data, doi)
    except Exception:
        crossref = None

    try:
        data = _get_json(OPENALEX_WORK.format(doi=doi), settings)
        openalex = _merge_openalex(reference, data, doi)
    except Exception:
        openalex = None

    if crossref is None and openalex is None:
        return reference.model_copy(
            update={"doi": doi, "url": doi_url(doi), "resolved": False}
        )

    merged = openalex or crossref or reference
    if crossref and openalex:
        merged = merged.model_copy(
            update={
                "title": crossref.title or openalex.title,
                "authors": crossref.authors or openalex.authors,
                "year": crossref.year or openalex.year,
                "abstract": openalex.abstract or crossref.abstract,
                "is_retracted": openalex.is_retracted,
                "provider": "crossref+openalex",
            }
        )

    return merged.model_copy(
        update={
            "doi": doi,
            "url": doi_url(doi),
            "resolved": True,
            "match_score": match_score,
        }
    )


def resolve_all(
    references: list[Reference],
    settings: Settings,
    progress: Callable[[int, int, Reference], None] | None = None,
) -> list[Reference]:
    resolved: list[Reference] = []
    total = len(references)
    for index, reference in enumerate(references, start=1):
        try:
            item = resolve_reference(reference, settings)
        except Exception:
            item = reference.model_copy(update={"resolved": False})
        resolved.append(item)
        if progress:
            progress(index, total, item)
    return resolved


def check_doi(value: str, settings: Settings) -> Reference:
    doi = normalize_doi(value)
    if not doi:
        raise ResolutionError("That does not look like a DOI.")
    reference = Reference(
        id="doi_check",
        raw=value,
        doi=doi,
        url=doi_url(doi),
    )
    resolved = resolve_reference(reference, settings)
    if not resolved.resolved:
        raise ResolutionError(
            "Crossref and OpenAlex could not resolve that DOI. "
            "Check the DOI or your connection."
        )
    return resolved

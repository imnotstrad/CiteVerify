"""PDF and pasted-text ingestion."""

from __future__ import annotations

import re

import pymupdf

from .models import PageText, PaperText

REFERENCE_HEADING_RE = re.compile(
    r"(?im)^\s*(?:\d+[\.\s]+)?(references|bibliography|works cited|literature cited)\s*:?\s*$"
)


def _clean_title(value: str | None) -> str | None:
    if not value:
        return None
    title = re.sub(r"\s+", " ", value).strip()
    if not title or title.lower() in {"untitled", "unknown", "microsoft word"}:
        return None
    return title[:220]


def _guess_title(pages: list[PageText], metadata_title: str | None) -> str:
    cleaned = _clean_title(metadata_title)
    if cleaned:
        return cleaned
    if pages:
        for line in pages[0].text.splitlines():
            candidate = _clean_title(line)
            if candidate and len(candidate) > 8:
                return candidate
    return "Untitled paper"


def find_references_text(full_text: str) -> str:
    matches = list(REFERENCE_HEADING_RE.finditer(full_text))
    if not matches:
        return ""
    return full_text[matches[-1].start() :].strip()


def extract_pdf(data: bytes, filename: str | None = None) -> PaperText:
    doc = pymupdf.open(stream=data, filetype="pdf")
    try:
        pages = [
            PageText(number=index + 1, text=page.get_text("text"))
            for index, page in enumerate(doc)
        ]
        metadata_title = (doc.metadata or {}).get("title")
    finally:
        doc.close()

    title = _guess_title(pages, metadata_title)
    reference_text = find_references_text("\n\n".join(page.text for page in pages))
    return PaperText(
        title=title,
        pages=pages,
        references_text=reference_text,
        filename=filename,
    )


def extract_text(text: str, filename: str | None = None, title: str | None = None) -> PaperText:
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Pasted text is empty.")
    page = PageText(number=1, text=cleaned)
    guessed = _clean_title(title)
    if not guessed:
        first_line = next((line for line in cleaned.splitlines() if line.strip()), "")
        guessed = _clean_title(first_line) or "Pasted paper"
    return PaperText(
        title=guessed,
        pages=[page],
        references_text=find_references_text(cleaned),
        filename=filename,
    )

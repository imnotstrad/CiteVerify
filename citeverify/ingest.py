"""PDF and pasted-text ingestion."""

from __future__ import annotations

import re

import pymupdf

from .models import PageText, PaperText

REFERENCE_HEADING_RE = re.compile(
    r"(?im)^\s*(?:\d+[\.\s]+)?(references|bibliography|works cited|literature cited)\s*:?\s*$"
)

# Text that shows up at the top of real PDFs but is never the paper title:
# arXiv licence banners, the rotated arXiv stamp, publisher copyright lines.
JUNK_TITLE_RE = re.compile(
    r"(provided proper attribution"
    r"|hereby grants permission"
    r"|reproduce the tables"
    r"|all rights reserved"
    r"|copyright\s*(?:©|\(c\))?\s*\d{4}"
    r"|^arxiv:\s*\d{4}\.\d{4,5})",
    re.IGNORECASE,
)

ARXIV_STAMP_RE = re.compile(r"^arxiv:\s*\d{4}\.\d{4,5}", re.IGNORECASE)


def _clean_title(value: str | None) -> str | None:
    if not value:
        return None
    title = re.sub(r"\s+", " ", value).strip()
    if not title or title.lower() in {"untitled", "unknown", "microsoft word"}:
        return None
    if JUNK_TITLE_RE.search(title):
        return None
    return title[:220]


def _normalize_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _metadata_matches_page(cleaned: str, page_text: str) -> bool:
    """Guard against junk PDF metadata by requiring it to appear on page 1."""
    key = _normalize_key(cleaned)
    if len(key) < 8:
        return False
    return key[:60] in _normalize_key(page_text)


def _layout_title(doc: pymupdf.Document) -> str | None:
    """Pick the title from page-1 typography, skipping stamps and banners."""
    try:
        page = doc[0]
        page_dict = page.get_text("dict")
    except Exception:
        return None

    candidates: list[tuple[float, float, str]] = []
    for block in page_dict.get("blocks", []):
        if block.get("type", 0) != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            text = "".join(span.get("text", "") for span in spans).strip()
            if len(text) < 4:
                continue
            direction = line.get("dir", (1.0, 0.0))
            if abs(float(direction[0]) - 1.0) > 0.15:
                continue  # rotated margin stamps
            if ARXIV_STAMP_RE.match(text) or JUNK_TITLE_RE.search(text):
                continue
            size = max((float(span.get("size", 0.0)) for span in spans), default=0.0)
            top = float(line.get("bbox", (0.0, 0.0, 0.0, 0.0))[1])
            candidates.append((size, top, text))

    if not candidates:
        return None

    biggest = max(size for size, _, _ in candidates)
    if biggest < 11.5:
        return None

    picked = [
        text
        for size, _, text in sorted(candidates, key=lambda item: item[1])
        if size >= biggest * 0.92
    ]
    return _clean_title(" ".join(picked))


def _guess_title(
    pages: list[PageText],
    metadata_title: str | None,
    layout_title: str | None = None,
) -> str:
    first_page = pages[0].text if pages else ""
    cleaned = _clean_title(metadata_title)

    # Publisher metadata is reliable only when the page actually contains it.
    if cleaned and _metadata_matches_page(cleaned, first_page):
        return cleaned
    if layout_title:
        return layout_title
    if cleaned:
        return cleaned
    for line in first_page.splitlines():
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
        layout_title = _layout_title(doc)
    finally:
        doc.close()

    title = _guess_title(pages, metadata_title, layout_title)
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

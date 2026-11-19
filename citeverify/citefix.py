"""Automatic citation correction: parse a messy reference and rewrite it in APA 7.

Pure Python, no LLM and no network. Heuristic: it reports what it could not find
rather than inventing missing details.
"""

from __future__ import annotations

import re

SMALL_WORDS = {
    "a", "an", "the", "and", "or", "of", "in", "on", "for", "to", "with", "at", "by", "from", "as",
}


def _initials(first: str) -> str:
    parts = re.findall(r"[A-Za-z][A-Za-z'\-]*\.?", first)
    out: list[str] = []
    for part in parts:
        # "J.A." style -> J. A.
        letters = (
            re.findall(r"[A-Za-z]", part)
            if re.fullmatch(r"(?:[A-Za-z]\.)+", part)
            else [part[0]]
        )
        out += [f"{letter.upper()}." for letter in letters]
    return " ".join(out)


def parse_authors(text: str) -> list[tuple[str, str]]:
    text = re.sub(r"\s*(?:&|\band\b)\s*", "; ", text.strip().rstrip(".,"))
    found = re.findall(
        r"([A-Z][\w'\-]+(?:\s[A-Z][\w'\-]+)?),\s*((?:[A-Z][\w.\-]*\s*)+)", text
    )
    if found:
        return [(last.strip(), _initials(first)) for last, first in found]
    parts = [p.split() for p in filter(None, (p.strip() for p in text.split(";")))]
    # If any name ends in an initial ("Lee A."), the list is written Surname-first.
    # Only real initials count ("A.", "JA"); short surnames like "He" or "Wu" do not.
    surname_first = any(
        len(w) >= 2 and re.fullmatch(r"(?:[A-Z]\.?){1,3}", w[-1]) for w in parts
    )
    authors: list[tuple[str, str]] = []
    for words in parts:
        if len(words) < 2:
            if words:
                authors.append((words[0], ""))
        elif surname_first:  # "Smith John" / "Lee A." -> Smith, J. / Lee, A.
            authors.append((words[0], _initials(" ".join(words[1:]))))
        else:  # "John A. Smith" -> Smith, J. A.
            authors.append((words[-1], _initials(" ".join(words[:-1]))))
    return authors


def to_sentence_case(title: str) -> str:
    words = title.split()
    alpha = [w for w in words if w[:1].isalpha()]
    if not alpha or sum(w[0].isupper() for w in alpha) / len(alpha) < 0.6:
        return title  # already sentence case
    out: list[str] = []
    capitalize_next = True
    for word in words:
        if word.isupper() and len(word) > 1:  # keep acronyms (AI, DNA)
            out.append(word)
        elif capitalize_next:
            out.append(word[0].upper() + word[1:].lower())
        else:
            out.append(word.lower())
        capitalize_next = word.endswith(":") or word.endswith("?")
    return " ".join(out)


def parse_citation(raw: str) -> dict:
    c: dict = {}
    raw = " ".join(raw.split())
    doi = re.search(
        r"(?:https?://(?:dx\.)?doi\.org/|doi:\s*)?(10\.\d{4,9}/[^\s]+)", raw, re.I
    )
    if doi:
        c["doi"] = doi.group(1).rstrip(".,")
        raw = raw.replace(doi.group(0), "").strip()
    match = re.search(r"\(?\b((?:19|20)\d{2})[a-z]?\)?", raw)
    if match:
        c["year"] = match.group(1)
        authors_part, rest = raw[: match.start()], raw[match.end():]
        # "Ashish Vaswani et al." means more authors exist that we do not know.
        stripped = re.sub(r"[,;]?\s*\bet\.?\s+al\b\.?", "", authors_part, flags=re.I)
        if stripped != authors_part:
            c["et_al"] = True
            authors_part = stripped
        if authors_part.strip(" ,.("):
            c["authors"] = parse_authors(authors_part)
        rest = rest.lstrip(" .,)")
        title_match = re.match(r"(.+?[.?!])\s+(.*)$", rest)
        if title_match:
            c["title"], rest = title_match.group(1).rstrip("."), title_match.group(2)
        else:
            c["title"], rest = rest.rstrip("."), ""
        pages = re.search(
            r"(\d+)\s*(?:\((\d+)\))?\s*,?\s*(?:pp?\.\s*)?(\d+)\s*[-–—]\s*(\d+)",
            rest,
        )
        if pages:
            c["volume"], c["issue"] = pages.group(1), pages.group(2)
            c["pages"] = f"{pages.group(3)}–{pages.group(4)}"
            rest = rest[: pages.start()]
        else:
            volume = re.search(r"(\d+)\s*(?:\((\d+)\))?\s*,?\s*$", rest.strip(" ."))
            if volume:
                c["volume"], c["issue"] = volume.group(1), volume.group(2)
                rest = rest[: volume.start()]
        journal = rest.strip(" .,")
        if journal:
            c["journal"] = journal
    else:
        c["title"] = raw
    return c


def title_case_journal(journal: str) -> str:
    return " ".join(
        w
        if (w.isupper() or w.lower() not in SMALL_WORDS) and w[:1].isupper()
        else (w.lower() if w.lower() in SMALL_WORDS else w.capitalize())
        for w in journal.split()
    )


def format_apa(c: dict) -> str:
    names = [f"{last}, {initials}".strip().rstrip(",") for last, initials in c.get("authors", [])]
    if len(names) == 0:
        authors = ""
    elif len(names) == 1:
        authors = names[0]
    elif len(names) <= 20:
        authors = ", ".join(names[:-1]) + ", & " + names[-1]
    else:
        authors = ", ".join(names[:19]) + ", ... " + names[-1]
    if c.get("et_al") and authors:
        authors += ", et al"
    authors = authors if authors.endswith(".") else authors + "."
    out = f"{authors} ({c.get('year', 'n.d.')}). {c.get('title', '[Missing title]')}."
    if c.get("journal"):
        out += f" *{c['journal']}*"
        if c.get("volume"):
            out += f", *{c['volume']}*"
            if c.get("issue"):
                out += f"({c['issue']})"
        if c.get("pages"):
            out += f", {c['pages']}"
        out += "."
    if c.get("doi"):
        out += f" https://doi.org/{c['doi']}"
    return out.strip()


def correct_citation(raw: str) -> dict:
    """Parse a messy citation, report missing info + formatting problems, return APA 7."""
    c = parse_citation(raw)
    issues: list[str] = []
    missing: list[str] = []

    for key, label in [
        ("authors", "author(s)"),
        ("year", "year"),
        ("title", "title"),
        ("journal", "journal/publisher"),
        ("volume", "volume"),
        ("pages", "page range"),
        ("doi", "DOI"),
    ]:
        if not c.get(key):
            missing.append(label)

    if c.get("et_al"):
        issues.append(
            'Only the first author is known ("et al."). APA 7 lists up to 20 authors '
            "in the reference list, so add the rest from the source."
        )
    if "title" in c:
        sentence = to_sentence_case(c["title"])
        if sentence != c["title"]:
            issues.append(f'Title should be sentence case: "{c["title"]}" -> "{sentence}"')
            c["title"] = sentence
    if "journal" in c:
        journal = title_case_journal(c["journal"])
        if journal != c["journal"]:
            issues.append(f'Journal name should be Title Case: "{c["journal"]}" -> "{journal}"')
            c["journal"] = journal
    if re.search(r"\band\b", raw.split("(")[0] if "(" in raw else raw[:80]) and len(
        c.get("authors", [])
    ) > 1:
        issues.append('Use "&" before the last author (APA 7).')
    if re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+,", raw[:60]) and c.get("authors"):
        issues.append("Authors should be written as Surname, Initials.")
    if re.search(r"\d+-\d+", raw) and c.get("pages"):
        issues.append("Page ranges should use an en dash (45–67), not a hyphen.")
    if c.get("doi") and "doi.org" not in raw:
        issues.append("DOI should be formatted as a https://doi.org/ link.")
    if "DOI" in missing:
        issues.append("Add a DOI if one exists (look up the title at crossref.org).")

    return {
        "original": raw,
        "parsed": c,
        "missing": missing,
        "issues": issues,
        "corrected": format_apa(c),
    }

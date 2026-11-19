"""Small text helpers shared by the evidence and reliability modules (stdlib only)."""

from __future__ import annotations

import re

STOPWORDS = set(
    """a an the and or but if of to in on at by for with from as is are was were be been being
this that these those it its they them their we our you your he she his her not no than then so such
can could may might will would should do does did has have had which who whom what when where how also
into over under between about after before during per via among within without""".split()
)


def stem(word: str) -> str:
    """Very light stemmer so 'increases' ~ 'increased' ~ 'increasing'."""
    for suffix in ("ing", "ed", "es", "s", "ly"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z\-']+", text.lower())
    return [stem(w) for w in words if w not in STOPWORDS and len(w) > 2]


def split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


def split_sentences(paragraph: str) -> list[str]:
    return [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z\"'(])", paragraph)
        if s.strip()
    ]

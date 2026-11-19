"""Lightweight local semantic retrieval for citation evidence.

The embedding model only ranks passages. It never assigns a citation verdict.
If the optional model cannot load (for example, offline on first run), a
small keyword-overlap fallback keeps the verifier usable.
"""

from __future__ import annotations

import re
from functools import lru_cache

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_STOP_WORDS = {
    "about", "after", "again", "against", "among", "also", "although", "and",
    "are", "because", "been", "before", "being", "between", "both", "could",
    "does", "during", "each", "from", "further", "have", "having", "into",
    "more", "most", "only", "other", "over", "same", "should", "some", "such",
    "than", "that", "their", "there", "these", "they", "this", "those",
    "through", "under", "very", "were", "what", "when", "where", "which",
    "while", "with", "would", "your",
}


@lru_cache(maxsize=1)
def _load_model():
    """Load once per process; importing this module never downloads a model."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def _passages(text: str, max_chars: int = 650) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    sentences: list[str] = []
    for paragraph in paragraphs or [text.strip()]:
        parts = re.split(r"(?<=[.!?])\s+", paragraph)
        for part in parts:
            part = re.sub(r"\s+", " ", part).strip()
            if not part:
                continue
            if len(part) <= max_chars:
                sentences.append(part)
            else:
                sentences.extend(
                    part[i : i + max_chars].strip()
                    for i in range(0, len(part), max_chars)
                    if part[i : i + max_chars].strip()
                )

    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _keyword_rank(query: str, passages: list[str], top_k: int) -> list[str]:
    def terms(value: str) -> set[str]:
        return {
            word for word in re.findall(r"[a-z0-9]{3,}", value.casefold())
            if word not in _STOP_WORDS
        }

    query_terms = terms(query)
    if not query_terms:
        return passages[:top_k]
    scored = []
    for index, passage in enumerate(passages):
        passage_terms = terms(passage)
        score = len(query_terms & passage_terms) / len(query_terms)
        scored.append((score, -index, passage))
    scored.sort(reverse=True)
    ranked = [item[2] for item in scored[:top_k] if item[0] > 0]
    return ranked or passages[:top_k]


def retrieve_passages(
    query: str,
    source_text: str,
    top_k: int = 4,
) -> tuple[list[str], str]:
    """Return the most relevant exact source passages and retrieval method."""
    passages = _passages(source_text)
    if not passages:
        return [], "none"

    try:
        model = _load_model()
        vectors = model.encode(
            [query, *passages],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        scores = vectors[1:] @ vectors[0]
        ranked_indices = sorted(
            range(len(passages)), key=lambda i: float(scores[i]), reverse=True
        )[:top_k]
        return [passages[i] for i in ranked_indices], "semantic"
    except Exception:
        # Keep analysis working if the optional package/model is unavailable.
        return _keyword_rank(query, passages, top_k), "keyword"

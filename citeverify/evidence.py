"""Evidence highlighting: find and mark the passages that best match a claim.

Pure Python, no LLM and no network. Runs in milliseconds even on a full paper.
"""

from __future__ import annotations

import html
import math
import re
from collections import Counter

from .textutil import split_paragraphs, split_sentences, stem, tokens

HEDGES = {
    "may",
    "might",
    "suggest",
    "suggests",
    "suggested",
    "possibly",
    "preliminary",
    "tentative",
}
CONTRAST = {
    "however",
    "no significant",
    "did not",
    "failed to",
    "contrary",
    "in contrast",
    "no evidence",
}


def _tfidf_vectors(docs_tokens: list[list[str]]):
    n = len(docs_tokens)
    df: Counter = Counter()
    for toks in docs_tokens:
        df.update(set(toks))
    idf = {t: math.log((n + 1) / (c + 0.5)) + 1 for t, c in df.items()}
    vectors = []
    for toks in docs_tokens:
        tf = Counter(toks)
        vectors.append({t: (1 + math.log(c)) * idf[t] for t, c in tf.items()})
    return vectors, idf


def _cosine(a: dict, b: dict) -> float:
    common = set(a) & set(b)
    numerator = sum(a[t] * b[t] for t in common)
    denominator = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(
        sum(v * v for v in b.values())
    )
    return numerator / denominator if denominator else 0.0


def find_evidence(claim: str, source_text: str, top_k: int = 3) -> list[dict]:
    """Return the paragraphs (and best sentence in each) that best support `claim`."""
    paragraphs = split_paragraphs(source_text or "")
    if not paragraphs:
        return []
    claim_tokens = tokens(claim)
    docs = [tokens(p) for p in paragraphs]
    vectors, idf = _tfidf_vectors(docs + [claim_tokens])
    claim_vec = vectors[-1]

    results = []
    for index, paragraph in enumerate(paragraphs):
        score = _cosine(claim_vec, vectors[index])
        if score == 0:
            continue
        best_sentence, best_score = paragraph, 0.0
        for sentence in split_sentences(paragraph):
            sentence_vec = {
                t: (1 + math.log(c)) * idf.get(t, 1.0)
                for t, c in Counter(tokens(sentence)).items()
            }
            sentence_score = _cosine(claim_vec, sentence_vec)
            if sentence_score > best_score:
                best_sentence, best_score = sentence, sentence_score

        lowered = paragraph.lower()
        notes = []
        if any(h in lowered.split() for h in HEDGES):
            notes.append("Uses hedged language (may/suggests): evidence may be tentative.")
        if any(c in lowered for c in CONTRAST):
            notes.append(
                "Contains contrasting language: check it doesn't contradict the claim."
            )
        label = "Strong" if score >= 0.35 else "Moderate" if score >= 0.18 else "Weak"
        results.append(
            {
                "paragraph_index": index + 1,
                "score": round(score, 3),
                "match": label,
                "paragraph": paragraph,
                "best_sentence": best_sentence,
                "matched_terms": sorted(set(claim_tokens) & set(docs[index])),
                "notes": notes,
            }
        )
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]


def highlight(
    text: str, matched_stems, best_sentence: str = "", fmt: str = "html"
) -> str:
    """Highlight matched terms; the best sentence gets a stronger highlight.

    fmt="html" returns escaped HTML using <mark> and <span class="best">.
    fmt="ansi" returns terminal escape codes.
    """

    def mark_terms(chunk: str) -> str:
        def repl(match: re.Match) -> str:
            word = match.group(0)
            if stem(word.lower()) in matched_stems:
                return f"<mark>{word}</mark>" if fmt == "html" else f"\033[43m{word}\033[0m"
            return word

        return re.sub(r"[A-Za-z][A-Za-z\-']+", repl, chunk)

    escaped = html.escape(text) if fmt == "html" else text
    if best_sentence and best_sentence in text and best_sentence != text:
        best = html.escape(best_sentence) if fmt == "html" else best_sentence
        if best in escaped:
            before, after = escaped.split(best, 1)
            inner = mark_terms(best)
            wrapped = (
                f'<span class="best">{inner}</span>'
                if fmt == "html"
                else f"\033[1m{inner}\033[0m"
            )
            return mark_terms(before) + wrapped + mark_terms(after)
    return mark_terms(escaped)

"""Research reliability analysis: an explainable 0-100 score with a factor breakdown.

Pure Python, no LLM and no network. Two modes:

* Full paper (default): every factor is scored, unknowns get a small neutral value.
* skip_unknown=True: used for references, where we only have an abstract and
  metadata. Factors that cannot be judged from that are left out of both the points
  and the maximum, so the score is not dragged down by information we never had.
"""

from __future__ import annotations

import re
from datetime import date

from .models import Reference

STUDY_DESIGN_SCORES = {
    "meta-analysis": 25,
    "systematic review": 25,
    "randomized controlled trial": 22,
    "cohort study": 16,
    "case-control": 13,
    "cross-sectional": 10,
    "survey": 8,
    "case study": 5,
    "qualitative": 8,
    "opinion": 2,
    "preprint": 6,
    "unknown": 5,
}


def detect_study_design(text: str) -> str:
    lowered = text.lower()
    rules = [
        ("meta-analysis", "meta-analysis"),
        ("systematic review", "systematic review"),
        ("randomized", "randomized controlled trial"),
        ("randomised", "randomized controlled trial"),
        ("cohort", "cohort study"),
        ("case-control", "case-control"),
        ("cross-sectional", "cross-sectional"),
        ("survey", "survey"),
        ("interview", "qualitative"),
        ("case study", "case study"),
    ]
    for keyword, design in rules:
        if keyword in lowered:
            return design
    return "unknown"


def analyze_reliability(
    meta: dict, paper_text: str = "", skip_unknown: bool = False
) -> dict:
    """
    meta keys (all optional): title, authors, year, venue, peer_reviewed (bool),
    study_design, sample_size (int), citations (int), doi, funding_disclosed (bool),
    conflicts_disclosed (bool), retracted (bool)
    """
    factors: list[dict] = []
    flags: list[str] = []

    def add(name: str, points: int, max_points: int, why: str) -> None:
        factors.append(
            {"factor": name, "points": points, "max": max_points, "reason": why}
        )

    # Study design
    design = meta.get("study_design") or detect_study_design(paper_text)
    if not (skip_unknown and design == "unknown"):
        add(
            "Study design",
            STUDY_DESIGN_SCORES.get(design, 5),
            25,
            f"Detected design: {design}",
        )

    # Peer review
    peer_reviewed = meta.get("peer_reviewed")
    if not (skip_unknown and peer_reviewed is None):
        add(
            "Peer review",
            20 if peer_reviewed else 0 if peer_reviewed is False else 8,
            20,
            "Peer-reviewed"
            if peer_reviewed
            else "Not peer-reviewed"
            if peer_reviewed is False
            else "Unknown",
        )
    if peer_reviewed is False:
        flags.append("Not peer-reviewed: treat findings as provisional.")

    # Sample size
    n = meta.get("sample_size")
    if n is None:
        match = re.search(r"\b[nN]\s*=\s*([\d,]+)", paper_text)
        if match:
            digits = match.group(1).replace(",", "")
            n = int(digits) if digits else None
    if n is None:
        if not skip_unknown:
            add("Sample size", 4, 15, "Not reported or not found")
            flags.append("Sample size not found.")
    else:
        points = 15 if n >= 1000 else 12 if n >= 300 else 8 if n >= 100 else 4 if n >= 30 else 1
        add("Sample size", points, 15, f"n = {n:,}")
        if n < 30:
            flags.append(f"Very small sample (n={n}).")

    # Recency
    year = meta.get("year")
    if year:
        age = date.today().year - int(year)
        points = 10 if age <= 3 else 8 if age <= 7 else 5 if age <= 15 else 2
        add("Recency", points, 10, f"Published {year} ({age} yrs ago)")
    elif not skip_unknown:
        add("Recency", 3, 10, "Year unknown")

    # Citation impact
    citations = meta.get("citations")
    if citations is not None:
        points = 10 if citations >= 500 else 8 if citations >= 100 else 5 if citations >= 20 else 2
        add("Citation impact", points, 10, f"{citations:,} citations")
    elif not skip_unknown:
        add("Citation impact", 3, 10, "Citation count unknown")

    # Transparency
    funding = meta.get("funding_disclosed")
    conflicts = meta.get("conflicts_disclosed")
    if not (skip_unknown and funding is None and conflicts is None):
        add(
            "Transparency",
            (5 if funding else 0) + (5 if conflicts else 0),
            10,
            "Funding/conflict-of-interest disclosure",
        )
    if conflicts is False or (conflicts is None and not skip_unknown):
        flags.append("No conflict-of-interest statement found.")

    # Traceability
    add(
        "Traceability (DOI)",
        5 if meta.get("doi") else 0,
        5,
        "DOI present" if meta.get("doi") else "No DOI",
    )

    # Limitations
    if re.search(r"\blimitation", paper_text, re.I):
        add("Acknowledges limitations", 5, 5, "Paper discusses its limitations")
    elif not skip_unknown:
        add("Acknowledges limitations", 0, 5, "No limitations section detected")

    total = sum(f["points"] for f in factors)
    maximum = sum(f["max"] for f in factors)
    score = round(100 * total / maximum) if maximum else 0
    if meta.get("retracted"):
        score, flags = 0, ["RETRACTED PAPER: do not cite."] + flags
    grade = "High" if score >= 75 else "Moderate" if score >= 50 else "Low"
    return {
        "score": score,
        "grade": grade,
        "design": design,
        "factors": factors,
        "flags": flags,
    }


def reliability_for_reference(reference: Reference) -> dict:
    """Score a resolved reference from the metadata and abstract we actually have."""
    meta = {
        "title": reference.title,
        "authors": reference.authors,
        "year": reference.year,
        "doi": reference.doi,
        "retracted": reference.is_retracted,
    }
    return analyze_reliability(meta, reference.abstract or "", skip_unknown=True)

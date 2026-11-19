from __future__ import annotations

from citeverify.citefix import correct_citation
from citeverify.evidence import find_evidence, highlight
from citeverify.models import Reference
from citeverify.reliability import analyze_reliability, reliability_for_reference

PAPER = """Abstract
This randomized controlled trial examined whether daily sleep duration affects academic performance in university students (n = 412).

Methods
Participants were randomly assigned to a sleep extension group or a control group for eight weeks. Exam scores were collected at baseline and at the end of the study.

Results
Students who increased their sleep to at least eight hours per night showed significantly higher exam scores than controls (p < 0.01). Improvements in concentration and memory recall were also observed in the sleep extension group.

Discussion
These findings suggest that adequate sleep improves academic performance. However, the effect on first-year students was not significant.

Limitations
The study relied on self-reported sleep logs, and the sample came from a single university."""

CLAIM = "Getting more sleep improves students' exam performance."


def test_find_evidence_ranks_relevant_paragraph_first():
    results = find_evidence(CLAIM, PAPER)
    assert results
    top = results[0]["paragraph"]
    assert top.startswith(("Results", "Discussion"))
    assert not top.startswith(("Methods", "Limitations"))
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_find_evidence_flags_hedges_and_contrast():
    results = find_evidence("adequate sleep improves academic performance", PAPER)
    notes = " ".join(n for r in results for n in r["notes"])
    assert "hedged" in notes
    assert "contrasting" in notes


def test_find_evidence_handles_empty_input():
    assert find_evidence(CLAIM, "") == []
    assert find_evidence(CLAIM, "   ") == []


def test_highlight_escapes_html_and_marks_terms():
    text = "Sleep <b>matters</b> for exam performance. Other text here."
    out = highlight(text, {"sleep", "exam"}, "Sleep <b>matters</b> for exam performance.")
    assert "<b>" not in out
    assert "&lt;b&gt;" in out
    assert "<mark>Sleep</mark>" in out
    assert '<span class="best">' in out


def test_reliability_full_paper_matches_expected_shape():
    result = analyze_reliability(
        {
            "year": 2022,
            "peer_reviewed": True,
            "citations": 87,
            "doi": "10.1234/sleep.2022.001",
            "funding_disclosed": True,
            "conflicts_disclosed": False,
        },
        PAPER,
    )
    assert result["design"] == "randomized controlled trial"
    assert 0 <= result["score"] <= 100
    assert any("conflict" in f.lower() for f in result["flags"])


def test_reliability_retracted_is_zero():
    result = analyze_reliability({"retracted": True, "doi": "10.1/x"}, PAPER)
    assert result["score"] == 0
    assert "RETRACTED" in result["flags"][0]


def test_reliability_for_reference_ignores_unknowns():
    sparse = Reference(id="r1", raw="x", year=2023, doi="10.1/abc")
    result = reliability_for_reference(sparse)
    names = {f["factor"] for f in result["factors"]}
    assert "Peer review" not in names
    assert "Transparency" not in names
    assert result["flags"] == []
    assert result["score"] > 0


def test_reliability_for_retracted_reference():
    ref = Reference(id="r1", raw="x", year=1997, is_retracted=True)
    assert reliability_for_reference(ref)["score"] == 0


def test_correct_citation_messy_input():
    raw = (
        "Smith John and Lee A. 2022. Sleep Extension And Academic Performance In "
        "University Students. journal of sleep research, 31(2), 120-134"
    )
    result = correct_citation(raw)
    assert result["corrected"] == (
        "Smith, J., & Lee, A. (2022). Sleep extension and academic performance in "
        "university students. *Journal of Sleep Research*, *31*(2), 120–134."
    )
    assert "DOI" in result["missing"]
    assert any("sentence case" in i for i in result["issues"])
    assert any("en dash" in i for i in result["issues"])


def test_correct_citation_et_al_is_not_an_author():
    result = correct_citation("Ashish Vaswani et al. (2017). Attention Is All You Need.")
    assert result["corrected"].startswith("Vaswani, A., et al. (2017). Attention is all you need.")
    assert any("et al" in i for i in result["issues"])


def test_correct_citation_short_surnames_and_middle_initials():
    he = correct_citation("Kaiming He et al. (2016). Deep Residual Learning for Image Recognition.")
    assert he["corrected"].startswith("He, K., et al. (2016).")
    kingma = correct_citation("Diederik P. Kingma et al. (2015). Adam: A Method for Stochastic Optimization.")
    assert kingma["corrected"].startswith("Kingma, D. P., et al. (2015).")


def test_correct_citation_keeps_doi():
    result = correct_citation(
        "Doe, J. (2020). A study. Journal of Things, 5(1), 1-10. doi:10.1234/abc.5"
    )
    assert result["corrected"].endswith("https://doi.org/10.1234/abc.5")
    assert "DOI" not in result["missing"]

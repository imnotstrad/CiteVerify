from citeverify.doi import doi_url, extract_doi, normalize_doi


def test_normalize_doi_strips_prefix_and_case():
    assert normalize_doi("https://doi.org/10.1000/ABC.123.") == "10.1000/abc.123"


def test_extract_doi_from_prose():
    text = "See the study (doi: 10.48550/arXiv.1706.03762) for details."
    assert extract_doi(text) == "10.48550/arxiv.1706.03762"


def test_doi_url_round_trip():
    assert doi_url("10.1000/XYZ") == "https://doi.org/10.1000/xyz"


def test_invalid_doi_returns_none():
    assert normalize_doi("not a doi") is None
    assert normalize_doi(None) is None

from citeverify import local_matcher


def test_passages_preserve_source_text():
    source = "First sentence supports the claim. Second sentence adds context.\n\nA separate paragraph."
    passages = local_matcher._passages(source)
    assert passages
    assert "First sentence supports the claim." in " ".join(passages)
    assert "A separate paragraph." in " ".join(passages)


def test_keyword_fallback_ranks_relevant_passage(monkeypatch):
    def unavailable():
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(local_matcher, "_load_model", unavailable)
    selected, method = local_matcher.retrieve_passages(
        "neural networks improve image classification accuracy",
        "A study of ocean currents and temperature. "
        "Neural networks improved image classification accuracy in the experiment.",
        top_k=1,
    )
    assert method == "keyword"
    assert selected
    assert "Neural networks" in selected[0]

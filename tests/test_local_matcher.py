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


def test_embeddings_can_be_switched_off(monkeypatch):
    def must_not_load():
        raise AssertionError("model should not be loaded when disabled")

    monkeypatch.setenv("LOCAL_EMBEDDINGS", "0")
    monkeypatch.setattr(local_matcher, "_load_model", must_not_load)
    selected, method = local_matcher.retrieve_passages(
        "ocean temperature", "Ocean temperature rose. Unrelated sentence here.", top_k=1
    )
    assert method == "keyword"
    assert "Ocean temperature" in selected[0]


def test_keyword_is_the_safe_default(monkeypatch):
    def must_not_load():
        raise AssertionError("model should not be loaded by default")

    monkeypatch.delenv("LOCAL_EMBEDDINGS", raising=False)
    monkeypatch.setattr(local_matcher, "_load_model", must_not_load)
    selected, method = local_matcher.retrieve_passages(
        "ocean temperature", "Ocean temperature rose. Unrelated sentence here.", top_k=1
    )
    assert method == "keyword"
    assert "Ocean temperature" in selected[0]


def test_model_load_is_serialized_and_failure_is_remembered(monkeypatch):
    import sys
    import threading
    import types

    calls = []

    class Boom:
        def __init__(self, name):
            calls.append(name)
            raise RuntimeError("offline")

    stub = types.ModuleType("sentence_transformers")
    stub.SentenceTransformer = Boom
    monkeypatch.setitem(sys.modules, "sentence_transformers", stub)
    monkeypatch.setattr(local_matcher, "_model", None)
    monkeypatch.setattr(local_matcher, "_model_error", None)

    errors = []

    def worker():
        try:
            local_matcher._load_model()
        except RuntimeError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(errors) == 4
    assert len(calls) == 1  # one attempt in total, not one per thread

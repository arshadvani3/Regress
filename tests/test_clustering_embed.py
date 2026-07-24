import pytest

from regress.clustering.embed import DEFAULT_MODEL, load_embedder


def test_load_embedder_raises_clear_error_when_extra_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "sentence_transformers":
            raise ImportError("No module named 'sentence_transformers'")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ImportError, match="regress-ai\\[cluster\\]"):
        load_embedder()


@pytest.mark.slow
def test_load_embedder_produces_dense_vectors_for_real_model() -> None:
    embedder = load_embedder(DEFAULT_MODEL)

    vectors = embedder.embed(["hello world", "goodbye world"])

    assert vectors.shape[0] == 2
    assert vectors.shape[1] > 0

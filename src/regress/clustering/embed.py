"""Local embeddings via sentence-transformers.

`sentence-transformers` pulls in torch as a transitive dependency (~100MB+),
which conflicts with CLAUDE.md's "pip install regress-ai, working in under
5 minutes" north star as a core dependency. It's the `cluster` extra
(`pip install regress-ai[cluster]`) instead; `load_embedder()` gives a
clear, actionable error if it's missing rather than a raw ImportError.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    import numpy as np

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"

_INSTALL_HINT = (
    "Clustering requires the 'cluster' extra (sentence-transformers + "
    "scikit-learn). Install it with: pip install 'regress-ai[cluster]'"
)


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> np.ndarray: ...


class _SentenceTransformerEmbedder:
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(_INSTALL_HINT) from exc
        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> np.ndarray:
        embeddings: np.ndarray = self._model.encode(texts, convert_to_numpy=True)
        return embeddings


def load_embedder(model_name: str = DEFAULT_MODEL) -> Embedder:
    """Load the local embedding model. Raises ImportError with an install
    hint if the `cluster` extra isn't installed.
    """
    return _SentenceTransformerEmbedder(model_name)

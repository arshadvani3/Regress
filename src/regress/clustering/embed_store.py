"""Incremental, persisted embeddings for clustering.

`regress cluster` used to re-embed every scored-bad trace on every run and
throw the vectors away — the expensive, model-loading work redone from
scratch each time. This module persists each trace's embedding (keyed on the
exact text that was embedded) so a repeat run only embeds *new or changed*
failures and reuses the rest.

Vectors are stored as JSON in the `trace_embeddings` table, which keeps this
in the zero-config SQLite path with no database server. That's deliberate: a
single-node failure-to-eval tool that required Postgres would betray the
"pip install and go" promise. Postgres + pgvector is the documented scale
path (storage is abstracted behind `REGRESS_DB_URL`) for teams that outgrow
one node — not a default.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from regress.clustering import ClusterableTrace
from regress.clustering.embed import Embedder
from regress.models import TraceEmbedding

if TYPE_CHECKING:
    import numpy as np


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def embed_incremental(
    session: Session,
    clusterable: list[ClusterableTrace],
    embedder: Embedder,
) -> np.ndarray:
    """Return one embedding per input trace, in input order.

    Reuses any stored vector whose text still hashes to the same value, embeds
    only the misses in a single batched call, and persists the new vectors.
    The returned array is aligned to `clusterable` so the caller can pass it
    straight to `cluster_traces` alongside the same trace-id order.
    """
    import numpy as np

    stored = {
        row.trace_id: row
        for row in session.execute(
            select(TraceEmbedding).where(
                TraceEmbedding.trace_id.in_([c.trace_id for c in clusterable])
            )
        ).scalars()
    }

    hashes = [_text_hash(c.text) for c in clusterable]

    # Which inputs need embedding (new trace, or text changed since last time).
    miss_indices = [
        i
        for i, (c, h) in enumerate(zip(clusterable, hashes, strict=True))
        if c.trace_id not in stored or stored[c.trace_id].text_hash != h
    ]

    fresh_by_index: dict[int, list[float]] = {}
    if miss_indices:
        miss_vectors = embedder.embed([clusterable[i].text for i in miss_indices])
        for i, vector in zip(miss_indices, np.asarray(miss_vectors), strict=True):
            vec_list = [float(x) for x in vector]
            fresh_by_index[i] = vec_list
            _upsert(session, clusterable[i].trace_id, hashes[i], vec_list, stored)
        session.flush()

    # Assemble the full result in input order: fresh vectors where we just
    # embedded, stored vectors everywhere else.
    result = [
        fresh_by_index[i] if i in fresh_by_index else stored[c.trace_id].vector
        for i, c in enumerate(clusterable)
    ]
    return np.asarray(result)


def _upsert(
    session: Session,
    trace_id: str,
    text_hash: str,
    vector: list[float],
    stored: dict[str, TraceEmbedding],
) -> None:
    existing = stored.get(trace_id)
    if existing is None:
        session.add(TraceEmbedding(trace_id=trace_id, text_hash=text_hash, vector=vector))
    else:
        existing.text_hash = text_hash
        existing.vector = vector

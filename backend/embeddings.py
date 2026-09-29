"""Local embeddings. No API calls, so ingestion costs nothing.

Two backends, same model (all-MiniLM-L6-v2, 384-dim):

  onnx  (default) — the ONNX build bundled with ChromaDB. No PyTorch, roughly a
                    tenth of the memory, and a ~80MB download instead of ~2.5GB.
                    This is what makes deploying on a 512MB free tier possible.
  torch           — sentence-transformers. Same weights, heavier runtime.

Vectors from the two are near-identical but not bit-identical, so an index built
with one should be queried with the same one. Within a single process that is
automatic; across a rebuild, re-index. Whichever is active is printed by the eval
harness so a measured number always says which backend produced it.
"""

import os
from functools import lru_cache

from backend.config import EMBEDDING_MODEL

BACKEND = os.getenv("DOCLYN_EMBEDDINGS", "onnx").lower()


@lru_cache(maxsize=1)
def _encoder():
    """Built once, on first use. Imports live inside the function because both
    backends are slow to import and neither is needed to serve /health."""
    if BACKEND == "torch":
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(EMBEDDING_MODEL)
        return "torch", lambda texts: [v.tolist() for v in model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False,
            convert_to_numpy=True)]

    from chromadb.utils.embedding_functions import ONNXMiniLM_L6_V2

    fn = ONNXMiniLM_L6_V2()
    return "onnx", lambda texts: [list(map(float, v)) for v in fn(texts)]


def backend_name() -> str:
    return _encoder()[0]


def _normalize(vector: list[float]) -> list[float]:
    """Unit length, so a dot product IS cosine similarity.

    Both backends already normalise. Doing it here anyway costs nothing and
    means the two are guaranteed to behave identically rather than
    near-identically — which matters when a score is compared against SIM_FLOOR.
    """
    norm = sum(x * x for x in vector) ** 0.5
    return [x / norm for x in vector] if norm else vector


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    _, encode = _encoder()
    return [_normalize(v) for v in encode(texts)]


def embed_query(text: str) -> list[float]:
    return embed([text])[0]

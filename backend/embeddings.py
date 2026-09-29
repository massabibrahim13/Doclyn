"""Local embeddings. No API calls, so ingestion costs nothing.

This is the single biggest reason Doclyn is free: a 100-page PDF produces a few
hundred embeddings, and all of them are computed on this machine.
"""

from functools import lru_cache

from backend.config import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def _model():
    """Loaded once, on first use. The import is inside the function because
    sentence-transformers pulls in torch and takes seconds to load — no reason
    to pay that when the app is only serving /health."""
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL)


def embed(texts: list[str]) -> list[list[float]]:
    """Text -> vectors. Normalised, so a dot product IS cosine similarity."""
    if not texts:
        return []
    vectors = _model().encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return [v.tolist() for v in vectors]


def embed_query(text: str) -> list[float]:
    return embed([text])[0]

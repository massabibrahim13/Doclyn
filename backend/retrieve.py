"""Query path: question -> vector -> nearest chunks -> similarity floor."""

from backend import embeddings, store
from backend.config import SIM_FLOOR, TOP_K_DEFAULT


def retrieve(question: str, top_k: int = TOP_K_DEFAULT,
             document_ids: list[str] | None = None,
             sim_floor: float = SIM_FLOOR) -> tuple[list[dict], bool]:
    """Returns (chunks, grounded).

    grounded is False when every result falls below the floor. That does double
    duty: it prevents an ungrounded answer, and it lets /chat skip the LLM call
    entirely, so an unanswerable question costs zero tokens.
    """
    hits = store.query(embeddings.embed_query(question), top_k, document_ids)
    if not hits:
        return [], False

    grounded = any(h["score"] >= sim_floor for h in hits)
    if not grounded:
        return [], False

    # Keep every chunk that clears the floor, best first.
    #
    # An earlier version collapsed ADJACENT chunks from the same document, on the
    # theory that their overlap duplicates text. Measured 2026-09-29: that was a
    # bad trade. Asking "what overlap is recommended?" retrieved the right chunk
    # at rank 2, the filter dropped it for being next to rank 1, and the model
    # correctly answered that it didn't know. Overlap costs ~10% duplicated
    # tokens; dropping the chunk holding the answer costs the answer.
    kept = [h for h in sorted(hits, key=lambda x: -x["score"]) if h["score"] >= sim_floor]
    return kept, True

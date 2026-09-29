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

    # Adjacent chunks from the same document overlap by design, so sending both
    # wastes tokens on duplicated text.
    kept, seen = [], set()
    for h in sorted(hits, key=lambda x: -x["score"]):
        if h["score"] < sim_floor:
            continue
        key = (h["metadata"]["document_id"], h["metadata"]["chunk_index"])
        if any(k[0] == key[0] and abs(k[1] - key[1]) <= 1 for k in seen):
            continue
        seen.add(key)
        kept.append(h)

    return kept, True

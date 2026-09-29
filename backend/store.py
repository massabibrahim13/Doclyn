"""ChromaDB wrapper. Vectors, chunk text and metadata all live together here.

Chroma is embedded — there is no server process. It writes to chroma_store/ on
disk, which is what makes "upload once, query forever" true.
"""

from functools import lru_cache
from typing import Any

from backend.config import CHROMA_DIR, COLLECTION_NAME, DISTANCE_METRIC


@lru_cache(maxsize=1)
def _collection():
    import chromadb

    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    # hnsw:space must be set at creation. Cosine is what the embedding model
    # is normalised for; leaving Chroma's default (L2) would quietly rank
    # results differently.
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": DISTANCE_METRIC},
    )


def add_chunks(ids, texts, embeddings, metadatas) -> None:
    _collection().add(ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas)


def hash_exists(content_hash: str) -> dict | None:
    """Dedup check. Returns the existing document's metadata, or None.

    Without this, re-uploading a file double-indexes it and retrieval starts
    returning the same passage twice — which silently degrades every answer.
    """
    res = _collection().get(where={"content_hash": content_hash}, limit=1,
                            include=["metadatas"])
    metas = res.get("metadatas") or []
    return metas[0] if metas else None


def query(embedding: list[float], top_k: int, document_ids: list[str] | None = None):
    """Nearest chunks. Returns a list of dicts with text, metadata and score."""
    where = None
    if document_ids:
        where = ({"document_id": document_ids[0]} if len(document_ids) == 1
                 else {"document_id": {"$in": document_ids}})

    res = _collection().query(
        query_embeddings=[embedding],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    out = []
    for cid, text, meta, dist in zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        # Chroma returns cosine DISTANCE (0 = identical). Similarity is 1 - d,
        # which is the number the rest of the app and the UI talk about.
        out.append({"chunk_id": cid, "text": text, "metadata": meta,
                    "score": round(1.0 - dist, 4)})
    return out


def list_documents() -> list[dict[str, Any]]:
    """One row per document, aggregated from chunk metadata."""
    res = _collection().get(include=["metadatas"])
    docs: dict[str, dict] = {}
    for meta in res.get("metadatas") or []:
        did = meta["document_id"]
        if did not in docs:
            docs[did] = {
                "document_id": did,
                "filename": meta.get("filename"),
                "pages": meta.get("pages", 1),
                "chunks": 0,
                "ingested_at": meta.get("ingested_at"),
            }
        docs[did]["chunks"] += 1
    return sorted(docs.values(), key=lambda d: d.get("ingested_at") or "")


def delete_document(document_id: str) -> bool:
    if not any(d["document_id"] == document_id for d in list_documents()):
        return False
    _collection().delete(where={"document_id": document_id})
    return True


def counts() -> tuple[int, int]:
    """(documents, chunks) — for GET /health."""
    return len(list_documents()), _collection().count()


def reset() -> None:
    """Wipe everything. Used by the eval harness when re-indexing."""
    import chromadb

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    _collection.cache_clear()

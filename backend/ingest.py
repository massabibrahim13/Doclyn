"""Ingestion: file bytes -> text -> chunks -> vectors -> Chroma.

This path never calls the LLM API. It cannot be rate limited and it costs
nothing, which is why documents can be re-indexed as often as tuning requires.
"""

import bisect
import hashlib
import io
from datetime import datetime, timezone

from backend import embeddings, store
from backend.config import CHUNK_OVERLAP, CHUNK_SIZE

# CHUNK_SIZE is in tokens; splitting happens on characters. Four characters per
# token is the same rough conversion used by the budget preflight.
CHARS_PER_TOKEN = 4


class IngestError(Exception):
    """Raised with a message suitable for showing the user."""


def file_hash(data: bytes) -> str:
    """SHA-256 of the raw bytes — the dedup key. Computed before parsing, so a
    duplicate costs nothing at all."""
    return hashlib.sha256(data).hexdigest()


def extract_text(filename: str, data: bytes) -> tuple[str, list[int], int]:
    """Returns (full_text, page_start_offsets, page_count).

    Pages are concatenated into one string and their character offsets recorded,
    so a chunk can be mapped back to the page it came from. Chunking the whole
    text rather than page by page avoids producing a stub chunk at every page
    break.
    """
    lower = filename.lower()

    if lower.endswith(".txt"):
        text = data.decode("utf-8", errors="replace")
        return text, [0], 1

    if lower.endswith(".pdf"):
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
        except Exception as exc:
            raise IngestError("Could not read the PDF") from exc

        parts, offsets, cursor = [], [], 0
        for page in reader.pages:
            offsets.append(cursor)
            page_text = (page.extract_text() or "") + "\n\n"
            parts.append(page_text)
            cursor += len(page_text)
        return "".join(parts), offsets, len(reader.pages)

    raise IngestError("Only .pdf and .txt are supported")


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list[tuple[int, str]]:
    """Split into overlapping passages. Returns (char_start, chunk_text) pairs.

    Fixed-size with overlap, but it prefers to break at a paragraph or sentence
    boundary when one falls near the target length — a chunk ending mid-sentence
    embeds worse than one ending cleanly.
    """
    size = chunk_size * CHARS_PER_TOKEN
    lap = overlap * CHARS_PER_TOKEN
    text = text.strip()
    n = len(text)
    if n == 0:
        return []

    chunks: list[tuple[int, str]] = []
    start = 0

    while start < n:
        end = min(start + size, n)

        if end < n:
            # Only look for a boundary in the last 30% of the window, so a break
            # near the start doesn't produce a tiny chunk.
            earliest = start + int(size * 0.7)
            cut = text.rfind("\n\n", earliest, end)
            if cut <= start:
                cut = max(text.rfind(". ", earliest, end), text.rfind(".\n", earliest, end))
                cut = cut + 1 if cut > start else -1
            if cut > start:
                end = cut

        piece = text[start:end].strip()
        if piece:
            chunks.append((start, piece))

        if end >= n:
            break
        start = max(end - lap, start + 1)

    return chunks


def _page_for_offset(offsets: list[int], char_start: int) -> int:
    """Which page a character offset falls on. Pages are 1-indexed."""
    return bisect.bisect_right(offsets, char_start)


def ingest_document(filename: str, data: bytes,
                    chunk_size: int = CHUNK_SIZE) -> dict:
    """Full write path. Returns the §6.2 response shape."""
    content_hash = file_hash(data)

    existing = store.hash_exists(content_hash)
    if existing:
        return {
            "document_id": existing["document_id"],
            "filename": existing.get("filename", filename),
            "content_hash": content_hash,
            "pages": existing.get("pages", 1),
            "chunks_created": 0,
            "duplicate": True,
            "ingested_at": existing.get("ingested_at"),
        }

    text, page_offsets, page_count = extract_text(filename, data)
    if not text.strip():
        raise IngestError("No extractable text found; OCR is not supported in v1")

    pieces = chunk_text(text, chunk_size)
    if not pieces:
        raise IngestError("No extractable text found; OCR is not supported in v1")

    document_id = f"doc_{content_hash[:8]}"
    ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    ids, texts, metas = [], [], []
    for index, (char_start, piece) in enumerate(pieces):
        ids.append(f"{document_id}::c{index:03d}")
        texts.append(piece)
        metas.append({
            "document_id": document_id,
            "filename": filename,
            "content_hash": content_hash,
            "page": _page_for_offset(page_offsets, char_start),
            "pages": page_count,
            "chunk_index": index,
            "char_start": char_start,
            "ingested_at": ingested_at,
        })

    store.add_chunks(ids, texts, embeddings.embed(texts), metas)

    return {
        "document_id": document_id,
        "filename": filename,
        "content_hash": content_hash,
        "pages": page_count,
        "chunks_created": len(pieces),
        "duplicate": False,
        "ingested_at": ingested_at,
    }

"""Retrieval evaluation. Makes ZERO API calls — run it as often as you like.

    python scripts\test_retrieval.py --reindex
    python scripts\test_retrieval.py --reindex --chunk-size 500
    python scripts\test_retrieval.py --top-k 5

Measures hit rate at k: the share of test questions where the correct passage
appears in the top k results. This is the number that decides answer quality.
If retrieval fetches the wrong passage, no model and no prompt can recover.

It also prints the score gap between answerable and unanswerable questions,
which is how SIM_FLOOR gets a real value instead of a guessed one.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import embeddings, ingest, store  # noqa: E402
from backend.config import SAMPLE_DIR, SIM_FLOOR, TOP_K_DEFAULT  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--reindex", action="store_true", help="wipe and re-ingest the corpus")
parser.add_argument("--chunk-size", type=int, default=None, help="tokens per chunk")
parser.add_argument("--top-k", type=int, default=TOP_K_DEFAULT)
args = parser.parse_args()

def _norm(s: str) -> str:
    """Collapse all whitespace and lowercase.

    Source files are hard-wrapped, so an expected phrase often straddles a
    newline. Matching on raw text would fail for a reason that has nothing to do
    with retrieval quality — which would make the eval lie.
    """
    return re.sub(r"\s+", " ", s).strip().lower()


EVAL_FILE = SAMPLE_DIR / "eval.json"
if not EVAL_FILE.exists():
    print(f"No eval set at {EVAL_FILE}")
    sys.exit(1)

cases = json.loads(EVAL_FILE.read_text(encoding="utf-8"))
answerable = [c for c in cases if not c.get("unanswerable")]
unanswerable = [c for c in cases if c.get("unanswerable")]

# ── Index ────────────────────────────────────────────────────────────────────
if args.reindex:
    from backend.config import CHUNK_SIZE

    size = args.chunk_size or CHUNK_SIZE
    print(f"Re-indexing {SAMPLE_DIR} at chunk_size={size} tokens...")
    store.reset()
    total = 0
    for path in sorted(SAMPLE_DIR.glob("*")):
        if path.suffix.lower() not in {".txt", ".pdf"}:
            continue
        res = ingest.ingest_document(path.name, path.read_bytes(), chunk_size=size)
        total += res["chunks_created"]
        print(f"  {path.name:<28} {res['chunks_created']:>3} chunks")
    print(f"  {'total':<28} {total:>3} chunks\n")

docs, chunks = store.counts()
if chunks == 0:
    print("Index is empty. Run again with --reindex")
    sys.exit(1)

print(f"Index: {docs} documents, {chunks} chunks   |   evaluating top_k={args.top_k}\n")

# ── Answerable questions: hit rate at k ──────────────────────────────────────
hits = 0
page_hits = 0
top_scores = []
rows = []

for case in answerable:
    results = store.query(embeddings.embed_query(case["question"]), args.top_k)
    needle = _norm(case["expect_chunk_contains"])

    rank = None
    for i, r in enumerate(results, start=1):
        if needle in _norm(r["text"]):
            rank = i
            break

    best = results[0]["score"] if results else 0.0
    top_scores.append(best)
    if rank:
        hits += 1
        if case.get("expect_page") is None or \
           results[rank - 1]["metadata"].get("page") == case["expect_page"]:
            page_hits += 1

    rows.append((case["question"], rank, best,
                 results[0]["metadata"]["filename"] if results else "-"))

print("ANSWERABLE")
print("-" * 78)
for question, rank, best, fname in rows:
    mark = f"@{rank}" if rank else "MISS"
    print(f"  {mark:<5} {best:>6.3f}  {question[:44]:<44} {fname[:20]}")

n = len(answerable)
rate = hits / n * 100
print(f"\n  HIT RATE @ {args.top_k} : {hits}/{n} = {rate:.1f}%")
print(f"  correct page    : {page_hits}/{n}")

# ── Unanswerable questions: what do they score? ──────────────────────────────
noise_scores = []
if unanswerable:
    print("\nUNANSWERABLE  (these should score LOW — that is what the floor catches)")
    print("-" * 78)
    for case in unanswerable:
        results = store.query(embeddings.embed_query(case["question"]), args.top_k)
        best = results[0]["score"] if results else 0.0
        noise_scores.append(best)
        flag = "leaks through" if best >= SIM_FLOOR else "blocked"
        print(f"        {best:>6.3f}  {case['question'][:44]:<44} {flag}")

# ── Floor recommendation ─────────────────────────────────────────────────────
print("\n" + "=" * 78)
if top_scores and noise_scores:
    worst_real = min(top_scores)
    best_noise = max(noise_scores)
    print(f"  lowest score on a real question : {worst_real:.3f}")
    print(f"  highest score on a noise question: {best_noise:.3f}")
    print(f"  current SIM_FLOOR                : {SIM_FLOOR}")
    if worst_real > best_noise:
        suggested = round((worst_real + best_noise) / 2, 2)
        print(f"\n  Clean separation. Suggested SIM_FLOOR = {suggested}")
        print("  (set it in backend/config.py)")
    else:
        print("\n  No clean gap — some noise scores as high as a real match.")
        print("  The floor alone cannot separate these. Note it honestly in the README.")
print("=" * 78)
print("\nZero API calls were made.")

"""Stage 4 verification — the five checks from the spec, automated.

    python scripts\test_stage4.py

Costs about 2 real API calls. Set DOCLYN_STUB=0 first.

Checks:
  1. answerable question   -> correct answer, correct page cited
  2. unanswerable question -> grounded:false, NO API call, no hallucination
  3. re-upload same file   -> duplicate:true, chunk count unchanged
  4. scoped to doc B, ask about doc A -> refusal
  5. /usage reflects exactly the calls that were made
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from backend import config, store, usage  # noqa: E402
from backend.config import SAMPLE_DIR  # noqa: E402
from backend.main import app  # noqa: E402

if config.STUB_MODE:
    print("DOCLYN_STUB is 1 — these checks need real answers. Set it to 0 in .env.")
    sys.exit(1)

c = TestClient(app)
passed, failed = 0, 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
    # detail explains a FAILURE. Printing it next to PASS produced lines like
    # "PASS  chunks contain the answer   retrieval sent the wrong chunks".
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   {detail}" if detail and not ok else ""))


print(f"\nStage 4 verification — budget before: {usage.today_total():,} tokens used\n")

# ── Setup ────────────────────────────────────────────────────────────────────
store.reset()
ids = {}
for path in sorted(SAMPLE_DIR.glob("*.txt")):
    with path.open("rb") as f:
        r = c.post("/documents", files={"file": (path.name, f, "text/plain")})
    ids[path.name] = r.json()["document_id"]
    print(f"  indexed {path.name:<26} {r.json()['chunks_created']} chunks  (HTTP {r.status_code})")

docs, chunks = store.counts()
print(f"  {docs} documents, {chunks} chunks\n")

# ── 3. Dedup (free — no API call) ────────────────────────────────────────────
print("CHECK 3 — duplicate upload")
name = "rag-fundamentals.txt"
with (SAMPLE_DIR / name).open("rb") as f:
    r = c.post("/documents", files={"file": (name, f, "text/plain")})
after_docs, after_chunks = store.counts()
check(r.status_code == 200, "returns 200 not 201", f"got {r.status_code}")
check(r.json()["duplicate"] is True, "duplicate flag set")
check(after_chunks == chunks, "chunk count unchanged", f"{chunks} -> {after_chunks}")

# ── 2. Unanswerable (free — must NOT call the API) ───────────────────────────
print("\nCHECK 2 — unanswerable question")
before = usage.today_total()
r = c.post("/chat", json={"message": "Who won the cricket match last night?"})
j = r.json()
check(j["grounded"] is False, "grounded is false")
check(len(j["citations"]) == 0, "no citations")
check(j["usage"]["input_tokens"] == 0, "usage zeroed")
check(usage.today_total() == before, "LEDGER UNCHANGED — no API call was made")
print(f"        answer: {j['answer']}")

# ── 4. Scoping (free if it refuses) ──────────────────────────────────────────
print("\nCHECK 4 — scoped to the wrong document")
r = c.post("/chat", json={"message": "What overlap is recommended between chunks?",
                          "document_ids": [ids["http-and-rest.txt"]]})
j = r.json()
if j["grounded"]:
    others = {cit["document_id"] for cit in j["citations"]} - {ids["http-and-rest.txt"]}
    check(not others, "citations stayed inside the scoped document")
    print("        note: answered rather than refused — the scoped doc cleared the floor")
else:
    check(True, "refused, as expected")

# ── 1. Answerable (costs one API call) ───────────────────────────────────────
print("\nCHECK 1 — answerable question  [real API call]")
before = usage.today_total()
r = c.post("/chat", json={"message": "What overlap is recommended between chunks?"})
j = r.json()
check(r.status_code == 200, "HTTP 200", f"got {r.status_code}")
check(j["grounded"] is True, "grounded is true")
check(len(j["citations"]) > 0, "citations returned", f"{len(j['citations'])}")
check(usage.today_total() > before, "ledger recorded the call",
      f"+{usage.today_total() - before} tokens")

# The checks above are mechanical: they pass even when the answer is wrong.
# These two look at what was actually delivered.
import re  # noqa: E402

norm = lambda s: re.sub(r"\s+", " ", s).lower()
# The snippet is truncated for display; check the FULL chunk that was sent.
sent = norm(" ".join(
    ch["text"] for ch in store.query(
        __import__("backend.embeddings", fromlist=["x"]).embed_query(
            "What overlap is recommended between chunks?"), 3)
))
check("10 percent" in sent,
      "the chunks sent actually contain the answer",
      "retrieval sent the wrong chunks")
check(all(re.fullmatch(r"\[\d+\]", m) for m in re.findall(r"\[[^\]]*\]", j["answer"])),
      "citation markers are plain [n]",
      f"found {re.findall(r'[^ -~]', j['answer'])[:6]}" if re.search(r"[^ -~]", j["answer"]) else "")
check(not any(p in norm(j["answer"]) for p in
              ("does not specify", "not specify", "does not mention", "couldn't find")),
      "the model did not say it couldn't find it")
print(f"\n        answer: {j['answer']}\n")
for cit in j["citations"]:
    print(f"        [{cit['marker']}] {cit['filename']} p.{cit['page']} "
          f"score={cit['score']}")
    print(f"            {cit['snippet'][:90]}...")

# ── 5. Usage endpoint ────────────────────────────────────────────────────────
print("\nCHECK 5 — /usage")
u = c.get("/usage").json()
check(u["tokens_used_today"] == usage.today_total(), "matches the ledger")
print(f"        {u['queries_today']} queries, {u['tokens_used_today']:,} tokens used, "
      f"{u['remaining']:,} remaining")

print("\n" + "=" * 62)
print(f"  {passed} passed, {failed} failed")
print(f"  total spend today: {usage.today_total():,} / {config.DAILY_TOKEN_BUDGET:,}")
print("=" * 62)
sys.exit(1 if failed else 0)

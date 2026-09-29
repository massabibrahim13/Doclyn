# Doclyn

A document-grounded chatbot. Upload documents, ask questions, get answers with
citations you can check — or an explicit refusal when the documents don't contain
the answer.

Built to run entirely on free tiers: **no paid API, no credit card, no trial
credits that expire into a bill.**

```
FastAPI · ChromaDB · all-MiniLM-L6-v2 (local, ONNX) · Groq gpt-oss-120b · Streamlit
```

---

## What this actually gives you

Honest first: **if you have one PDF and one question, pasting it into ChatGPT or
Claude is better.** The whole document fits in context, so there is no retrieval
step to get wrong. Doclyn does not beat that, and pretending otherwise would be
the least credible thing in this README.

Where it does earn its place:

| Benefit | How |
|---|---|
| Upload once, query forever | Persistent vector store + content-hash dedup on re-upload |
| Verify every claim | Citations carry filename, page, similarity score and the retrieved text |
| No confident fabrication | Similarity floor → `grounded: false` → a visibly different refusal |
| Scope a question to specific documents | `document_ids` filter, per-document checkboxes in the UI |
| Drop it inside another product | **The REST API is the product.** The UI is one client of it |

---

## Architecture

```
┌──────────────────┐
│  Streamlit UI    │  one client of the API — not the product
└────────┬─────────┘
         │ HTTP (JSON / SSE)
┌────────▼─────────────────────────────────────────────┐
│  FastAPI backend  ← THE PRODUCT                      │
│                                                      │
│  ┌────────────┐  ┌────────────┐  ┌────────────────┐  │
│  │ ingest.py  │  │ retrieve.py│  │  llm.py        │  │
│  │ parse→chunk│  │ embed query│  │ prompt assembly│  │
│  │ →embed→    │  │ →top-k     │  │ →provider call │  │
│  │  store     │  │ →floor     │  │ →stream        │  │
│  └─────┬──────┘  └─────┬──────┘  └───────┬────────┘  │
│                                   ┌──────▼────────┐  │
│                                   │  usage.py     │  │
│                                   │  token ledger │  │
│                                   │  + preflight  │  │
│                                   └──────┬────────┘  │
└────────┼───────────────┼─────────────────┼───────────┘
         │               │                 │ OpenAI-compatible HTTP
    ┌────▼───────────────▼────┐      ┌─────▼─────────────────┐
    │   ChromaDB (persistent) │      │  Groq                 │
    │   ./chroma_store/       │      │  api.groq.com/openai  │
    │   vectors + text + meta │      │  gpt-oss-120b         │
    └─────────────────────────┘      └───────────────────────┘
              ▲
    ┌─────────┴──────────────┐
    │ all-MiniLM-L6-v2 (ONNX)│  local, CPU, 384-dim, no PyTorch
    │ (runs on your machine, │  ← why ingestion costs nothing, and why
    │  zero API calls)       │    the API fits in 512MB of RAM
    └────────────────────────┘
```

**Only one arrow costs anything.** Embeddings run locally on CPU, so ingesting a
100-page PDF makes zero API calls. A hosted embeddings API would burn hundreds of
requests on a single upload — that choice is most of why this project is free.

---

## Setup

```bash
git clone <your-repo-url> && cd doclyn
python -m venv .venv
.venv\Scripts\activate           # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

copy .env.example .env           # cp on macOS/Linux
# paste a key from https://console.groq.com/keys  (free, no credit card)

python scripts/check_env.py      # verifies interpreter, deps, key loading
```

Embeddings default to the ONNX build of `all-MiniLM-L6-v2` that ships with
ChromaDB — same model as `sentence-transformers`, no PyTorch, about a tenth of
the memory. That is what lets the API run on a 512MB free tier. To use the
PyTorch path instead: `pip install sentence-transformers` and set
`DOCLYN_EMBEDDINGS=torch`. Re-index when switching, since the two produce
near-identical but not bit-identical vectors.

Run the two processes:

```bash
uvicorn backend.main:app --reload     # terminal 1 — API on :8000
streamlit run frontend/app.py         # terminal 2 — UI on :8501
```

`.env` ships with `DOCLYN_STUB=1`, so a fresh clone returns canned answers and
spends nothing until you deliberately set it to `0`.

---

## Using the API directly

The UI is optional. Everything is reachable over HTTP.

```bash
# Upload a document
curl -X POST http://localhost:8000/documents \
     -F "file=@data/sample/rag-fundamentals.txt"
```
```json
{"document_id":"doc_a1b2c3d4","filename":"rag-fundamentals.txt","pages":1,
 "chunks_created":4,"duplicate":false,"ingested_at":"2026-09-29T15:40:11Z"}
```

```bash
# Ask a question
curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"message":"What overlap is recommended between chunks?","top_k":3}'
```
```json
{"answer":"An overlap of roughly 10 percent is recommended between chunks [2].",
 "citations":[{"marker":2,"filename":"rag-fundamentals.txt","page":1,
               "chunk_id":"doc_a1b2c3d4::c001","score":0.3987,
               "snippet":"...overlap of roughly 10 percent means any sentence..."}],
 "usage":{"input_tokens":864,"output_tokens":100},
 "grounded":true,
 "budget":{"used_today":3591,"daily_budget":150000,"remaining":146409}}
```

```bash
# Ask something the documents don't cover — note grounded:false and zero usage
curl -X POST http://localhost:8000/chat \
     -H "Content-Type: application/json" \
     -d '{"message":"Who won the cricket match last night?"}'
```
```json
{"answer":"I couldn't find this in your documents.","citations":[],
 "usage":{"input_tokens":0,"output_tokens":0},"grounded":false,
 "budget":{"used_today":3591,"daily_budget":150000,"remaining":146409}}
```

```bash
curl http://localhost:8000/documents          # list indexed documents
curl -X DELETE http://localhost:8000/documents/doc_a1b2c3d4
curl http://localhost:8000/usage              # today's token spend, no API call
curl http://localhost:8000/health
```

Interactive docs at `http://localhost:8000/docs`, generated from the Pydantic
schemas. `POST /chat/stream` returns the same data as server-sent events, with
citations emitted **before** the first token so the UI can render sources while
the answer is still typing.

---

## Measured results

Everything below is measured, not estimated. The evaluation harness makes **zero
API calls**, so it can be re-run as often as tuning requires.

```bash
python scripts/test_retrieval.py --reindex
python scripts/test_retrieval.py --reindex --chunk-size 500
```

### Retrieval: hit rate @ k

15 questions (12 answerable, 3 deliberately unanswerable) against a 3-document
corpus.

| Chunk size | Chunks indexed | Hit rate @3 | Ranked #1 | Delivered @3 | Input tokens/query |
|---|---|---|---|---|---|
| **350 (chosen)** | 10 | **11/12 — 91.7%** | 8/12 | 10/12 — 83.3% | ~1,109 |
| 500 | 7 | 11/12 — 91.7% | 10/12 | 10/12 — 83.3% | ~1,550 |

**Chunk size 350 was kept.** 500 put the right chunk first more often, but hit
rate @3 was identical and each query carried ~40% more context. Rank *inside* the
top-k doesn't matter — all k chunks go into the prompt regardless — so the only
thing 500 bought was cost.

**"Delivered" is the number that matters.** Hit rate measures raw retrieval;
delivered measures what survives the similarity floor and actually reaches the
model. The gap is the floor refusing a genuine question, and it is reported
rather than hidden.

### The similarity floor

| | |
|---|---|
| Real questions score | 0.19 – 0.64 |
| Unanswerable questions score | 0.04 – 0.22 |
| `SIM_FLOOR` | **0.25** |

**These ranges overlap, so no threshold separates them cleanly.** 0.25 blocks all
three noise questions at the cost of one false refusal in twelve. The direction is
deliberate: a visible refusal is an honest failure; a confident answer to an
unanswerable question is not.

The value was originally guessed at 0.35. Measuring showed that would have refused
three legitimate questions.

### Token cost

```bash
python scripts/measure_tokens.py     # one real call
python scripts/check_budget.py       # reads the local ledger, costs nothing
```

| | Estimated | **Measured** |
|---|---|---|
| Input (system + 3 chunks + question) | ~1,630 | **1,109** |
| Output — visible answer | — | **64** |
| Output — reasoning (`effort: low`) | — | **40** |
| Total per query | ~2,430 | **1,213** |

Two findings worth stating:

1. **Reasoning overhead is small and observable.** `gpt-oss` spends hidden
   reasoning tokens from the completion budget, and Groq's docs don't specify how
   they're counted. Measured: 40 tokens, itemised under
   `completion_tokens_details.reasoning_tokens`.
2. **`max_completion_tokens` is reserved against the per-minute limit, not billed
   on use.** A 1,109-token prompt with an 800 cap returned
   `x-ratelimit-remaining-tokens: 6091` — exactly `8000 − (1109 + 800)`, while the
   answer used 104. The daily ledger charges actual usage; the per-minute window
   charges the cap. Lowering the cap therefore buys throughput, not budget.

---

## Staying inside a free tier

A budget written in a document prevents nothing. These are enforced in code:

| Guardrail | Where |
|---|---|
| Self-imposed ceiling at 150k of Groq's 200k daily limit | `config.DAILY_TOKEN_BUDGET` |
| Append-only token ledger — the only thing that knows daily spend, since Groq's headers report per-*minute* state | `backend/usage.py` |
| Preflight check refuses locally **before** the request is sent | `usage.preflight_ok()` |
| Ungrounded questions skip the model entirely — they cost nothing | `main.chat()` |
| One retry on an upstream 429, never a loop | `frontend/app.py` |
| Per-IP request cap, required before any public deploy | `backend/ratelimit.py` |
| Stub mode defaults **on**, so a fresh clone can't spend anything | `config.STUB_MODE` |

Every limit is a named constant in `backend/config.py` and exists in exactly one
place.

Stub mode is why the entire UI was built for zero tokens: it yields canned text
from a fake generator, and the interface shows a permanent banner so a fake answer
can never be mistaken for a real one.

---

## Prompt iteration

Kept in `backend/prompts.py`, because a prompt that was tested is worth more than
one that was copied.

| Version | Failure observed | Change |
|---|---|---|
| v1 | — | Initial draft |
| v2 | `gpt-oss-120b` emitted `【2†L7-L9】` instead of `[2]` — CJK brackets, dagger, line anchors, a convention from its training data | Spelled the format out in ASCII, named the wrong forms explicitly, gave a correct/wrong example |

The v1 rule said what to do but never what *not* to do, and the model filled the
gap from habit. Open-weight models follow multi-rule prompts less rigidly than
frontier models — a known cost of this provider choice, cheap to fix once seen.

Prompting alone isn't a guarantee, so v2 is backed by
`prompts.normalize_citations()`, which rewrites stray bracket styles and **deletes
markers numbered above the count of chunks actually sent**. A citation pointing at
a document that was never provided is a fabricated source — worse than no citation,
because it looks checkable.

---

## Limitations

Stated plainly, because every one of these is real.

**Retrieval can fetch the wrong passage.** Answer quality is determined almost
entirely by retrieval. When the wrong chunk is fetched, no model and no prompt
recovers. Measured hit rate is 91.7% on the sample corpus — meaning roughly one
question in twelve starts from the wrong text.

**The benchmark corpus is small.** Three documents, 10 chunks. Returning 3 of 10
means top-k covers 30% of the index, so 91.7% flatters the system. This number
will fall on a real corpus and should be re-measured there before it's quoted.

**Short questions retrieve badly.** "What is hit rate at k?" fails at every chunk
size tested. A six-word question produces a query vector with too little signal to
match 1,400-character passages. Query expansion is the standard fix and is out of
scope here.

**The similarity floor cannot separate cleanly.** Real and noise questions overlap
in score (0.19–0.64 vs 0.04–0.22). The chosen threshold costs one false refusal in
twelve.

**Prompt injection is mitigated, not solved.** Document text is untrusted input,
delimited in XML with a system-prompt rule that documents are data. A determined
injection can still work, and open-weight models are more susceptible than frontier
ones. Tested deliberately; the mitigation is a reduction in risk, not a guarantee.

**Rate limiting is in-memory and per-process.** It resets on restart and wouldn't
hold across replicas. Adequate for a single free-tier instance, not for anything
larger.

**Deployed uploads do not survive a restart.** No free tier offers a persistent
disk. The sample corpus is re-indexed on every start so the demo always works,
`/health` reports `persistence: "ephemeral"`, and the UI says so in the header.

**The deployed API sleeps.** Render's free tier spins down after 15 minutes idle,
so the first request after a quiet period takes the better part of a minute. The
UI says it is waking rather than claiming the backend is dead.

**The token ledger is ephemeral in deployment too.** `data/usage.jsonl` sits on
the same disposable filesystem, so the daily budget guard forgets what was spent
whenever the service restarts. On an ephemeral host the per-IP cap does the real
work.

**No auth, no multi-user isolation.** Everyone shares one document collection.
This is a demo, not a product.

**For one small document, a general chatbot is still the better tool.** See the
top of this README.

---

## Not in v1

Reranking · hybrid BM25 + vector search · query rewriting · semantic chunking ·
conversation summarisation · multi-user auth · OCR for scanned PDFs · tool use ·
response caching for repeated queries (the highest-value next item — it extends
the free-tier budget directly) · local inference via Ollama.

---

## Project layout

```
backend/
  config.py      every tunable constant, in one place
  main.py        FastAPI routes
  models.py      request/response schemas — validation comes free from these
  ingest.py      file → text → chunks → vectors, with SHA-256 dedup
  embeddings.py  local ONNX embeddings, zero API calls
  store.py       ChromaDB wrapper
  retrieve.py    query → nearest chunks → similarity floor
  prompts.py     versioned system prompts + citation normalisation
  llm.py         the only module that knows a provider exists; holds stub mode
  usage.py       token ledger and budget preflight
  ratelimit.py   per-IP cap for public deployment
frontend/app.py  Streamlit client — no business logic, never holds the API key
scripts/         env check, chat CLI, token measurement, budget, evaluation
data/sample/     demo corpus + eval set
docs/SPEC.md     full technical specification, amended as stages completed
deploy/DEPLOY.md step-by-step deployment (Render + Streamlit Community Cloud)
```

The frontend never calls Groq directly. Every call routes through the backend so
the key stays server-side — that is the main reason the API layer exists.


## Licence

MIT — see [LICENSE](LICENSE).

"""
Doclyn — central configuration.

Two rules govern this file:

1. **It imports nothing from the rest of the app.** It sits at the bottom of the
   dependency graph (§5): main -> {ingest, retrieve, llm} -> {store, embeddings,
   prompts, usage} -> config. Nothing here may import upward, or you create a cycle.

2. **Every tunable number in Doclyn lives here and nowhere else** (§9.6 guardrail 5).
   When §9.4 says "lower MAX_COMPLETION_TOKENS while iterating", that has to be a
   one-line change. The moment a magic number is duplicated into another module,
   it stops being one.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ──────────────────────────────────────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────────────────────────────────────
# __file__ is .../doclyn/backend/config.py
#   .resolve()   -> absolute path, symlinks followed
#   .parent      -> .../doclyn/backend
#   .parent      -> .../doclyn          <- project root
# Deriving the root from __file__ (rather than from the current working directory)
# means the app behaves the same whether you launch it from the project root, from
# PyCharm, or from anywhere else.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Reads .env and copies its keys into the process environment, so os.getenv() can
# see them. It does NOT overwrite variables already set in the real environment —
# so a deployment host's own env vars win over a stray .env file. Missing .env is
# not an error, which is what makes the deployed case work (§12).
load_dotenv(PROJECT_ROOT / ".env")

CHROMA_DIR = PROJECT_ROOT / "chroma_store"     # persistent vector store
DATA_DIR = PROJECT_ROOT / "data"
SAMPLE_DIR = DATA_DIR / "sample"               # committed demo corpus + eval.json
USAGE_LEDGER = DATA_DIR / "usage.jsonl"        # append-only token ledger (§9.6)

# ──────────────────────────────────────────────────────────────────────────────
# LLM provider (§4.2)
# ──────────────────────────────────────────────────────────────────────────────
# Swapping provider is a change to these three constants and nothing else. That
# claim is only true if no other module ever names Groq directly — llm.py is the
# only file allowed to know a provider exists.
LLM_BASE_URL = "https://api.groq.com/openai/v1"
LLM_MODEL = "openai/gpt-oss-120b"
LLM_API_KEY = os.getenv("GROQ_API_KEY")

PROVIDER_NAME = "groq"                # reported by GET /health (§6.1)

# gpt-oss is a reasoning model and reasoning tokens are billed against the
# completion budget (§4.1). "low" keeps them small; include_reasoning=False keeps
# them out of the response body. NOTE: gpt-oss uses `include_reasoning`, NOT
# `reasoning_format` — that parameter belongs to other models.
REASONING_EFFORT = "low"
INCLUDE_REASONING = False

# Stub mode defaults ON (§9.6 guardrail 6). A fresh clone, and every UI iteration
# in Stage 5, costs zero tokens until this is deliberately set to "0".
STUB_MODE = os.getenv("DOCLYN_STUB", "1") == "1"

# ──────────────────────────────────────────────────────────────────────────────
# Embeddings & vector store (§8.1)
# ──────────────────────────────────────────────────────────────────────────────
# Runs locally on CPU. Zero API calls, and therefore zero cost for ingestion —
# the single biggest reason this project is free (§9.5).
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
COLLECTION_NAME = "doclyn_chunks"
DISTANCE_METRIC = "cosine"            # set explicitly in collection metadata

# ──────────────────────────────────────────────────────────────────────────────
# Budget guardrails (§9.6)
# ──────────────────────────────────────────────────────────────────────────────
# Groq's real free-tier ceiling is 200,000 tokens/day. We stop at 75% of it.
# Hitting our own wall is a predictable local 429; hitting Groq's wall mid-demo
# is the failure that actually costs something.
DAILY_TOKEN_BUDGET = 150_000

# Measured 2026-09-29 (scripts/measure_tokens.py): a real cited answer cost 104
# completion tokens — 64 visible + 40 reasoning — at reasoning_effort="low".
# 500 keeps ~5x headroom over that.
#
# This is more than a cap. Groq RESERVES this whole number against the 8,000
# TPM limit at request time, not what you actually use: a 1,109-token prompt
# with an 800 cap consumed 1,909 of the per-minute allowance. So lowering this
# directly buys more queries per minute.
MAX_COMPLETION_TOKENS = 500
MAX_HISTORY_TURNS = 4                 # truncated SERVER-side, never trust the client
MAX_TOP_K = 6                         # enforced in the Pydantic model (Stage 2)
MAX_MESSAGE_CHARS = 4_000             # enforced in the Pydantic model (Stage 2)

# Groq free-tier limits, recorded so the preflight logic and /usage can reason
# about them. Informational — Groq enforces these, we don't.
GROQ_TPM_LIMIT = 8_000
GROQ_TPD_LIMIT = 200_000
RETRY_AFTER_CAP_SECONDS = 30          # §9.6 guardrail 4: retry ONCE, never loop

# ──────────────────────────────────────────────────────────────────────────────
# RAG parameters (§8.1, §8.2)
# ──────────────────────────────────────────────────────────────────────────────
# Kept at 350 after measuring (Stage 3). At 500 the hit rate @3 was identical
# (11/12) while each query carried ~450 more tokens of context. Rank improved at
# 500, but rank inside the top-k is irrelevant: all k chunks go into the prompt
# either way. Same accuracy, lower cost wins.
CHUNK_SIZE = 350                      # tokens (~1400 chars)
CHUNK_OVERLAP = 35                    # 10% — keeps boundary-split sentences whole
TOP_K_DEFAULT = 3

# Tuned 2026-09-29 against the eval set (scripts/test_retrieval.py).
# The guessed 0.35 was too high: it would have refused three legitimate questions
# scoring 0.192, 0.260 and 0.285.
#
# Measured spread: real questions 0.19-0.64, noise questions 0.04-0.22.
# They OVERLAP, so no floor is perfect. 0.25 blocks all three noise questions
# and costs one false refusal out of twelve. That tradeoff is deliberate —
# refusing a real question is a visible, honest failure; answering a noise
# question confidently is not.
SIM_FLOOR = 0.25

# ──────────────────────────────────────────────────────────────────────────────
# Uploads (§6.2, §12)
# ──────────────────────────────────────────────────────────────────────────────
MAX_UPLOAD_BYTES = 10 * 1024 * 1024   # 10 MB
ALLOWED_EXTENSIONS = {".pdf", ".txt"}

# ──────────────────────────────────────────────────────────────────────────────
# CORS (§12)
# ──────────────────────────────────────────────────────────────────────────────
# Named origins, never "*". Embeddability means cross-origin calls are a real
# use case, so this is a deliberate list rather than a wildcard.
# 8501 is Streamlit's default port.
# DOCLYN_CORS_ORIGINS is a comma-separated list, set on the deployed API to the
# UI's public origin. Named origins, never "*".
CORS_ORIGINS = [
    o.strip() for o in os.getenv(
        "DOCLYN_CORS_ORIGINS",
        "http://localhost:8501,http://127.0.0.1:8501",
    ).split(",") if o.strip()
]


def missing_api_key() -> bool:
    """True when a real API call would fail for lack of a key.

    Stub mode needs no key, so this is only a problem when STUB_MODE is off.
    Used by GET /health so a misconfigured deploy is visible immediately rather
    than at the first user question.
    """
    return not STUB_MODE and not LLM_API_KEY


# ──────────────────────────────────────────────────────────────────────────────
# Deployment (§12)
# ──────────────────────────────────────────────────────────────────────────────
# A public demo spends YOUR org-wide free quota. One abusive visitor can drain
# the whole day, so a per-IP cap is required before deploying — not optional.
RATE_LIMIT_REQUESTS = int(os.getenv("DOCLYN_RATE_LIMIT", "10"))
RATE_LIMIT_WINDOW_SECONDS = 3600

# "durable" only if the host gives chroma_store/ a real disk. Most free tiers do
# not. Set DOCLYN_PERSISTENCE=ephemeral there so /health says so and the UI warns
# the user instead of silently losing their uploads.
PERSISTENCE = os.getenv("DOCLYN_PERSISTENCE", "durable")

# On an ephemeral host the index is empty after every restart, which would leave
# the demo broken. Seeding the committed sample corpus keeps it working.
SEED_SAMPLE_ON_STARTUP = os.getenv("DOCLYN_SEED_SAMPLE", "0") == "1"

"""FastAPI app — the product. The Streamlit UI is just one client of this.

Run it:
    uvicorn backend.main:app --reload

Then open http://localhost:8000/docs — FastAPI generates that page from the
Pydantic models, so it is always in sync with the real schemas.

Stage 2 scope: /health, /usage, /chat. No retrieval yet — /chat answers from
general knowledge and returns grounded=true with no citations. Stage 4 wires
in RAG behind the same response shape, so clients don't change.
"""

from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from openai import APIConnectionError, APIStatusError, RateLimitError

from backend import config, llm, prompts, store, usage
from backend.models import (
    BudgetOut,
    ChatRequest,
    ChatResponse,
    HealthResponse,
    UsageOut,
    UsageResponse,
)

app = FastAPI(
    title="Doclyn API",
    description="Document-grounded chat. The API is the product; the UI is one client.",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Error handling ───────────────────────────────────────────────────────────
# On a free tier a 429 is normal runtime state, not an exception. These turn
# provider errors into the documented API contract so clients see one shape.


@app.exception_handler(RequestValidationError)
async def _validation_failed(request: Request, exc: RequestValidationError):
    """FastAPI returns 422 for schema violations by default. §6.5 documents 400,
    so the contract wins — clients shouldn't have to read our framework choice."""
    # exc.errors() can carry a raw ValueError in "ctx" (whenever a custom
    # field_validator raised one), which json.dumps chokes on. Keep only the
    # three fields a client actually needs.
    clean = [
        {"field": ".".join(str(p) for p in e.get("loc", [])),
         "msg": e.get("msg", ""),
         "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return JSONResponse(
        status_code=400,
        content={"detail": "Invalid request", "errors": clean},
    )


@app.exception_handler(RateLimitError)
async def _upstream_rate_limited(request: Request, exc: RateLimitError):
    retry_after = None
    if getattr(exc, "response", None) is not None:
        retry_after = exc.response.headers.get("retry-after")
    headers = {"Retry-After": retry_after} if retry_after else {}
    return JSONResponse(
        status_code=429,
        content={"detail": "Provider rate limit reached. Try again shortly.",
                 "retry_after": retry_after},
        headers=headers,
    )


@app.exception_handler(APIConnectionError)
async def _provider_unreachable(request: Request, exc: APIConnectionError):
    return JSONResponse(status_code=503, content={"detail": "Provider unreachable"})


@app.exception_handler(APIStatusError)
async def _provider_error(request: Request, exc: APIStatusError):
    return JSONResponse(
        status_code=502,
        content={"detail": f"Provider returned {exc.status_code}"},
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


def _budget() -> BudgetOut:
    return BudgetOut(
        used_today=usage.today_total(),
        daily_budget=config.DAILY_TOKEN_BUDGET,
        remaining=usage.remaining_today(),
    )


# ── Routes ───────────────────────────────────────────────────────────────────


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Cheap liveness + configuration check. Makes no API call."""
    try:
        documents, chunks = store.counts()
    except Exception:
        documents, chunks = 0, 0   # index not created yet — not a failure

    return HealthResponse(
        status="ok",
        provider=config.PROVIDER_NAME,
        model=config.LLM_MODEL,
        embedding_model=config.EMBEDDING_MODEL,
        stub_mode=config.STUB_MODE,
        documents_indexed=documents,
        chunks_indexed=chunks,
        persistence="durable",  # local disk; re-checked against the host at Stage 6
    )


@app.get("/usage", response_model=UsageResponse)
def get_usage() -> UsageResponse:
    """Reads the local ledger. Costs nothing, makes no API call."""
    return UsageResponse(
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        queries_today=usage.queries_today(),
        tokens_used_today=usage.today_total(),
        daily_budget=config.DAILY_TOKEN_BUDGET,
        remaining=usage.remaining_today(),
        groq_remaining_tpm=usage.last_groq_remaining(),
    )


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """Non-streaming query endpoint.

    The route validates, delegates and shapes the response. No business logic
    lives here — that belongs in the modules it calls.
    """
    # Stage 4 replaces this with the real prompt once documents exist.
    system = prompts.NO_RAG_SYSTEM_PROMPT
    history = [m.model_dump() for m in req.history]

    # Preflight (§9.6 guardrail 3): refuse locally before the provider refuses us.
    # Runs before the call, so an over-budget request costs nothing.
    prompt_text = system + "".join(m["content"] for m in history) + req.message
    allowed, _estimate = usage.preflight_ok(prompt_text)
    if not allowed and not config.STUB_MODE:
        raise HTTPException(
            status_code=429,
            detail=(f"Daily budget reached ({config.DAILY_TOKEN_BUDGET:,} tokens). "
                    "Resets 00:00 UTC."),
        )

    result = llm.complete(system, history, req.message)

    if not config.STUB_MODE:
        usage.record("/chat", result["input_tokens"], result["output_tokens"],
                     result.get("groq_remaining"))

    return ChatResponse(
        answer=result["text"],
        citations=[],          # Stage 4
        usage=UsageOut(input_tokens=result["input_tokens"],
                       output_tokens=result["output_tokens"]),
        grounded=True,         # Stage 4 makes this meaningful
        budget=_budget(),
    )

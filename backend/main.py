"""FastAPI app — the product. The Streamlit UI is just one client of this.

Run it:
    uvicorn backend.main:app --reload

Docs at http://localhost:8000/docs, generated from the Pydantic models, so it
is always in sync with the real schemas.
"""

import json
from datetime import datetime, timezone
from pathlib import PurePath

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from openai import APIConnectionError, APIStatusError, RateLimitError

from backend import config, ingest, llm, prompts, retrieve, store, usage
from backend.models import (
    BudgetOut,
    ChatRequest,
    ChatResponse,
    Citation,
    DocumentInfo,
    DocumentListResponse,
    DocumentUploadResponse,
    HealthResponse,
    UsageOut,
    UsageResponse,
)

app = FastAPI(
    title="Doclyn API",
    description="Document-grounded chat. The API is the product; the UI is one client.",
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

SNIPPET_CHARS = 220


# ── Error handling ───────────────────────────────────────────────────────────


@app.exception_handler(RequestValidationError)
async def _validation_failed(request: Request, exc: RequestValidationError):
    """FastAPI returns 422 for schema violations by default. §6.5 documents 400,
    so the contract wins — clients shouldn't have to read our framework choice."""
    clean = [
        {"field": ".".join(str(p) for p in e.get("loc", [])),
         "msg": e.get("msg", ""),
         "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return JSONResponse(status_code=400,
                        content={"detail": "Invalid request", "errors": clean})


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
    return JSONResponse(status_code=502,
                        content={"detail": f"Provider returned {exc.status_code}"})


@app.exception_handler(ingest.IngestError)
async def _ingest_failed(request: Request, exc: ingest.IngestError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ── Helpers ──────────────────────────────────────────────────────────────────


def _budget() -> BudgetOut:
    return BudgetOut(
        used_today=usage.today_total(),
        daily_budget=config.DAILY_TOKEN_BUDGET,
        remaining=usage.remaining_today(),
    )


def _known_document_ids() -> set[str]:
    return {d["document_id"] for d in store.list_documents()}


# ── Health & usage ───────────────────────────────────────────────────────────


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


# ── Documents ────────────────────────────────────────────────────────────────


@app.post("/documents", response_model=DocumentUploadResponse, status_code=201)
async def upload_document(response: Response,
                          file: UploadFile = File(...)) -> DocumentUploadResponse:
    """Ingest one document. Never calls the LLM — cannot be rate limited, costs nothing.

    Returns 201 for a new document, 200 for one already indexed.
    """
    # Take the basename only. A filename is client-supplied text and could
    # contain path separators.
    filename = PurePath(file.filename or "upload").name
    if PurePath(filename).suffix.lower() not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Only .pdf and .txt are supported")

    data = await file.read()
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File exceeds 10 MB limit")
    if not data:
        raise HTTPException(400, "No extractable text found; OCR is not supported in v1")

    try:
        result = ingest.ingest_document(filename, data)
    except ingest.IngestError:
        raise
    except Exception as exc:
        raise HTTPException(500, "Ingestion failed") from exc

    # A duplicate is not an error — the document is already there and usable.
    if result["duplicate"]:
        response.status_code = 200

    return DocumentUploadResponse(**result)


@app.get("/documents", response_model=DocumentListResponse)
def list_documents() -> DocumentListResponse:
    return DocumentListResponse(
        documents=[DocumentInfo(**d) for d in store.list_documents()]
    )


@app.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: str) -> Response:
    if not store.delete_document(document_id):
        raise HTTPException(404, "Unknown document_id")
    return Response(status_code=204)


# ── Chat ─────────────────────────────────────────────────────────────────────


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """Query endpoint, non-streaming.

    Order matters here and is the whole design:
      retrieve -> floor check -> (maybe stop) -> budget preflight -> call -> record

    The two cheapest outcomes come first. An ungrounded question and an
    over-budget request both return without spending a single token.
    """
    if req.document_ids:
        unknown = set(req.document_ids) - _known_document_ids()
        if unknown:
            raise HTTPException(404, f"Unknown document_id: {', '.join(sorted(unknown))}")

    chunks, grounded = retrieve.retrieve(req.message, req.top_k, req.document_ids)

    # Nothing cleared the similarity floor. Refuse WITHOUT calling the model:
    # correct behaviour and a free saving at the same time.
    if not grounded:
        return ChatResponse(
            answer=prompts.REFUSAL_MESSAGE,
            citations=[],
            usage=UsageOut(input_tokens=0, output_tokens=0),
            grounded=False,
            budget=_budget(),
        )

    context_block = prompts.format_context_block(chunks)
    user_content = context_block + "\n\n" + req.message
    # Trim first: the preflight below must estimate the prompt that actually
    # gets sent, not the full history the client happened to include.
    history = llm.trim_history([m.model_dump() for m in req.history])

    # Preflight (§9.6 guardrail 3): refuse locally before the provider refuses us.
    prompt_text = prompts.SYSTEM_PROMPT + "".join(m["content"] for m in history) + user_content
    allowed, _estimate = usage.preflight_ok(prompt_text)
    if not allowed and not config.STUB_MODE:
        raise HTTPException(
            status_code=429,
            detail=(f"Daily budget reached ({config.DAILY_TOKEN_BUDGET:,} tokens). "
                    "Resets 00:00 UTC."),
        )

    result = llm.complete(prompts.SYSTEM_PROMPT, history, user_content)

    if not config.STUB_MODE:
        usage.record("/chat", result["input_tokens"], result["output_tokens"],
                     result.get("groq_remaining"))

    # marker matches the index= attribute in the context block, so [1] in the
    # answer text lines up with citations[0] without parsing the reply.
    citations = [
        Citation(
            marker=i,
            document_id=c["metadata"]["document_id"],
            filename=c["metadata"].get("filename", ""),
            page=c["metadata"].get("page"),
            chunk_id=c["chunk_id"],
            snippet=c["text"][:SNIPPET_CHARS].strip() +
                    ("..." if len(c["text"]) > SNIPPET_CHARS else ""),
            score=c["score"],
        )
        for i, c in enumerate(chunks, start=1)
    ]

    return ChatResponse(
        # Rewrite stray citation styles and drop markers pointing at documents
        # that were never sent (§8.4 v2).
        answer=prompts.normalize_citations(result["text"], max_marker=len(citations)),
        citations=citations,
        usage=UsageOut(input_tokens=result["input_tokens"],
                       output_tokens=result["output_tokens"]),
        grounded=True,
        budget=_budget(),
    )


# ── Streaming chat ───────────────────────────────────────────────────────────


def _sse(event: str, payload: dict) -> str:
    """One server-sent event. The blank line at the end is the delimiter and is
    not optional — without it the client never sees the message."""
    return f"event: {event}\ndata: {json.dumps(payload)}\n\n"


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    """Same request shape as /chat, delivered as server-sent events (§6.7).

    Citations are sent FIRST, before any token, because they are already known
    at retrieval time. The UI can render the sources panel while the answer is
    still typing.
    """
    if req.document_ids:
        unknown = set(req.document_ids) - _known_document_ids()
        if unknown:
            raise HTTPException(404, f"Unknown document_id: {', '.join(sorted(unknown))}")

    chunks, grounded = retrieve.retrieve(req.message, req.top_k, req.document_ids)

    def refusal_stream():
        yield _sse("citations", {"citations": [], "grounded": False})
        yield _sse("token", {"text": prompts.REFUSAL_MESSAGE})
        yield _sse("done", {"usage": {"input_tokens": 0, "output_tokens": 0},
                            "answer": prompts.REFUSAL_MESSAGE,
                            "budget": _budget().model_dump()})

    if not grounded:
        return StreamingResponse(refusal_stream(), media_type="text/event-stream")

    citations = [
        Citation(
            marker=i,
            document_id=c["metadata"]["document_id"],
            filename=c["metadata"].get("filename", ""),
            page=c["metadata"].get("page"),
            chunk_id=c["chunk_id"],
            snippet=c["text"][:SNIPPET_CHARS].strip() +
                    ("..." if len(c["text"]) > SNIPPET_CHARS else ""),
            score=c["score"],
        )
        for i, c in enumerate(chunks, start=1)
    ]

    user_content = prompts.format_context_block(chunks) + "\n\n" + req.message
    history = llm.trim_history([m.model_dump() for m in req.history])

    prompt_text = prompts.SYSTEM_PROMPT + "".join(m["content"] for m in history) + user_content
    allowed, _estimate = usage.preflight_ok(prompt_text)

    def event_stream():
        yield _sse("citations",
                   {"citations": [c.model_dump() for c in citations], "grounded": True})

        if not allowed and not config.STUB_MODE:
            # Local budget wall. Distinct from an upstream 429 because waiting
            # will not fix it — nothing resets until 00:00 UTC.
            yield _sse("error", {
                "code": 429,
                "detail": (f"Daily budget reached ({config.DAILY_TOKEN_BUDGET:,} tokens). "
                           "Resets 00:00 UTC."),
                "retry_after": None,
            })
            return

        collected, usage_out = [], {}
        try:
            for piece in llm.stream_answer(prompts.SYSTEM_PROMPT, history,
                                           user_content, usage_out):
                collected.append(piece)
                yield _sse("token", {"text": piece})
        except RateLimitError as exc:
            retry_after = None
            if getattr(exc, "response", None) is not None:
                retry_after = exc.response.headers.get("retry-after")
            yield _sse("error", {"code": 429, "detail": "Provider rate limit reached.",
                                 "retry_after": retry_after})
            return
        except APIConnectionError:
            yield _sse("error", {"code": 503, "detail": "Provider unreachable",
                                 "retry_after": None})
            return

        if not config.STUB_MODE and usage_out:
            usage.record("/chat/stream", usage_out.get("input_tokens", 0),
                         usage_out.get("output_tokens", 0), usage_out.get("groq_remaining"))

        # Tokens went out raw, because normalising mid-stream would mean holding
        # text back and losing the point of streaming. The cleaned answer rides
        # along in `done`, and the client swaps it in once the stream ends.
        yield _sse("done", {
            "usage": {"input_tokens": usage_out.get("input_tokens", 0),
                      "output_tokens": usage_out.get("output_tokens", 0)},
            "answer": prompts.normalize_citations("".join(collected),
                                                  max_marker=len(citations)),
            "budget": _budget().model_dump(),
        })

    return StreamingResponse(event_stream(), media_type="text/event-stream")

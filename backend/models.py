"""Request and response schemas.

These are the public shape of the API. They are deliberately separate from the
internal functions: changing how retrieval works internally must not change what
a client sees.

Pydantic turns each of these into validation for free — a bad request is
rejected with a 422/400 before any of our code runs, and before any tokens
are spent.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.config import MAX_MESSAGE_CHARS, MAX_TOP_K, TOP_K_DEFAULT

# ── Requests ─────────────────────────────────────────────────────────────────


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_CHARS)
    history: list[ChatMessage] = Field(default_factory=list)
    top_k: int = Field(default=TOP_K_DEFAULT, ge=1, le=MAX_TOP_K)
    document_ids: list[str] | None = None

    @field_validator("message")
    @classmethod
    def not_just_whitespace(cls, v: str) -> str:
        # min_length=1 rejects "" but accepts "   ". Strip, then re-check.
        v = v.strip()
        if not v:
            raise ValueError("message cannot be empty")
        return v


# ── Response pieces ──────────────────────────────────────────────────────────


class Citation(BaseModel):
    marker: int
    document_id: str
    filename: str
    page: int | None = None
    chunk_id: str
    snippet: str
    score: float


class UsageOut(BaseModel):
    """Provider-neutral names. Groq returns prompt_tokens/completion_tokens;
    llm.py renames them here so the public API doesn't leak provider details."""

    input_tokens: int = 0
    output_tokens: int = 0


class BudgetOut(BaseModel):
    used_today: int
    daily_budget: int
    remaining: int


# ── Responses ────────────────────────────────────────────────────────────────


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    usage: UsageOut
    grounded: bool
    budget: BudgetOut


class HealthResponse(BaseModel):
    status: str
    provider: str
    model: str
    embedding_model: str
    stub_mode: bool
    documents_indexed: int
    chunks_indexed: int
    persistence: Literal["durable", "ephemeral"]


class UsageResponse(BaseModel):
    date: str
    queries_today: int
    tokens_used_today: int
    daily_budget: int
    remaining: int
    groq_remaining_tpm: int | None = None


class DocumentInfo(BaseModel):
    document_id: str
    filename: str
    pages: int
    chunks: int
    ingested_at: str | None = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    content_hash: str
    pages: int
    chunks_created: int
    duplicate: bool
    ingested_at: str | None = None

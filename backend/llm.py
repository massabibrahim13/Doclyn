"""The only module that knows a provider exists.

Everything else in the app talks to complete() and stream_answer(). Swapping
Groq for something else means changing config's three LLM_* constants and
nothing here or above.

Also holds stub mode: canned answers, no network, no quota. On by default.
"""

import time
from typing import Iterator

from openai import OpenAI

from backend import config

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Built once, on first use. Not at import time — that would make a missing
    API key crash the whole app even in stub mode."""
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)
    return _client


def build_messages(system: str, history: list[dict], user_content: str) -> list[dict]:
    """system + trimmed history + the new question.

    History is trimmed HERE, server-side. The client sends whatever it likes;
    we never trust it to have limited itself, because a careless client would
    spend our quota.
    """
    trimmed = history[-(config.MAX_HISTORY_TURNS * 2):] if history else []
    return (
        [{"role": "system", "content": system}]
        + trimmed
        + [{"role": "user", "content": user_content}]
    )


# ── Stub mode ────────────────────────────────────────────────────────────────

_STUB_TEXT = (
    "This is a canned answer from stub mode. No model was called and no tokens "
    "were spent. Set DOCLYN_STUB=0 in .env to get real answers [1]."
)


def _stub_complete() -> dict:
    time.sleep(0.4)
    return {"text": _STUB_TEXT, "input_tokens": 0, "output_tokens": 0, "groq_remaining": None}


def _stub_stream() -> Iterator[str]:
    for word in _STUB_TEXT.split(" "):
        time.sleep(0.03)
        yield word + " "


# ── Real calls ───────────────────────────────────────────────────────────────


def _extra_body() -> dict:
    """reasoning_effort and include_reasoning are Groq extensions, not part of
    the OpenAI schema, so they go through extra_body rather than as kwargs."""
    return {
        "reasoning_effort": config.REASONING_EFFORT,
        "include_reasoning": config.INCLUDE_REASONING,
    }


def _remaining_tokens_header(headers) -> int | None:
    raw = headers.get("x-ratelimit-remaining-tokens")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def complete(system: str, history: list[dict], user_content: str) -> dict:
    """One non-streaming call. Returns provider-neutral field names."""
    if config.STUB_MODE:
        return _stub_complete()

    raw = _get_client().chat.completions.with_raw_response.create(
        model=config.LLM_MODEL,
        messages=build_messages(system, history, user_content),
        max_completion_tokens=config.MAX_COMPLETION_TOKENS,
        extra_body=_extra_body(),
    )
    resp = raw.parse()
    u = resp.usage

    return {
        "text": resp.choices[0].message.content or "",
        "finish_reason": resp.choices[0].finish_reason,
        # Rename at the boundary: prompt/completion is OpenAI's vocabulary,
        # input/output is ours.
        "input_tokens": u.prompt_tokens,
        "output_tokens": u.completion_tokens,
        "groq_remaining": _remaining_tokens_header(raw.headers),
    }


def stream_answer(system: str, history: list[dict], user_content: str) -> Iterator[str]:
    """Yields text fragments as they arrive. Used by /chat/stream in Stage 5.

    Note: in streaming mode the usage object only arrives in the FINAL chunk,
    which is why the SSE contract sends usage in a separate `done` event.
    """
    if config.STUB_MODE:
        yield from _stub_stream()
        return

    stream = _get_client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=build_messages(system, history, user_content),
        max_completion_tokens=config.MAX_COMPLETION_TOKENS,
        stream=True,
        stream_options={"include_usage": True},
        extra_body=_extra_body(),
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

"""Token ledger.

Every real API call appends one line to data/usage.jsonl. That file is the only
thing that can answer "how much of today's budget have I spent?" — Groq's
response headers report tokens left this MINUTE, not this day.

Used by: the preflight check in /chat, GET /usage, and scripts/check_budget.py.
"""

import json
from datetime import datetime, timezone
from typing import Any

# Imported as a module, not by name: `from config import X` freezes X at import
# time, so changing a limit for a test (or at runtime) would silently do nothing.
from backend import config
from backend.config import USAGE_LEDGER


def _today() -> str:
    """Today's date in UTC. Groq's daily quota resets at 00:00 UTC, not local midnight."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def record(
    endpoint: str,
    input_tokens: int,
    output_tokens: int,
    groq_remaining_tokens: int | None = None,
) -> None:
    """Append one call to the ledger. Never raises — accounting must not break a request."""
    try:
        USAGE_LEDGER.parent.mkdir(parents=True, exist_ok=True)
        line = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "endpoint": endpoint,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "groq_remaining_tokens": groq_remaining_tokens,
        }
        with USAGE_LEDGER.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line) + "\n")
    except OSError:
        pass


def today_entries() -> list[dict[str, Any]]:
    """Every ledger line from today (UTC). Skips corrupt lines rather than crashing."""
    if not USAGE_LEDGER.exists():
        return []
    today, rows = _today(), []
    with USAGE_LEDGER.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(row.get("ts", "")).startswith(today):
                rows.append(row)
    return rows


def today_total() -> int:
    """Total tokens spent today, input + output."""
    return sum(r.get("input_tokens", 0) + r.get("output_tokens", 0) for r in today_entries())


def queries_today() -> int:
    return len(today_entries())


def remaining_today() -> int:
    return max(0, config.DAILY_TOKEN_BUDGET - today_total())


def last_groq_remaining() -> int | None:
    """Tokens Groq said were left this minute, from the most recent call."""
    for row in reversed(today_entries()):
        if row.get("groq_remaining_tokens") is not None:
            return row["groq_remaining_tokens"]
    return None


def estimate_tokens(text: str) -> int:
    """Rough token count: about 4 characters per token, always rounded UP.

    Deliberately crude. A real tokenizer would be another dependency for a number
    that only has to be good enough to refuse a request before it's sent.
    """
    return -(-len(text) // 4)


def preflight_ok(prompt_text: str) -> tuple[bool, int]:
    """Would this request fit inside today's remaining budget?

    Returns (allowed, estimated_cost). Assumes the worst case: the full
    completion cap gets used. Better to refuse a request that would have fit
    than to allow one that doesn't.
    """
    estimate = estimate_tokens(prompt_text) + config.MAX_COMPLETION_TOKENS
    return (today_total() + estimate <= config.DAILY_TOKEN_BUDGET), estimate

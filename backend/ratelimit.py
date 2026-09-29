"""Per-IP request cap for the public demo (§12).

`DAILY_TOKEN_BUDGET` protects the day in aggregate; this stops one visitor
consuming all of it. Both are needed: without this, a single script pointed at
the demo URL drains the quota in minutes and every other visitor sees errors.

In-memory and per-process on purpose. It resets on restart and would not hold
across multiple replicas — fine for a single free-tier instance, and honestly
stated in the README rather than pretended otherwise.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from backend.config import RATE_LIMIT_REQUESTS, RATE_LIMIT_WINDOW_SECONDS

_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    """Behind a proxy the socket address is the proxy's, so prefer the
    forwarded header. It is client-controllable, which makes this a speed bump
    rather than a security control — the token budget is the real backstop."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce(request: Request) -> None:
    """FastAPI dependency. Raises 429 once an IP exceeds its window allowance."""
    ip = _client_ip(request)
    now = time.time()
    window = _hits[ip]

    while window and now - window[0] > RATE_LIMIT_WINDOW_SECONDS:
        window.popleft()

    if len(window) >= RATE_LIMIT_REQUESTS:
        retry_after = int(RATE_LIMIT_WINDOW_SECONDS - (now - window[0])) + 1
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Try again in {retry_after // 60 + 1} minute(s).",
            headers={"Retry-After": str(retry_after)},
        )

    window.append(now)

    # Keep the dict from growing without bound on a long-lived process.
    if len(_hits) > 10_000:
        for key in [k for k, v in _hits.items() if not v]:
            del _hits[key]

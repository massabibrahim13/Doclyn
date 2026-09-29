"""Stage 1 — a terminal chatbot. No RAG, no FastAPI.

Run it:
    python scripts\\chat_cli.py

See why conversation memory has to be built by hand:
    python scripts\\chat_cli.py --no-memory

Requires DOCLYN_STUB=0 in .env, because this makes real calls to Groq.
"""

import sys
from pathlib import Path

# Running `python scripts\chat_cli.py` puts scripts/ on the import path, not the
# project root — so `from backend import config` would fail. This fixes that.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openai import OpenAI  # noqa: E402

from backend import config  # noqa: E402

# When True, we deliberately DON'T store the model's replies, to demonstrate
# that the conversation memory is entirely our own doing.
NO_MEMORY = "--no-memory" in sys.argv

# ──────────────────────────────────────────────────────────────────────────────
# Guards — fail loudly and early rather than confusingly later
# ──────────────────────────────────────────────────────────────────────────────
if config.STUB_MODE:
    print("DOCLYN_STUB is 1, so no real call would be made.")
    print("Open .env, set DOCLYN_STUB=0, then run this again.")
    sys.exit(1)

if not config.LLM_API_KEY:
    print("No GROQ_API_KEY found. Check .env at the project root.")
    sys.exit(1)

# ──────────────────────────────────────────────────────────────────────────────
# Setup
# ──────────────────────────────────────────────────────────────────────────────
# The OpenAI client is just an HTTP client with auth and JSON parsing attached.
# Pointing base_url at Groq is the entire "provider swap". No OpenAI account
# is involved and nothing is billed to OpenAI.
client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)

SYSTEM_PROMPT = "You are a concise, friendly assistant. Keep answers to 2-3 sentences."

# ★ THIS LIST IS THE ENTIRE MEMORY OF THE CONVERSATION. ★
# Groq stores nothing between requests. Whatever is in this list at the moment
# we call the API is the complete extent of what the model knows.
messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

session_input = 0      # running totals, so you can watch the cost of "memory"
session_output = 0


def ask(messages: list[dict]):
    """Send the WHOLE conversation and return the raw response object."""
    return client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        max_completion_tokens=config.MAX_COMPLETION_TOKENS,
        # reasoning_effort and include_reasoning are Groq extensions, not part of
        # the standard OpenAI schema. extra_body passes them straight through —
        # this is the normal way to send provider-specific params through an
        # OpenAI-compatible client.
        extra_body={
            "reasoning_effort": config.REASONING_EFFORT,
            "include_reasoning": config.INCLUDE_REASONING,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# The loop
# ──────────────────────────────────────────────────────────────────────────────
print(f"Doclyn CLI — {config.LLM_MODEL} via {config.PROVIDER_NAME}")
if NO_MEMORY:
    print("!! --no-memory: assistant replies are NOT being stored.")
print("Type 'quit' to exit.\n")

while True:
    # 1. Read a line. Ctrl+C or Ctrl+Z exits cleanly rather than with a traceback.
    try:
        user_text = input("you: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        break

    if not user_text:
        continue
    if user_text.lower() in {"quit", "exit"}:
        break

    # 2. Append the user's turn to the list.
    messages.append({"role": "user", "content": user_text})

    # 3. Send the entire list. Every turn re-sends everything before it —
    #    that resending IS the memory, and it is what costs tokens.
    try:
        resp = ask(messages)
    except Exception as e:
        # On a free tier a 429 is a normal runtime state, not a crash (§4.1).
        # Stage 1 just reports it; §9.6's one-retry rule arrives in Stage 4.
        print(f"[error] {type(e).__name__}: {e}\n")
        messages.pop()          # drop the turn we failed to answer
        continue

    reply = resp.choices[0].message.content
    finish = resp.choices[0].finish_reason
    usage = resp.usage

    # 4. gpt-oss spends hidden reasoning tokens out of the SAME completion
    #    budget as the visible answer (§4.1). If reasoning eats all of it,
    #    the content comes back empty. Worth catching explicitly — it looks
    #    like a model failure but it's a config one.
    if not reply:
        print(f"[empty reply — finish_reason={finish}. "
              f"Reasoning likely consumed the {config.MAX_COMPLETION_TOKENS}-token budget.]")
    else:
        print(f"bot: {reply}")

    if finish == "length":
        print("[truncated — hit max_completion_tokens]")

    # 5. Watch the numbers. input_tokens climbing faster than your questions are
    #    getting longer is the cost of conversation history.
    session_input += usage.prompt_tokens
    session_output += usage.completion_tokens
    print(f"     finish={finish}  in={usage.prompt_tokens} out={usage.completion_tokens}"
          f"  | session total={session_input + session_output}\n")

    # 6. Append the reply, so the next call includes it. THIS is the memory.
    #    Skipping it is what --no-memory demonstrates.
    if not NO_MEMORY:
        messages.append({"role": "assistant", "content": reply or ""})

print(f"\nSession totals — in: {session_input}  out: {session_output}  "
      f"total: {session_input + session_output}")
print(f"Daily budget is {config.DAILY_TOKEN_BUDGET:,} tokens.")

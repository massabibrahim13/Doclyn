"""Doclyn — Streamlit UI.

    streamlit run frontend/app.py

This is ONE CLIENT of the API, not the product. It holds no business logic and
no API key: every decision (what is grounded, what a citation is, whether the
budget allows a call) is made by the backend and simply rendered here.

The six states in §7.3 are the point of this file. If a refusal looks like a
normal answer, the grounding guarantee is invisible and therefore worthless.
"""

import json
import os
import time

import httpx
import streamlit as st

# ── Configuration, before anything else ──────────────────────────────────────
# Streamlit Community Cloud supplies configuration through st.secrets, but
# backend.config reads os.environ at IMPORT time. So secrets have to land in the
# environment before any backend module is imported — hence this sitting above
# every other import rather than in a tidy function further down.
try:
    for _key, _value in st.secrets.items():
        if isinstance(_value, str):
            os.environ.setdefault(_key, _value)
except Exception:
    pass   # no secrets file locally, which is fine

# Streamlit Community Cloud can only run a Streamlit app, so on that host the
# API runs inside this same process on loopback rather than as its own service.
# The separation still holds — it is the same ASGI app, reached over HTTP, and
# this file still contains no business logic.
EMBEDDED_API = os.getenv("DOCLYN_EMBEDDED_API", "0") == "1"

@st.cache_resource(show_spinner="Starting Doclyn…")
def _start_embedded_api() -> str:
    """Run the FastAPI app in a background thread and wait for it to answer.

    cache_resource means this happens once per process, not on every rerun —
    Streamlit re-executes this whole file on every interaction, and starting a
    second server on the same port would fail on the first click.
    """
    import threading

    import uvicorn

    from backend.main import app as api_app

    server = uvicorn.Server(uvicorn.Config(
        api_app, host="127.0.0.1", port=8000, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()

    for _ in range(90):
        try:
            if httpx.get("http://127.0.0.1:8000/health", timeout=2).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(1)
    return "http://127.0.0.1:8000"


def _api_url() -> str:
    if EMBEDDED_API:
        return _start_embedded_api()
    return os.getenv("DOCLYN_API", "http://localhost:8000")


API = _api_url()
TIMEOUT = 120.0
# Render's free tier spins the service down after 15 minutes idle, and a cold
# start takes the better part of a minute. A 10s health timeout would report a
# perfectly healthy backend as dead.
HEALTH_TIMEOUT = 30.0
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

st.set_page_config(page_title="Doclyn", page_icon="📄", layout="wide")

st.markdown("""
<style>
  .doclyn-head { display:flex; align-items:center; gap:.6rem; flex-wrap:wrap;
                 font-size:.85rem; color:#8a8f98; margin-bottom:.4rem; }
  .doclyn-head .title { font-size:1.35rem; font-weight:650; color:inherit;
                        margin-right:.5rem; }
  .dot { width:.55rem; height:.55rem; border-radius:50%; display:inline-block; }
  .dot.ok { background:#2ea043; } .dot.bad { background:#d1242f; }
  .pill { border:1px solid #33363d; border-radius:999px; padding:.1rem .55rem; }
  .pill.warn { border-color:#9a6700; color:#d4a72c; }
  /* State 2: a refusal must never be mistakable for an answer. */
  .refusal { border-left:3px solid #6e7681; background:rgba(110,118,129,.08);
             padding:.6rem .85rem; border-radius:.3rem; color:#8a8f98;
             font-style:italic; }
</style>
""", unsafe_allow_html=True)


# ── API client ───────────────────────────────────────────────────────────────

def api_get(path: str):
    try:
        r = httpx.get(f"{API}{path}", timeout=HEALTH_TIMEOUT)
        return r.json() if r.status_code == 200 else None
    except httpx.HTTPError:
        return None


def sse(payload: dict):
    """Consume the SSE stream, yielding (event_name, data) pairs.

    An SSE message is 'event: <name>' then 'data: <json>' then a blank line.
    """
    with httpx.stream("POST", f"{API}/chat/stream", json=payload, timeout=TIMEOUT) as r:
        if r.status_code >= 400:
            r.read()
            yield "error", {"code": r.status_code, "detail": r.text, "retry_after": None}
            return
        event = None
        for line in r.iter_lines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: ") and event:
                yield event, json.loads(line[6:])


# ── State ────────────────────────────────────────────────────────────────────

st.session_state.setdefault("messages", [])       # {role, content, citations, grounded}
st.session_state.setdefault("selected", {})       # document_id -> bool
st.session_state.setdefault("confirm_delete", None)
st.session_state.setdefault("budget_exhausted", False)

health = api_get("/health")
online = health is not None
usage = api_get("/usage") if online else None


# ── Header (§7.4) ────────────────────────────────────────────────────────────

bits = ['<div class="doclyn-head"><span class="title">Doclyn</span>']
bits.append(f'<span class="dot {"ok" if online else "bad"}"></span>')
if online:
    bits.append(f'<span>{health["model"].split("/")[-1]} · {health["provider"]}</span>')
    if usage:
        left = usage["remaining"]
        pct = left / max(1, usage["daily_budget"])
        cls = "pill warn" if pct < 0.2 else "pill"
        bits.append(f'<span class="{cls}">{left // 1000}k left</span>')
    if health["persistence"] == "ephemeral":
        bits.append('<span class="pill warn">Uploads reset on restart</span>')
else:
    bits.append("<span>backend offline</span>")
bits.append("</div>")
st.markdown("".join(bits), unsafe_allow_html=True)

# State 6 — stub mode. Non-negotiable: a fake answer shown as real misleads
# anyone watching the demo.
if online and health["stub_mode"]:
    st.warning("Demo mode — answers are canned, no model is being called.", icon="🧪")

# State 5 — backend unreachable. A dead backend must be obvious, not a chat box
# that silently swallows input.
if not online:
    if "localhost" in API or "127.0.0.1" in API:
        st.error("Backend not responding. Start it with "
                 "`uvicorn backend.main:app --reload`.", icon="🔌")
    else:
        st.error("Backend not responding. On a free tier it sleeps after 15 "
                 "minutes idle — give it a minute and refresh.", icon="😴")


# ── Sidebar (§7.2) ───────────────────────────────────────────────────────────

with st.sidebar:
    st.subheader("Documents")

    if online:
        upload = st.file_uploader("Upload", type=["pdf", "txt"],
                                  label_visibility="collapsed")
        if upload is not None:
            data = upload.getvalue()
            if len(data) > MAX_UPLOAD_BYTES:
                st.error("File exceeds 10 MB limit.")
            else:
                key = f"sent::{upload.name}::{len(data)}"
                if not st.session_state.get(key):
                    with st.spinner("Indexing..."):
                        r = httpx.post(f"{API}/documents",
                                       files={"file": (upload.name, data)},
                                       timeout=TIMEOUT)
                    st.session_state[key] = True
                    if r.status_code in (200, 201):
                        body = r.json()
                        if body["duplicate"]:
                            st.info("Already indexed — not re-uploaded.")
                        else:
                            st.success(f"{body['chunks_created']} chunks indexed.")
                        st.rerun()
                    else:
                        st.error(r.json().get("detail", "Upload failed"))

        docs = (api_get("/documents") or {}).get("documents", [])

        if not docs:
            st.caption("No documents yet — upload one to get started.")
        else:
            st.caption("Tick to limit questions to specific documents.")
            for d in docs:
                did = d["document_id"]
                st.session_state.selected.setdefault(did, True)
                row, btn = st.columns([5, 1])
                with row:
                    st.session_state.selected[did] = st.checkbox(
                        d["filename"], value=st.session_state.selected[did], key=f"cb_{did}"
                    )
                    st.caption(f"{d['pages']} page(s) · {d['chunks']} chunks")
                with btn:
                    if st.button("✕", key=f"del_{did}", help="Delete"):
                        st.session_state.confirm_delete = did
                        st.rerun()

                if st.session_state.confirm_delete == did:
                    st.warning(f"Delete **{d['filename']}** and all its chunks?")
                    yes, no = st.columns(2)
                    if yes.button("Delete", key=f"y_{did}", type="primary"):
                        httpx.delete(f"{API}/documents/{did}", timeout=TIMEOUT)
                        st.session_state.confirm_delete = None
                        st.session_state.selected.pop(did, None)
                        st.rerun()
                    if no.button("Cancel", key=f"n_{did}"):
                        st.session_state.confirm_delete = None
                        st.rerun()

        if st.session_state.messages and st.button("Clear conversation"):
            st.session_state.messages = []
            st.rerun()


# ── Transcript ───────────────────────────────────────────────────────────────

def render_citations(citations: list[dict]) -> None:
    """Every claim is checkable. This is what separates Doclyn from a chatbot."""
    if not citations:
        return
    st.caption("Sources")
    for c in citations:
        page = f" · p.{c['page']}" if c.get("page") else ""
        with st.expander(f"[{c['marker']}] {c['filename']}{page} · score {c['score']:.2f}"):
            st.write(c["snippet"])
            st.caption(f"chunk `{c['chunk_id']}`")


for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("grounded") is False:
            # State 2 — ungrounded refusal, deliberately styled apart.
            st.markdown(f'<div class="refusal">🔍 {msg["content"]}</div>',
                        unsafe_allow_html=True)
        else:
            st.markdown(msg["content"])
            render_citations(msg.get("citations", []))


# ── Composer ─────────────────────────────────────────────────────────────────

doc_count = len(st.session_state.selected) if online else 0
blocked = (not online) or st.session_state.budget_exhausted or doc_count == 0

if st.session_state.budget_exhausted:
    # State 4 — local budget wall. Distinct from a rate limit, because waiting
    # does not help: nothing resets until 00:00 UTC.
    st.error("Daily token budget reached. Resets at 00:00 UTC.", icon="🛑")

placeholder = ("Backend not responding." if not online
               else "Daily budget reached." if st.session_state.budget_exhausted
               else "Upload a document first." if doc_count == 0
               else "Ask a question…")

question = st.chat_input(placeholder, disabled=blocked)


def ask(question: str, retried: bool = False) -> None:
    """Send one question and render the streamed reply."""
    selected = [d for d, on in st.session_state.selected.items() if on] or None

    # messages[-1] is the question being asked right now. Including it here as
    # well would send it twice: once as `message`, once as the last history turn.
    payload = {
        "message": question,
        "history": [{"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages[:-1]],
        "document_ids": selected,
    }

    citations, grounded, parts, final = [], True, [], None
    saw_event = False

    with st.chat_message("assistant"):
        slot = st.empty()
        cite_slot = st.container()
        slot.markdown("_thinking…_")

        try:
            stream = sse(payload)
        except httpx.HTTPError as exc:
            slot.error(f"Could not reach the backend: {exc}", icon="🔌")
            return

        for event, data in stream:
            saw_event = True
            if event == "citations":
                citations = data.get("citations", [])
                grounded = data.get("grounded", True)
                if grounded:
                    with cite_slot:
                        render_citations(citations)

            elif event == "token":
                parts.append(data["text"])
                text = "".join(parts)
                if grounded:
                    slot.markdown(text + "▌")
                else:
                    slot.markdown(f'<div class="refusal">🔍 {text}</div>',
                                  unsafe_allow_html=True)

            elif event == "done":
                # The backend sends a cleaned copy of the answer; swap it in for
                # the raw tokens we streamed.
                final = data.get("answer") or "".join(parts)
                if grounded:
                    slot.markdown(final)
                else:
                    slot.markdown(f'<div class="refusal">🔍 {final}</div>',
                                  unsafe_allow_html=True)

            elif event == "error":
                detail = data.get("detail", "Something went wrong")
                if data.get("code") == 429 and "budget" in detail.lower():
                    st.session_state.budget_exhausted = True
                    st.error(detail, icon="🛑")
                elif data.get("code") == 429:
                    # State 3 — upstream rate limit. Retry ONCE, then stop.
                    # Looping retries is how a free quota dies in seconds.
                    wait = min(int(data.get("retry_after") or 5), 30)
                    if not retried:
                        slot.info(f"Rate limited — retrying in {wait}s.")
                        time.sleep(wait)
                        return ask(question, retried=True)
                    st.warning("Still rate limited. Send it again in a moment.", icon="⏳")
                else:
                    st.error(detail, icon="⚠️")
                return

    answer = final if final is not None else "".join(parts)
    if not saw_event or not answer.strip():
        st.warning("The backend returned nothing. Check the uvicorn terminal.", icon="⚠️")
        return

    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "citations": citations if grounded else [],
        "grounded": grounded,
    })


if question:
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    ask(question)
    st.rerun()

# Deploying Doclyn

Deployed on **Streamlit Community Cloud** — free, GitHub sign-in, no credit card.

## Why this host, and not the obvious ones

The hard constraint is zero cost with no card on file. Checked in September 2026:

| Host | Outcome |
|---|---|
| Hugging Face Spaces | Docker SDK now requires a PRO subscription; only Static Spaces are free, and Static cannot run Python. |
| Render | Free web services now ask for a card at signup. |
| Vercel | Wrong shape. Serverless functions are short-lived, so the vector store and embedding model would be rebuilt on every request, and the bundle size limit is well under what `chromadb` + `onnxruntime` need. |
| **Streamlit Community Cloud** | **Free, no card, one long-running process.** Chosen. |

Free tiers move. Re-check before repeating any of this.

## The one architectural concession

Streamlit Community Cloud runs a Streamlit app and nothing else, so the FastAPI
service cannot be its own deployment. With `DOCLYN_EMBEDDED_API=1` the UI starts
the ASGI app in a background thread on loopback and talks to it over HTTP.

The separation is intact — same app, same HTTP calls, no business logic in the
UI — but the API is not publicly reachable on this host. The `curl` examples in
the README are therefore local-only. Moving to any host that allows two services
is a config change, not a rewrite: drop `DOCLYN_EMBEDDED_API` and point
`DOCLYN_API` at the API's URL.

## Memory

The API fits a small free tier only because embeddings use the ONNX build of
all-MiniLM-L6-v2 bundled with ChromaDB rather than PyTorch. **Do not add
`sentence-transformers` to `requirements.txt`** — it pulls in ~2.5GB and will
exhaust the container. It stays commented out there as an optional local backend.

## Persistence

No free tier offers a persistent disk, so the vector store is ephemeral.
Handled rather than hidden: `DOCLYN_SEED_SAMPLE=1` re-indexes the sample corpus
on every start, `/health` reports `persistence: "ephemeral"`, and the UI shows
"Uploads reset on restart".

---

## Steps

### 1. Push to GitHub

```bash
git remote add origin https://github.com/<you>/Doclyn.git
git push -u origin main
```

Confirm `.env` is not in the repo — this is the check that matters:

```bash
git ls-files | findstr env      # .env.example and check_env.py ONLY
```

### 2. Deploy

1. https://share.streamlit.io → sign in with GitHub
2. **Create app** → **Deploy a public app from GitHub**
3. Repository `<you>/Doclyn`, branch `main`, main file `frontend/app.py`
4. **Advanced settings → Secrets:**

```toml
GROQ_API_KEY = "gsk_your_key_here"
DOCLYN_EMBEDDED_API = "1"
DOCLYN_STUB = "0"
DOCLYN_PERSISTENCE = "ephemeral"
DOCLYN_SEED_SAMPLE = "1"
DOCLYN_RATE_LIMIT = "10"
```

5. **Deploy.** First boot installs dependencies and downloads the embedding
   model — several minutes.

Secrets can be edited later under **Manage app → Settings → Secrets**, which
reboots the app. `DOCLYN_RATE_LIMIT` can be tightened without touching code.

### 3. Verify as a visitor

Open the URL in a private window:

- [ ] Green status dot, model name and remaining budget in the header
- [ ] **"Uploads reset on restart"** shown — correct and honest
- [ ] Sample documents listed in the sidebar (seeded at startup)
- [ ] An answerable question returns a cited answer; citations expand to source text
- [ ] An unanswerable question returns the grey refusal with no sources
- [ ] **No stub-mode banner** — one would mean `DOCLYN_STUB` isn't `"0"`

### 4. Before sharing the link widely

A public demo spends **your** org-wide Groq quota.

| Setting | Default | If the link travels |
|---|---|---|
| `DOCLYN_RATE_LIMIT` | 10 requests/hour/IP | 5 |
| `DAILY_TOKEN_BUDGET` | 150,000 (~123 questions) | Lower in `config.py` |

Run `python scripts/check_budget.py` locally before recording a demo.

---

## Known rough edges

**The app sleeps when idle.** First load after a quiet period is slow while the
container restarts and re-seeds. Worth saying in the README — a reviewer who
hits a long load with no explanation assumes it's broken.

**The ledger is ephemeral too.** `data/usage.jsonl` sits on the same disposable
filesystem, so `DAILY_TOKEN_BUDGET` forgets what was spent on restart. On this
host the per-IP cap is the real protection.

**Rate limiting is in-memory and per-process.** Fine for one instance.

## If it fails

**`ModuleNotFoundError: backend`** — `frontend/app.py` needs the project root on
`sys.path`; the fix is the `sys.path.insert` near the top of that file.

**App loads but the status dot is red** — the embedded API failed to start. It
prints the traceback on the page; **Manage app → logs** has the full detail.

**Out of memory during install** — something pulled in PyTorch. Check
`requirements.txt`.

**Stub-mode banner in production** — `DOCLYN_STUB` must be the string `"0"` in
secrets, with quotes.

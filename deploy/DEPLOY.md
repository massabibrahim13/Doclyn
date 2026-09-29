# Deploying Doclyn

Two free services, no credit card:

| Part | Host | Why |
|---|---|---|
| **API** (FastAPI) | Render free tier | 750 instance-hours/month. Gives you a public API URL. |
| **UI** (Streamlit) | Streamlit Community Cloud | Free, deploys straight from GitHub. |

Neither offers a persistent disk, so the vector store is ephemeral. Handled:
`DOCLYN_SEED_SAMPLE=1` re-indexes the sample corpus on every start, `/health`
reports `persistence: "ephemeral"`, and the UI shows "Uploads reset on restart".
Degraded but honest — never ship silently vanishing uploads.

**Note on memory:** the API fits the free tier only because embeddings run on
the ONNX build of all-MiniLM-L6-v2 bundled with ChromaDB instead of PyTorch.
Don't add `sentence-transformers` to `requirements.txt` — it will not fit in
512MB.

---

## 1. Push to GitHub

Both hosts deploy from a GitHub repo.

```bash
git remote add origin https://github.com/<you>/doclyn.git
git push -u origin main
```

Check `.env` is **not** in the repo:

```bash
git ls-files | findstr .env      # should show .env.example ONLY
```

## 2. Deploy the API to Render

1. https://render.com → sign in with GitHub
2. **New → Web Service** → pick the `doclyn` repo
3. Render reads `render.yaml` and fills most of it in. Confirm:
   - Runtime **Python 3**, Plan **Free**
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT --workers 1`
   - Health check path: `/health`
4. **Environment → Add Environment Variable:**

   | Key | Value |
   |---|---|
   | `GROQ_API_KEY` | your key from console.groq.com/keys |

   The rest come from `render.yaml`. Leave `DOCLYN_CORS_ORIGINS` for step 4.
5. Deploy. First build takes a few minutes.
6. Check it: open `https://<your-service>.onrender.com/health` — you want
   `"status":"ok"`, `"stub_mode":false`, `"persistence":"ephemeral"` and a
   non-zero `chunks_indexed` (that's the seeding working).

Copy the service URL.

## 3. Deploy the UI to Streamlit Community Cloud

1. https://share.streamlit.io → sign in with GitHub
2. **New app** → repo `doclyn`, branch `main`, main file `frontend/app.py`
3. **Advanced settings → Secrets**, paste:

   ```toml
   DOCLYN_API = "https://<your-service>.onrender.com"
   ```
4. Deploy.

## 4. Point CORS at the UI

Back in Render → Environment:

| Key | Value |
|---|---|
| `DOCLYN_CORS_ORIGINS` | `https://<your-app>.streamlit.app` |

Strictly, the UI calls the API server-side so CORS doesn't block it. Set it
anyway — anyone embedding Doclyn in a web page calls from a browser, and that is
the whole point of §6.0.

Never `*`.

## 5. Tighten the budget before sharing the link

A public demo spends **your** org-wide quota.

| Setting | Default | For a widely shared link |
|---|---|---|
| `DOCLYN_RATE_LIMIT` | 10 requests/hour/IP | 5 |
| `DAILY_TOKEN_BUDGET` | 150,000 (~123 questions) | Lower in `config.py` if you want reserve |

`DOCLYN_RATE_LIMIT` is a Render env var — changing it needs no code change.

## 6. Verify as a visitor

Open the Streamlit URL in a private window:

- [ ] Green dot, model name, remaining budget in the header
- [ ] **"Uploads reset on restart"** shown — correct and honest
- [ ] Sample documents listed in the sidebar (seeded at startup)
- [ ] An answerable question returns a cited answer, citations expand to source text
- [ ] An unanswerable question returns the grey refusal with no sources
- [ ] **No stub-mode banner** — if you see one, `DOCLYN_STUB` isn't `0`
- [ ] `curl https://<your-service>.onrender.com/health` works from a terminal

Run `python scripts/check_budget.py` locally before recording a demo GIF.

---

## Known rough edges

**First load after idle is slow.** Render's free tier spins down after 15
minutes. A cold start takes most of a minute; the UI shows a "sleeping" message
rather than claiming the backend is dead. Say so in the README — a reviewer who
hits a 50-second load with no explanation assumes it's broken.

**The ledger resets with the filesystem.** `data/usage.jsonl` is ephemeral too,
so `DAILY_TOKEN_BUDGET` forgets what was spent whenever the service restarts. On
an ephemeral host the per-IP cap is the real protection.

**Rate limiting is per-process and in-memory.** Fine for one free instance.

## If it fails

**Build runs out of memory** — something pulled in PyTorch. Check
`requirements.txt` for `sentence-transformers`.

**`/health` returns 500** — usually a missing `GROQ_API_KEY`. Check Render logs.

**UI says backend not responding** — either a cold start (wait a minute), or
`DOCLYN_API` in Streamlit secrets is wrong. It needs the scheme and no trailing
slash: `https://x.onrender.com`, not `x.onrender.com/`.

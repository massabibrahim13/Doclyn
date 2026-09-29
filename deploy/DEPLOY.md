# Deploying Doclyn to Hugging Face Spaces

Free, 16GB RAM (PyTorch fits), no card. Storage is ephemeral — handled by
`DOCLYN_SEED_SAMPLE=1`, which re-indexes the sample corpus on every start.

---

## 1. Create the Space

1. Go to https://huggingface.co/new-space
2. **Name:** `doclyn`
3. **SDK:** **Docker** → *Blank*
4. **Hardware:** CPU basic (free)
5. **Visibility:** Public
6. Create.

## 2. Add your API key as a secret

In the Space: **Settings → Variables and secrets → New secret**

| Name | Value |
|---|---|
| `GROQ_API_KEY` | your key from console.groq.com/keys |

Secret, not variable — variables are visible to anyone viewing the Space.

**Never commit `.env`.** It is gitignored; keep it that way.

## 3. Push the code

The Space is a git repo. From your project folder:

```bash
git remote add space https://huggingface.co/spaces/<your-username>/doclyn
```

The Space needs its own `README.md` carrying the YAML front-matter that tells
Hugging Face how to build it. Your project `README.md` is the portfolio one, so
swap it only on the branch you push to the Space:

```bash
git checkout -b space
cp deploy/hf-space-README.md README.md
git add README.md && git commit -m "Space README with HF front-matter"
git push space space:main
git checkout main          # your portfolio README is untouched on main
```

Repeat the last four lines whenever you want to redeploy.

Build takes several minutes the first time — it installs PyTorch and bakes the
embedding model into the image.

## 4. Tighten the budget before sharing the link

A public demo spends **your** org-wide free quota. Two dials, both in
`backend/config.py`:

| Setting | Default | For a public link |
|---|---|---|
| `DAILY_TOKEN_BUDGET` | 150,000 | Lower it if you want headroom kept in reserve |
| `RATE_LIMIT_REQUESTS` | 10/hour/IP | Lower to 5 if the link gets shared widely |

`RATE_LIMIT_REQUESTS` can also be set as a Space **variable** (`DOCLYN_RATE_LIMIT`)
without a redeploy.

## 5. Verify

Open the Space URL in a private window and check:

- [ ] Header shows a green dot, the model name, and remaining budget
- [ ] Header shows **"Uploads reset on restart"** — correct, and honest
- [ ] Sample documents are listed in the sidebar (seeded at startup)
- [ ] An answerable question returns a cited answer
- [ ] An unanswerable question returns the grey refusal, no sources
- [ ] Expanding a citation shows the source passage
- [ ] No stub-mode banner (that would mean `DOCLYN_STUB` wasn't `0`)

Then run `python scripts/check_budget.py` locally before recording a demo GIF, so
you know what you have left.

---

## If the build fails

**Out of memory during pip install** — the CPU-only torch index in the Dockerfile
is what keeps this manageable. Don't remove that line.

**Model download fails at build time** — Hugging Face rate-limits unauthenticated
downloads. Add `HF_TOKEN` as a Space secret.

**App starts but shows "backend not responding"** — `start.sh` waits for the API
before launching the UI, so this means uvicorn crashed. Check the Space logs; a
missing `GROQ_API_KEY` is the usual cause.

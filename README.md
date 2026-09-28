# Doclyn

A document-grounded chatbot. Upload documents, ask questions, get answers with
verifiable citations — or an honest refusal when the documents don't contain the
answer.

> **Status: Stage 0 of 6.** This README is a placeholder. It gets written properly
> at Stage 6 (§10.6) and must include: the architecture diagram, setup steps, the
> real hit-rate@k numbers from Stage 3 before and after the chunk-size change,
> working `curl` examples, the prompt iteration log, a note on the quota
> guardrails, and an honest Limitations section.

The full build reference lives in [`docs/SPEC.md`](docs/SPEC.md).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # then paste your Groq key into it
python scripts/check_env.py
```

## Stack

FastAPI · ChromaDB · sentence-transformers (`all-MiniLM-L6-v2`, local) ·
Groq `openai/gpt-oss-120b` · Streamlit

Ingestion runs entirely on your machine and costs zero API tokens. The only call
that spends quota is the answer generation itself.

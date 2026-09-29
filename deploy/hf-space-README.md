---
title: Doclyn
emoji: 📄
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
short_description: Document-grounded chat with verifiable citations
---

# Doclyn

Upload a document, ask questions, get answers with citations you can check —
or an explicit refusal when the documents don't contain the answer.

**Uploads reset when this Space restarts.** No free tier offers a persistent
disk, so the vector store is ephemeral. A sample corpus is indexed at startup so
there is always something to ask about.

Built on a zero-cost stack: FastAPI, ChromaDB, local sentence-transformers
embeddings, and Groq's free tier. Full write-up, measured retrieval numbers and
an honest limitations section are in the source repository.

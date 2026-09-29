# Hugging Face Spaces (Docker SDK). Runs both processes in one container:
# FastAPI on an internal port, Streamlit on 7860 which is what Spaces exposes.
FROM python:3.12-slim

# Spaces runs containers as uid 1000. Creating that user up front means the
# model cache, the vector store and the ledger all land somewhere writable.
RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HF_HOME=/home/user/.cache/huggingface \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
# CPU-only torch first. The default wheel carries CUDA and is several GB — this
# image has no GPU, so that is pure download time and disk.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt

COPY . /app
RUN chown -R user:user /app

USER user

# Bake the embedding model into the image. Downloading it on first request would
# make the first visitor wait a minute for no reason.
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('all-MiniLM-L6-v2')"

# No free tier gives chroma_store/ a real disk, so say so rather than losing
# uploads silently, and seed the sample corpus so the demo always works.
ENV DOCLYN_PERSISTENCE=ephemeral \
    DOCLYN_SEED_SAMPLE=1 \
    DOCLYN_STUB=0 \
    DOCLYN_API=http://127.0.0.1:8000

EXPOSE 7860
CMD ["bash", "start.sh"]

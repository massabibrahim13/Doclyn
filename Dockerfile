# Optional. Render and Streamlit Cloud both deploy from source without it —
# this is here for running the whole stack as one container locally, or on any
# host that wants an image.
FROM python:3.12-slim

RUN useradd -m -u 1000 user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
# No PyTorch: embeddings use the ONNX build of all-MiniLM-L6-v2 that ships with
# ChromaDB. That is the difference between a ~150MB image and a ~3GB one.
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . /app
RUN chown -R user:user /app
USER user

ENV DOCLYN_PERSISTENCE=ephemeral \
    DOCLYN_SEED_SAMPLE=1 \
    DOCLYN_STUB=0 \
    DOCLYN_API=http://127.0.0.1:8000

EXPOSE 7860
CMD ["bash", "start.sh"]

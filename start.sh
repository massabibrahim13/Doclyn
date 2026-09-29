#!/usr/bin/env bash
# One container, two processes. Streamlit takes 7860 because that is the port
# Hugging Face Spaces routes to; FastAPI stays on loopback and is reached only
# by the UI process, so it is never exposed publicly.
set -euo pipefail

uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 &
API_PID=$!

# Wait for the API before starting the UI, otherwise the first page load shows
# the "backend not responding" state for no reason.
for _ in $(seq 1 60); do
  if python -c "import httpx,sys; sys.exit(0 if httpx.get('http://127.0.0.1:8000/health', timeout=2).status_code==200 else 1)" 2>/dev/null; then
    break
  fi
  sleep 1
done

# If the API died during startup, fail loudly instead of serving a broken UI.
kill -0 "$API_PID" 2>/dev/null || { echo "backend failed to start"; exit 1; }

exec streamlit run frontend/app.py \
  --server.port 7860 \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false

#!/usr/bin/env sh
set -eu
uvicorn app.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true' EXIT
streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true

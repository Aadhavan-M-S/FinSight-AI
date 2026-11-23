#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export HF_HOME="${HF_HOME:-$PWD/data/huggingface}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-2}"
(
  cd backend
  exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
) &
backend_pid=$!
(
  cd frontend
  exec ./node_modules/.bin/vite --host 127.0.0.1
) &
frontend_pid=$!
trap 'kill "$backend_pid" "$frontend_pid" 2>/dev/null || true' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
wait -n "$backend_pid" "$frontend_pid"

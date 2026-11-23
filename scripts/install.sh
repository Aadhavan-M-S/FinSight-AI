#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/data/uv-cache}"
export npm_config_cache="${npm_config_cache:-$PWD/data/npm-cache}"
(cd backend && uv sync --locked --group neural)
(cd frontend && npm ci)

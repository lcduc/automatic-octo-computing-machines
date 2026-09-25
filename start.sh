#!/usr/bin/env bash
# Container entrypoint: bring the schema up to date, then serve the API.
set -euo pipefail

cd /app
echo "Applying database migrations…"
alembic upgrade head

echo "Starting API on ${HOST:-0.0.0.0}:${PORT:-8500}"
exec python main.py

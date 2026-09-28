#!/usr/bin/env bash
# Container entrypoint: optionally bring the schema up to date, then serve the API.
#
# Under docker compose the one-shot `migrate` service applies migrations with
# the schema owner's role before this starts (MIGRATE_ON_START=false), because
# the API itself connects with a role that may read and write rows only.
set -euo pipefail

cd /app
if [ "${MIGRATE_ON_START:-true}" = "true" ]; then
  echo "Applying database migrations…"
  alembic upgrade head
fi

echo "Starting API on ${HOST:-0.0.0.0}:${PORT:-8500}"
exec python main.py

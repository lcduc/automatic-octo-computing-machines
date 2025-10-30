#!/usr/bin/env bash
set -euo pipefail

CERT=${SSL_CERT_FILE:-/app/SSL/fullchain.pem}
KEY=${SSL_KEY_FILE:-/app/SSL/privkey_converted.pem}
WORKERS=${UVICORN_WORKERS:-1}
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8500}

if [[ -r "$CERT" && -r "$KEY" ]]; then
  echo "Starting Uvicorn with TLS → ${HOST}:${PORT}"
  exec uvicorn main:app --host "$HOST" --port "$PORT" --workers "$WORKERS" \
       --ssl-certfile "$CERT" --ssl-keyfile "$KEY"
else
  echo "TLS files not found/readable. Starting HTTP → ${HOST}:${PORT}"
  exec uvicorn main:app --host "$HOST" --port "$PORT" --workers "$WORKERS"
fi

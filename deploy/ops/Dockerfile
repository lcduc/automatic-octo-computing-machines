# Ops CLI image (`chatbot-ops`): everything a client box needs besides Docker itself.
# Build from the repository root:  docker build -f deploy/ops/Dockerfile -t chatbot-ops .
# It carries the release's compose file and deploy assets, copied into the
# install directory by `chatbot install` / `chatbot deploy`.

FROM rclone/rclone:1.71 AS rclone

# Docker CLI with the Compose plugin (v2.33), on Alpine.
FROM docker:27-cli
RUN apk add --no-cache python3 openssl tzdata
COPY --from=rclone /usr/local/bin/rclone /usr/local/bin/rclone

WORKDIR /opt/ops
COPY deploy/__init__.py deploy/__init__.py
COPY deploy/ops/*.py deploy/ops/
COPY docker-compose.yml templates/docker-compose.yml
COPY deploy/Caddyfile templates/deploy/Caddyfile
COPY deploy/postgres/ templates/deploy/postgres/

ENV OPS_TEMPLATES_DIR=/opt/ops/templates \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python3", "-m", "deploy.ops"]

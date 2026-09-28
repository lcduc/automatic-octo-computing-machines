#!/bin/sh
# One-command install of the chatbot on a client VPS/VM (Ubuntu/Debian).
#
#   curl -fsSL https://raw.githubusercontent.com/lcduc/automatic-octo-computing-machine/<tag>/deploy/install.sh \
#     | sudo sh -s -- --tag <tag> [--answers /root/client.toml]
#
# The host gets only what containers cannot bring themselves: Docker Engine
# and, with a GPU, the NVIDIA Container Toolkit (each installed only after you
# confirm). It then writes /usr/local/bin/chatbot (the ops CLI, run from its
# container) and a nightly backup cron entry, and runs `chatbot install`, which
# asks six questions (or reads --answers), generates every secret, checks the
# box, deploys and runs the security self-check. Rerunning is safe.
set -eu

TAG=""
ANSWERS=""
DIR="/opt/chatbot"
REGISTRY="ghcr.io/lcduc"
REGISTRY_USER=""
REGISTRY_TOKEN_FILE=""
ASSUME_YES=0

usage() {
  cat <<'EOF'
Usage: install.sh --tag TAG [--answers FILE] [--dir DIR] [--registry PREFIX]
                  [--registry-user USER --registry-token-file FILE] [--yes]

  --tag                  Release to install (e.g. v1.0.0)
  --answers              TOML answers file (see deploy/answers.example.toml); prompts otherwise
  --dir                  Install directory (default /opt/chatbot)
  --registry             Image registry prefix (default ghcr.io/lcduc)
  --registry-user/-token-file  Credentials when the images are private
  --yes                  Install Docker / the NVIDIA toolkit without asking
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --tag) TAG=$2; shift 2 ;;
    --answers) ANSWERS=$2; shift 2 ;;
    --dir) DIR=$2; shift 2 ;;
    --registry) REGISTRY=$2; shift 2 ;;
    --registry-user) REGISTRY_USER=$2; shift 2 ;;
    --registry-token-file) REGISTRY_TOKEN_FILE=$2; shift 2 ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

fail() { echo "install.sh: $*" >&2; exit 1; }
confirm() {
  [ "$ASSUME_YES" = 1 ] && return 0
  [ -r /dev/tty ] || fail "$1 (rerun with --yes to accept)"
  printf '%s [y/N] ' "$1" > /dev/tty
  read -r reply < /dev/tty
  case "$reply" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

[ -n "$TAG" ] || { usage >&2; fail "--tag is required"; }
[ "$(id -u)" = 0 ] || fail "run as root (sudo)"
[ "$(uname -s)" = Linux ] || fail "Linux only"
if [ -n "$ANSWERS" ]; then [ -r "$ANSWERS" ] || fail "cannot read $ANSWERS"; fi

# --- Docker Engine ------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  confirm "Docker is not installed. Install Docker Engine (get.docker.com)?" || fail "Docker is required"
  curl -fsSL https://get.docker.com | sh
fi
docker info >/dev/null 2>&1 || fail "Docker is installed but not running (systemctl start docker)"

# --- NVIDIA Container Toolkit -------------------------------------------------
if command -v nvidia-smi >/dev/null 2>&1; then
  if ! docker info --format '{{json .Runtimes}}' | grep -q nvidia; then
    command -v apt-get >/dev/null 2>&1 || fail "install the NVIDIA Container Toolkit for your distribution, then rerun"
    confirm "Install the NVIDIA Container Toolkit so containers can use the GPU?" || fail "the GPU toolkit is required"
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
      | gpg --dearmor --yes -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -fsSL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
      | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
      > /etc/apt/sources.list.d/nvidia-container-toolkit.list
    apt-get update -q && apt-get install -y -q nvidia-container-toolkit
    nvidia-ctk runtime configure --runtime=docker
    systemctl restart docker
  fi
else
  echo "warning: no NVIDIA driver found (nvidia-smi); the preflight GPU check will fail" >&2
fi

# --- Install directory and registry access ------------------------------------
mkdir -p "$DIR"
chmod 755 "$DIR"
export DOCKER_CONFIG="$DIR/.docker"
if [ -n "$REGISTRY_USER" ]; then
  [ -r "$REGISTRY_TOKEN_FILE" ] || fail "--registry-token-file is required with --registry-user"
  docker login "${REGISTRY%%/*}" -u "$REGISTRY_USER" --password-stdin < "$REGISTRY_TOKEN_FILE"
fi

# --- The `chatbot` command: the ops CLI in its container ----------------------
cat > /usr/local/bin/chatbot <<EOF
#!/bin/sh
# Runs the chatbot ops CLI for the install in $DIR (written by install.sh).
set -eu
DIR="$DIR"
REGISTRY="$REGISTRY"
export DOCKER_CONFIG="\$DIR/.docker"
env_value() { sed -n "s/^\$1=//p" "\$2" 2>/dev/null | tr -d "'" | tail -n 1; }
TAG=\$(env_value IMAGE_TAG "\$DIR/.env")
# deploy/rollback run the ops image of the target release (it carries that release's compose file).
case "\${1:-}" in
  deploy) [ -n "\${2:-}" ] && TAG=\$2 ;;
  rollback)
    if [ -n "\${2:-}" ]; then TAG=\$2
    else TAG=\$(grep -v "^\$TAG\\\$" "\$DIR/.deploy_history" 2>/dev/null | tail -n 1 || true); fi ;;
esac
[ -n "\$TAG" ] || TAG="$TAG"
MOUNTS="-v /var/run/docker.sock:/var/run/docker.sock -v \$DIR:\$DIR"
BACKUP_TARGET=\$(env_value BACKUP_TARGET "\$DIR/ops.env")
case "\$BACKUP_TARGET" in /*) mkdir -p "\$BACKUP_TARGET"; MOUNTS="\$MOUNTS -v \$BACKUP_TARGET:\$BACKUP_TARGET" ;; esac
TTY=""
[ -t 0 ] && [ -t 1 ] && TTY="-t"
# shellcheck disable=SC2086
exec docker run --rm -i \$TTY --network host \$MOUNTS \\
  -e OPS_DIR="\$DIR" -e OPS_REGISTRY="\$REGISTRY" -e OPS_TAG="\$TAG" -e DOCKER_CONFIG="\$DIR/.docker" \\
  "\$REGISTRY/chatbot-ops:\$TAG" "\$@"
EOF
chmod 755 /usr/local/bin/chatbot

# --- Nightly backup ------------------------------------------------------------
if [ -d /etc/cron.d ]; then
  cat > /etc/cron.d/chatbot <<'EOF'
# Written by install.sh: nightly off-server backup of the chatbot.
SHELL=/bin/sh
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
30 2 * * * root /usr/local/bin/chatbot backup --label nightly >> /var/log/chatbot-backup.log 2>&1
EOF
  chmod 644 /etc/cron.d/chatbot
else
  echo "warning: /etc/cron.d not found; schedule 'chatbot backup --label nightly' daily yourself" >&2
fi

# --- Install -------------------------------------------------------------------
docker pull -q "$REGISTRY/chatbot-ops:$TAG" >/dev/null
if [ -n "$ANSWERS" ]; then
  install -m 600 "$ANSWERS" "$DIR/.answers.toml"
  trap 'rm -f "$DIR/.answers.toml"' EXIT
  /usr/local/bin/chatbot install --tag "$TAG" --registry "$REGISTRY" --answers "$DIR/.answers.toml"
elif [ -r /dev/tty ]; then
  /usr/local/bin/chatbot install --tag "$TAG" --registry "$REGISTRY" < /dev/tty
else
  fail "no terminal for the questions: pass --answers FILE"
fi

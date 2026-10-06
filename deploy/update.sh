#!/usr/bin/env bash
# Pull a newer Health Wall image and restart only if it changed. Run by health-wall-update.timer
# (deploy/install-updater.sh) every few minutes — the server pulls; nothing from outside runs on it.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose pull --quiet
docker compose up -d --no-build --remove-orphans
docker image prune -f >/dev/null
rev=$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' \
      "$(docker compose ps -q web)" 2>/dev/null || true)
echo "health-wall: running ${rev:0:7}"

#!/usr/bin/env bash
# Auto-update for the Docker setup: a systemd *user* timer runs `docker compose pull && up -d` every 5 min,
# so a push to main (→ GitHub Actions → GHCR) lands on the Pi by itself. No root needed.
# Run from the project root, after `docker login ghcr.io`:  ./deploy/install-autoupdate.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"
mkdir -p "$UNIT_DIR"
for unit in health-wall-update.service health-wall-update.timer; do
  sed -e "s#__ROOT__#$ROOT#g" "$ROOT/deploy/systemd/$unit" > "$UNIT_DIR/$unit"
done
loginctl enable-linger "$(id -un)"   # keep user timers running without a login session
systemctl --user daemon-reload
systemctl --user enable --now health-wall-update.timer
systemctl --user list-timers health-wall-update.timer --no-pager

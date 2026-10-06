#!/usr/bin/env bash
# Automatic updates for the Docker install: a systemd *user* timer runs deploy/update.sh every 5 minutes
# (docker compose pull + up -d; containers restart only when the image changed).
# The server pulls from the registry — no CI runner, nothing from outside executes on it.
# Run from the project root (expected at ~/health-wall):  ./deploy/install-updater.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$ROOT" != "$HOME/health-wall" ]; then
  echo "Expected the project at ~/health-wall (the timer runs %h/health-wall/deploy/update.sh)." >&2
  exit 1
fi
UNITS="$HOME/.config/systemd/user"
mkdir -p "$UNITS"
cp "$ROOT/deploy/systemd/health-wall-update.service" "$ROOT/deploy/systemd/health-wall-update.timer" "$UNITS/"

loginctl enable-linger "$(id -un)"   # keep user timers running without a login session
systemctl --user daemon-reload
# replaces the old deploy-on-build GitHub Actions runner, if one was installed
systemctl --user disable --now github-runner.service 2>/dev/null || true
systemctl --user enable --now health-wall-update.timer
systemctl --user list-timers health-wall-update.timer --no-pager

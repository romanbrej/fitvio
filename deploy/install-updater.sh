#!/usr/bin/env bash
# Automatic updates for the Docker install: a systemd *user* timer runs deploy/update.sh every 5 minutes
# (docker compose pull + up -d; containers restart only when the image changed).
# The server pulls from the registry — no CI runner, nothing from outside executes on it.
# Run from the project root (expected at ~/fitvio):  ./deploy/install-updater.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$ROOT" != "$HOME/fitvio" ]; then
  echo "Expected the project at ~/fitvio (the timer runs %h/fitvio/deploy/update.sh)." >&2
  exit 1
fi
UNITS="$HOME/.config/systemd/user"
mkdir -p "$UNITS"
cp "$ROOT/deploy/systemd/fitvio-update.service" "$ROOT/deploy/systemd/fitvio-update.timer" "$UNITS/"

loginctl enable-linger "$(id -un)"   # keep user timers running without a login session
systemctl --user daemon-reload
# replaces the update timer from before the rename to Fitvio (health-wall-update), if installed
systemctl --user disable --now health-wall-update.timer 2>/dev/null || true
rm -f "$UNITS/health-wall-update.service" "$UNITS/health-wall-update.timer"
# replaces the old deploy-on-build GitHub Actions runner, if one was installed
systemctl --user disable --now github-runner.service 2>/dev/null || true
systemctl --user enable --now fitvio-update.timer
systemctl --user list-timers fitvio-update.timer --no-pager

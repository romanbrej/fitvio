#!/usr/bin/env bash
# Install the Health Wall without Docker on a systemd-based Linux (Python >= 3.11).
# Run from the project root:  ./deploy/install.sh
# The frontend is built here if Node is present, otherwise build it elsewhere and copy frontend/dist over first.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"
cd "$ROOT"

python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e backend

if command -v npm >/dev/null 2>&1; then
  (cd frontend && npm ci && npm run build)
elif [ ! -f frontend/dist/index.html ]; then
  echo "No npm and no frontend/dist — build on your Mac (cd frontend && npm run build) and copy frontend/dist here." >&2
  exit 1
fi

mkdir -p data

for unit in healthdash-api.service healthdash-sync.service healthdash-sync.timer; do
  sed -e "s#__ROOT__#$ROOT#g" -e "s#__USER__#$USER_NAME#g" "deploy/systemd/$unit" | sudo tee "/etc/systemd/system/$unit" >/dev/null
done
sudo systemctl daemon-reload
sudo systemctl enable --now healthdash-api.service healthdash-sync.timer

IP="$(hostname -I | awk '{print $1}')"
echo
echo "Installed. Wall UI: http://$IP:8765"
echo "Next, for each person (asks only for the Garmin email + password):"
echo "  .venv/bin/healthdash add-person"

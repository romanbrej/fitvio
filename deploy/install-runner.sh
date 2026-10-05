#!/usr/bin/env bash
# Deploy on build (optional): installs a GitHub Actions self-hosted runner (label "pi", the one the `deploy`
# job asks for) on the server as a systemd *user* service. The `deploy` job in .github/workflows/build.yml
# runs on it after the image is pushed and does `docker compose pull && up -d`. The runner only connects out
# to GitHub; nothing on the server is exposed. It downloads the linux-arm64 runner — use the x64 build on
# an x86 server.
# Get a registration token (valid 1 h) on any machine with the GitHub CLI:
#   gh api -X POST repos/<owner>/<repo>/actions/runners/registration-token --jq .token
# Then on the server, from the project root:  ./deploy/install-runner.sh <token>
set -euo pipefail
TOKEN="${1:?usage: $0 <registration-token>}"
VERSION=2.337.0
REPO_URL=https://github.com/romanbrej/fitness-dashboard
DIR="$HOME/actions-runner"

mkdir -p "$DIR" && cd "$DIR"
if [ ! -x ./config.sh ]; then
  curl -fsSL "https://github.com/actions/runner/releases/download/v$VERSION/actions-runner-linux-arm64-$VERSION.tar.gz" | tar xz
fi
./config.sh --unattended --replace --url "$REPO_URL" --token "$TOKEN" --name "$(hostname)" --labels pi --work _work

mkdir -p "$HOME/.config/systemd/user"
cat > "$HOME/.config/systemd/user/github-runner.service" <<UNIT
[Unit]
Description=GitHub Actions runner (deploys the Health Wall after each build)
After=network-online.target

[Service]
WorkingDirectory=$DIR
ExecStart=$DIR/run.sh
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNIT

loginctl enable-linger "$(id -un)"   # keep the runner up without a login session
systemctl --user daemon-reload
systemctl --user disable --now health-wall-update.timer 2>/dev/null || true   # replaced by deploy-on-build
systemctl --user enable --now github-runner.service
systemctl --user status github-runner.service --no-pager | head -5

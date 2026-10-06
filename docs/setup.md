# Setup and hosting

## Requirements

- An always-on machine in your home network with **Docker** and Docker Compose — a home server, NAS, mini PC or single-board computer (amd64 or arm64). SQLite is written regularly, so prefer an SSD over an SD card or USB stick.
- A **Garmin Connect** account (and a Garmin watch that syncs to it).
- A screen with a browser for the wall — typically a tablet in kiosk mode.

## Install with Docker

```bash
mkdir health-wall && cd health-wall
curl -fsSLO https://raw.githubusercontent.com/romanbrej/fitness-dashboard/main/docker-compose.yml
mkdir -p data config
printf 'HW_UID=%s\nHW_GID=%s\nTZ=Europe/Berlin\n' "$(id -u)" "$(id -g)" > .env   # containers run as you; set your time zone
docker compose up -d
```

Two containers start from the prebuilt image (`ghcr.io/romanbrej/fitness-dashboard`, amd64 + arm64):

| Container | Job |
|---|---|
| `web` | UI and API on port 8765 |
| `sync` | Auto-sync: checks for a new activity every 2 min, full differential sync hourly |

Your data and logins stay on the host in `./data` and `./config`. They are mounted into the containers and never built into the image (see `.dockerignore`).

- **Logs:** `docker compose logs -f sync` (or `web`).
- **Build it yourself instead:** clone the repository and run `docker compose up -d --build`.
- **Rollback:** put `HW_TAG=sha-<commit>` in `.env`, then `docker compose up -d`. Remove it again to follow `latest`.

### Updates

- **By hand:** `docker compose pull && docker compose up -d`.
- **Automatically:** clone the repository to `~/health-wall` (your `data/`, `config/` and `.env` live there too) and run `./deploy/install-updater.sh`. A systemd user timer then checks for a newer image every 5 minutes and restarts the containers only when it changed. The server pulls; nothing from outside runs on it.
- Without systemd, a cron line does the same: `*/5 * * * * cd ~/health-wall && docker compose pull -q && docker compose up -d`.

## Connect Garmin

Open `http://<server-ip>:8765` from a device in your home network. A fresh install asks for your Garmin email and password (and the security code, if your account uses two-factor login). Your whole history is downloaded in the background — the first time this can take a while; you can watch the progress. To add another person: Accounts (the person icon, top right) → *Add a person*.

Logins are only accepted from your home network (private or loopback addresses), because the dashboard serves plain HTTP. Don't expose port 8765 to the internet.

### From a terminal

```bash
docker compose exec web healthdash add-person     # or .venv/bin/healthdash add-person without Docker
# Garmin email: …
# Garmin password: …        (plus the MFA code if your account uses two-factor auth)
```

That one command:
1. Logs in to Garmin Connect once. The login tokens are cached, so background syncs never prompt.
2. Downloads **all** your activities and up to 5 years of health data (sleep, HRV, resting HR, stress, Body Battery, weight). Use `--since YYYY-MM-DD` to go back further. The first download can take a long time; later syncs only fetch what's new.
3. Reads everything else from Garmin and prints where each value came from:

| Value | Where it comes from |
|---|---|
| Name | Your Garmin profile |
| Sex | Garmin user settings, or the user profile on your watch |
| Max HR | The HR zones on your watch. If your activities show a higher HR, that wins, because the setting is outdated |
| Resting HR | Median of Garmin's daily resting HR over the last 30 days |
| Threshold HR, FTP | Your watch settings. Without an FTP, it's estimated per ride from your power data |

These values refresh on every sync. If your max or resting HR moves, your whole history is recalculated with the new zones.
To see what was detected: `healthdash profile`, or open the *Training load* page on the wall.
To override a value anyway, add it to that person in `config/users.json` (e.g. `"max_hr": 192`).

The password is stored `chmod 600` in `data/garmindb/<id>/config/password.txt`, in case the cached tokens ever expire.

## Without Docker (systemd)

On a systemd-based Linux with Python ≥ 3.11:

```bash
git clone https://github.com/romanbrej/fitness-dashboard.git health-wall && cd health-wall && ./deploy/install.sh
```

This installs `healthdash-api.service` (the UI and API on port 8765) and `healthdash-sync.timer`. It builds the frontend if Node is installed; otherwise build it elsewhere (`cd frontend && npm run build`) and copy `frontend/dist` over.

## Put it on the wall

Any screen with a modern browser works. For a wall display:
- **Android tablet:** a kiosk browser (e.g. *Fully Kiosk Browser*) pointed at `http://<server-ip>:8765`, screen always on, status and navigation bars hidden. Turn on *auto reload on network reconnect / page error*, so the wall recovers by itself after a server restart.
- **iPad:** in Safari, *Add to Home Screen* (it opens fullscreen), then *Guided Access*, and set Auto-Lock to Never.
- **Any other screen:** a browser in fullscreen / kiosk mode.

The layout is made for a landscape tablet (around 1280 × 800 CSS px); bigger screens at pixel ratio 1 are scaled up automatically, smaller ones stack. Accounts → *This screen* shows the size the wall lays out at and whether it fits on one screen. The night screen times are set with `night_start` and `night_end` in `config/users.json` (`wall` section).

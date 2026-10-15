# Setup and hosting

## Requirements

- An always-on machine in your home network with **Docker** and Docker Compose — a home server, NAS, mini PC or single-board computer (amd64 or arm64). SQLite is written regularly, so prefer an SSD over an SD card or USB stick.
- A **Garmin Connect** account (and a Garmin watch that syncs to it).
- A screen with a browser for the wall — typically a tablet in kiosk mode.

## Install with Docker

```bash
mkdir fitvio && cd fitvio
curl -fsSLO https://raw.githubusercontent.com/romanbrej/fitvio/main/docker-compose.yml
mkdir -p data config
printf 'FITVIO_UID=%s\nFITVIO_GID=%s\nTZ=Europe/Berlin\n' "$(id -u)" "$(id -g)" > .env   # containers run as you; set your time zone
docker compose up -d
```

Two containers start from the prebuilt image (`ghcr.io/romanbrej/fitvio`, amd64 + arm64):

| Container | Job |
|---|---|
| `web` | UI and API on port 8765 (IPv4) |
| `sync` | Auto-sync: checks for a new activity every 2 min, full differential sync hourly |
| `mqtt` | Optional, off by default: shares people with Home Assistant (see [Home Assistant](#home-assistant)) |

Your data and logins stay on the host in `./data` and `./config`. They are mounted into the containers and never built into the image (see `.dockerignore`).

- **Logs:** `docker compose logs -f sync` (or `web`).
- **Build it yourself instead:** clone the repository and run `docker compose up -d --build`.
- **Rollback:** put `FITVIO_TAG=sha-<commit>` in `.env`, then `docker compose up -d`. Remove it again to follow `latest`.
- **Miles, °F and pounds:** put `FITVIO_UNITS=imperial` in `.env`, then `docker compose up -d`. That's the default for everyone; each person can still pick their own on the phone (Me → Units). Everything is stored in metric, so switching back and forth is safe.
- **Only on your LAN address:** the port is published on IPv4 only. To listen on one address, put `FITVIO_BIND=<server-ip>` in `.env` — only if that IP is fixed (a DHCP reservation in your router), otherwise the dashboard stops answering when it changes.

### Updates

- **By hand:** `docker compose pull && docker compose up -d`.
- **Automatically:** clone the repository to `~/fitvio` (your `data/`, `config/` and `.env` live there too) and run `./deploy/install-updater.sh`. A systemd user timer then checks for a newer image every 5 minutes and restarts the containers only when it changed. The server pulls; nothing from outside runs on it.
- Without systemd, a cron line does the same: `*/5 * * * * cd ~/fitvio && docker compose pull -q && docker compose up -d`.
- The updater refreshes the image, not `docker-compose.yml`. When a change touches that file (the pull request says so), run `git pull && docker compose up -d` in `~/fitvio` once.

## Connect Garmin

Open `http://<server-ip>:8765` from a device in your home network. A fresh install asks for your Garmin email and password (and the security code, if your account uses two-factor login). Your whole history is downloaded in the background — the first time this can take a while; you can watch the progress. To add another person: Accounts (the person icon, top right) → *Add a person*.

Logins are only accepted from your home network (10.x, 172.16–31.x, 192.168.x, IPv6 ULA/link-local, loopback), because the dashboard serves plain HTTP. Don't expose port 8765 to the internet. Rootless Docker hides where a client comes from, so every client would look local; use regular Docker for Fitvio.

### From a terminal

```bash
docker compose exec web fitvio add-person     # or .venv/bin/fitvio add-person without Docker
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
To see what was detected: `fitvio profile`, or open the *Training load* page on the wall.
To override a value anyway, add it to that person in `config/users.json` (e.g. `"max_hr": 192`).

The password is stored `chmod 600` in `data/garmindb/<id>/config/password.txt`, in case the cached tokens ever expire.

## Without Docker (systemd)

On a systemd-based Linux with Python ≥ 3.11:

```bash
git clone https://github.com/romanbrej/fitvio.git fitvio && cd fitvio && ./deploy/install.sh
```

This installs `fitvio-api.service` (the UI and API on port 8765) and `fitvio-sync.timer`. It builds the frontend if Node is installed; otherwise build it elsewhere (`cd frontend && npm run build`) and copy `frontend/dist` over.

## Put it on the wall

Any screen with a modern browser works. For a wall display:
- **Android tablet:** a kiosk browser (e.g. *Fully Kiosk Browser*) pointed at `http://<server-ip>:8765`, screen always on, status and navigation bars hidden. Turn on *auto reload on network reconnect / page error*, so the wall recovers by itself after a server restart.
- **iPad:** in Safari, *Add to Home Screen* (it opens fullscreen), then *Guided Access*, and set Auto-Lock to Never.
- **Any other screen:** a browser in fullscreen / kiosk mode.

The layout is made for a landscape tablet (around 1280 × 800 CSS px); bigger screens at pixel ratio 1 are scaled up automatically. Phones (narrower than 700 px) get their own phone app instead. Accounts → *This screen* shows the size the wall lays out at and whether it fits on one screen. The night screen times are set with `night_start` and `night_end` in `config/users.json` (`wall` section).

## Home Assistant

Fitvio can show up in your own [Home Assistant](https://www.home-assistant.io), so its numbers and workouts sit on the same dashboard as everything else and can drive automations. It goes through an MQTT broker in your home network, with Home Assistant's MQTT discovery: the entities appear by themselves. Nothing goes to the cloud.

It's off by default, twice over: nothing is sent until there's an `mqtt` block in the config, and then only for people who share. Each person decides for themselves in Accounts (or on the phone: Me → Home Assistant).

### 1. A broker

- **Home Assistant OS / Supervised:** install the *Mosquitto broker* add-on and create a Home Assistant user for Fitvio (Settings → People → Users), e.g. `fitvio`.
- **Home Assistant in Docker:** run Mosquitto next to it. A minimal `docker-compose.yml` in its own folder:

  ```yaml
  services:
    mosquitto:
      image: eclipse-mosquitto:2
      restart: unless-stopped
      ports: ["1883:1883"]
      volumes: ["./config:/mosquitto/config", "./data:/mosquitto/data"]
      mem_limit: 64m
  ```

  with `config/mosquitto.conf`:

  ```
  listener 1883
  allow_anonymous false
  password_file /mosquitto/config/passwd
  persistence true
  persistence_location /mosquitto/data/
  ```

  Create one user for Home Assistant and one for Fitvio: `docker compose run --rm mosquitto mosquitto_passwd -c /mosquitto/config/passwd homeassistant`, then the same without `-c` for `fitvio`. Then `docker compose up -d`.

Then add the **MQTT** integration in Home Assistant (Settings → Devices & services → Add integration → MQTT) with the broker's address and the `homeassistant` user. Discovery is on by default.

### 2. Fitvio

Add an `mqtt` block to `config/users.json`:

```json
"mqtt": {
  "host": "host.docker.internal",
  "port": 1883,
  "username": "fitvio"
}
```

- `host`: the broker's address. `host.docker.internal` means "this machine" (the broker runs on the same server as Fitvio); otherwise its IP.
- `topic_prefix` (default `fitvio`) and `discovery_prefix` (default `homeassistant`) are optional.

The password goes into `.env`, never into the config file. Turn on the `mqtt` container there too:

```
COMPOSE_PROFILES=mqtt
FITVIO_MQTT_PASSWORD=<the fitvio user's password>
```

Then `docker compose up -d` and `docker compose logs -f mqtt`; it says when it's connected. Last, each person picks **Share** under Home Assistant in Accounts or on their phone.

If the broker is down, Fitvio just keeps going; the `mqtt` container retries on its own and catches up when the broker is back. Syncs never wait for it.

### What you get

Per person, a device **Fitvio \<name\>** (entity ids use the person's id from `config/users.json`, here `alex`):

| Entity | What |
|---|---|
| `sensor.fitvio_alex_training_readiness` | Garmin Training Readiness (attribute `level`) |
| `sensor.fitvio_alex_hrv` | last night's HRV in ms (attributes: `status`, `normal_low`, `normal_high`, `weekly_average`) |
| `sensor.fitvio_alex_resting_hr` | resting heart rate (attribute `normal`) |
| `sensor.fitvio_alex_sleep_score`, `…_sleep_duration` | last night's sleep |
| `sensor.fitvio_alex_body_battery` | Body Battery (the day's highest) |
| `sensor.fitvio_alex_vo2max` | VO₂max |
| `sensor.fitvio_alex_fitness`, `…_fatigue`, `…_form` | the training load curves |
| `sensor.fitvio_alex_training_status` | the form zone, as on the wall: Very fresh / Fresh / Neutral / Productive / Overreaching |
| `sensor.fitvio_alex_running`, `…_cycling`, `…_swimming`, `…_gym` | per sport (only the ones the person does; a new sport appears by itself): the newest verdict, Better / In line / Worse … (attributes: `trend` improving / steady / declining, `change` and `unit`, e.g. +5 s/km, the period in `days`, `last_session`) |
| `sensor.fitvio_alex_week_load` | this week's load (attributes: `sweet_spot_low`, `sweet_spot_high`, `status` below / in / above) |
| `sensor.fitvio_alex_week_streak` | weeks in a row (attributes: `this_week`, `needed`) |
| `sensor.fitvio_alex_todays_workout` | today's planned workout, or `Rest` |
| `sensor.fitvio_alex_last_workout` | the last workout's verdict: Better / In line / Worse (attributes: `sport`, `name`, `headline`, `time`) |
| `sensor.fitvio_alex_last_sync`, `…_sync_status` | when it last synced, and `ok` / `stale` / `failed` / `login_expired` |
| `button.fitvio_alex_sync_now` | starts a sync (same cooldown as the button in Accounts) |
| `event.fitvio_alex_new_workout` | a new workout; its event type is the verdict: `better`, `in_line`, `worse`, `not_comparable`, `load_only` |
| `event.fitvio_alex_sync_failed`, `…_login_expired` | syncing started failing; the Garmin login expired (each once, until it works again) |

### Example automations

```yaml
- alias: "Better workout: living room lights green"
  triggers:
    - trigger: state
      entity_id: event.fitvio_alex_new_workout
      not_from: [unavailable, unknown]
  conditions:
    - condition: state
      entity_id: event.fitvio_alex_new_workout
      attribute: event_type
      state: better
  actions:
    - action: light.turn_on
      target: { entity_id: light.living_room }
      data: { color_name: green, brightness_pct: 100 }

- alias: "Low readiness: take it easy today"
  triggers:
    - trigger: time
      at: "07:30:00"
  conditions:
    - condition: numeric_state
      entity_id: sensor.fitvio_alex_training_readiness
      below: 40
  actions:
    - action: notify.mobile_app_alex_phone
      data: { message: "Take it easy today: readiness {{ states('sensor.fitvio_alex_training_readiness') }}" }

- alias: "Garmin login expired"
  triggers:
    - trigger: state
      entity_id: event.fitvio_alex_login_expired
      not_from: [unavailable, unknown]
  actions:
    - action: notify.mobile_app_alex_phone
      data: { message: "Fitvio: Garmin login expired. Tap Sync now in Accounts." }
```

### The wall inside a Home Assistant dashboard

The wall can be shown in a dashboard, e.g. with a *Webpage* card pointed at `http://<server-ip>:8765`. By default no other page may frame it; allow your Home Assistant explicitly in `config/users.json`:

```json
"wall": { "embed_origins": ["http://192.168.1.10:8123"] }
```

That's the address you open Home Assistant with, exactly (scheme, host, port). Then restart the `web` container. If you open Home Assistant over HTTPS, the browser won't show the plain-HTTP wall inside it.

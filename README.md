# Health Wall

A wall-mounted fitness and health dashboard on top of your Garmin data.
When you come home from an activity, the wall answers one question: **did this session make me better?**
The rest of the time it shows your training form, recovery and how each sport is trending.

```
Garmin watch → Garmin Connect → GarminDB (per person, on the Pi) → healthdash ingest + verdicts → API → tablet (kiosk browser)
```

## What it does

**Post-activity verdict.** Each new activity is compared with your *similar* sessions from the last 8 to 17 weeks: same sport, same session type (easy / long / tempo / intervals / race), a comparable duration, and indoor vs outdoor kept apart. The result is **Better / In line / Worse**, with the top reasons in plain language, a confidence level, and the effect on your fitness, fatigue and form.
When there are fewer than 3 comparable sessions it says **"Not comparable yet"** instead of guessing.

| Sport | What "improved" means |
|---|---|
| Running | Grade-adjusted pace per heartbeat (Minetti energy-cost model, heat-normalised), pace at a fixed HR, aerobic decoupling (HR drift) |
| Cycling (with power, e.g. a smart trainer) | Power per heartbeat, Power:HR drift, best 5-min power, power-curve PRs, eFTP |
| Cycling without power | Training load only, marked low confidence (wind and terrain make speed meaningless) |
| Swimming | Pace per 100 m and SWOLF, compared only against the same main stroke |
| Gym | Estimated 1-rep max per exercise (Epley) vs the best of your last 3 sessions, plus PRs. Needs reps and weight logged on the watch |
| Everything else | Training load and recovery impact |

**Heat and humidity.** Running efficiency is adjusted with **Garmin's own weather for the activity** (the same weather box Garmin Connect shows, taken from a station near the start at start time) and **Garmin's heat acclimation**. It uses the runners' temperature + dew point rule: the sum in °F sets how much harder the same effort was (0 % up to 100 °F, up to 12 % above 180 °F). Heat acclimation reduces that effect by up to half, which is a heuristic. Indoor and treadmill sessions get no heat adjustment. The wrist temperature sensor isn't used for this, because body heat skews it, and FIT files use 127 as a "no value" marker.
Weather and acclimation are downloaded with each sync. For older history, run `healthdash backfill-extras` once (a first download does this automatically).

**Overview.**
- Form, fitness and fatigue, from heart-rate-based training load so all sports count on one scale
- Last night's HRV against your baseline, resting HR against your usual, sleep with stages, Body Battery and stress
- 6-week trend per sport
- This week vs last week
- Recent activities
- VO₂max to one decimal (e.g. 44.1, from Garmin's daily VO₂max history), running and cycling, with the 6-week change

**Glance → tap → detail.** Every card opens a detail page: every number, HR and pace/power charts, laps, sets, the exact baseline sessions you were compared with, and health trends over up to 365 days. The display returns to the wall after 2 minutes idle.

**Multi-user.** Each person has their own Garmin login and their own GarminDB. The newest activity takes over the wall with that person's avatar; tap an avatar to switch.

**Verdict check.** Rate *How did you feel* and *Perceived effort* on your watch after each activity. The app tracks how often the verdicts agree with how you felt, and lists the disagreements.

**Syncing.** Every hour, on a new activity (see *Auto-sync* below), and on demand via the sync button in the top bar (at most once a minute), the app runs a *differential* sync:
- It only downloads days and activities that are new or changed, including today.
- It only imports files written since the last successful sync.
- It only recalculates the affected years.
- Activities you rename or rate afterwards in Garmin Connect (feel, effort) are picked up again without re-taking the wall.

A typical sync takes well under a minute.

**Auto-sync on new activity.** Garmin offers webhooks only to approved business partners, so the app does the next best thing:
- **Quick check:** every 2 minutes (05:00–24:00) it asks Garmin for the newest activity id only. That's one tiny request per person, and nothing is downloaded.
- **Sync on change:** if the id is new, the normal differential sync starts, and the workout is on the wall about 2–3 minutes after your watch uploaded it.
- **Hourly sync:** sleep, HRV, resting HR and the other health data sync hourly, day and night.

It protects your Garmin account, because the app uses the unofficial Garmin Connect login:
- **Expired login:** the check only uses the cached login tokens, never your password or MFA. If the tokens expire, the check pauses for that person and the top bar says *Garmin login expired*. Tap it, then *Sync now* in Accounts to log in again with the saved password.
- **Rate limit:** if Garmin answers "too many requests", the check pauses for everyone for 6 hours.
- **Stuck activity:** an activity that doesn't arrive after 3 syncs is left alone, so it never syncs in a loop.
- **Off switch:** you can turn it off in *Accounts → Auto-sync on new activity*. The hourly sync and the sync button keep working.

**Failure handling.** If the Garmin sync breaks (GarminDB uses the unofficial Garmin Connect login), the wall shows an amber "Last sync X ago" banner after 24 h. An old verdict is never re-shown as if it were new.

## Quick start (demo data, on your Mac)

```bash
python3 -m venv .venv && .venv/bin/pip install -e "backend[dev]"
(cd frontend && npm install && npm run build)
mkdir -p data && cp config/users.example.json data/demo-users.json   # the example file itself stays untouched
export HEALTHDASH_CONFIG=data/demo-users.json HEALTHDASH_DB=data/demo.db   # demo people, separate DB
.venv/bin/healthdash demo          # 150 days of synthetic data for 2 people
.venv/bin/healthdash serve         # → http://localhost:8765
```

Frontend development with hot reload: `cd frontend && npm run dev`. It proxies `/api` to port 8765.

## Real data: just connect Garmin

There's nothing to configure by hand.

**In the UI (easiest):** open the wall on a fresh install and it asks for your Garmin email and password.
To add another person later, tap the accounts icon (top right) and then *Add a person*.
If Garmin asks for a security code (two-factor login), the screen asks for it too. Afterwards you watch the download
progress live, and it keeps running in the background if you leave the page. The same screen shows each person's last sync
and has a *Sync now* button.

Logins are only accepted from your home network (private or loopback addresses), because the dashboard serves plain HTTP.
Don't expose port 8765 to the internet.

**Or from a terminal:**

```bash
.venv/bin/healthdash add-person
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
To see what was detected: `healthdash profile`, or tap *Training form* on the wall.
To override a value anyway, add it to that person in `config/users.json` (e.g. `"max_hr": 192`).

The password is stored `chmod 600` in `data/garmindb/<id>/config/password.txt`, in case the cached tokens ever expire.

## Raspberry Pi + tablet

### With Docker (recommended)

The compose file runs one image as two containers:

| Container | Job |
|---|---|
| `web` | UI and API on port 8765 |
| `sync` | Auto-sync: checks for a new activity every 2 min, full differential sync hourly |

Your data and logins stay on the host in `./data` and `./config`. They are mounted into the containers and never built into the image (see `.dockerignore`).

```bash
git clone https://github.com/romanbrej/fitness-dashboard.git health-wall && cd health-wall
mkdir -p data config
printf 'HW_UID=%s\nHW_GID=%s\nTZ=Europe/Berlin\n' "$(id -u)" "$(id -g)" > .env   # containers run as you, not root
docker compose up -d --build
docker compose logs -f sync      # watch the sync
```

Then open `http://<pi-ip>:8765` and connect your Garmin account.

**If `npm ci` fails while building on the Pi** (e.g. "Exit handler never called"), build the image on another machine (arm64, e.g. an Apple Silicon Mac) and copy it over:

```bash
docker build -t health-wall .                                   # on the Mac, in the repo
docker save health-wall | gzip | ssh <user>@<pi-ip> 'gunzip | docker load'
ssh <user>@<pi-ip> 'cd health-wall && git pull && docker compose up -d --no-build'
```

To update, run `git pull`, then either `docker compose up -d --build` or the three commands above.

### Without Docker (systemd)

```bash
git clone https://github.com/romanbrej/fitness-dashboard.git health-wall && cd health-wall && ./deploy/install-pi.sh
```

This installs `healthdash-api.service` (the UI and API on port 8765) and `healthdash-sync.timer`.

### Display
- Use an SSD rather than an SD card if you can, because SQLite is written regularly.
- **Android tablet:** use *Fully Kiosk Browser* pointed at `http://<pi-ip>:8765`, with screen always on.
- **iPad:** in Safari, *Add to Home Screen* (it opens fullscreen), then *Guided Access*, and set Auto-Lock to Never.
- The screen dims automatically between `night_start` and `night_end` (tap to wake).

Nothing is exposed to the internet. Garmin credentials stay on the Pi.

## Security

What stays on the Pi and never goes into git (everything under `data/` and `config/users.json` is git-ignored):

| What | Where | Protection |
|---|---|---|
| Garmin password | `data/garmindb/<id>/config/password.txt` | `chmod 600`, directory `700`. Only needed if the cached login tokens expire |
| Garmin login tokens | `data/garmindb/<id>/config/garmin_tokens.json` | `chmod 600` |
| Your health data | `data/garmindb/<id>/HealthData`, `data/app.db` | directory `700`, DB `600` |
| Who is connected | `config/users.json` | `chmod 600`. A real account is never written into `users.example.json` |

How the web app is protected:
- **Home network only.** Garmin logins are only accepted from private or loopback addresses. The dashboard speaks plain HTTP, so never forward port 8765 to the internet.
- **DNS rebinding.** The server only answers to IP addresses, `localhost`, bare LAN hostnames and local domains (`.local`, `.lan`, `.home`, `.fritz.box`, …). To use another hostname, set `HEALTHDASH_ALLOWED_HOSTS=myname.example`.
- **Cross-site requests.** State-changing requests from another origin are refused, and non-JSON bodies are rejected.
- **Headers.** A strict Content-Security-Policy, `X-Frame-Options: DENY` (no clickjacking of the login form), `nosniff`, `no-referrer`, and `no-store` on API responses.
- **Input validation.** Lengths and formats are checked (email, password, MFA code, query ranges). Only one account can be connected at a time.
- **No password leaks.** The password is never logged or returned by the API, and the web page clears it from memory right after sending.

Not protected, by design: anyone on your home network can *view* the dashboard. It's a wall display, with no user login.

## CLI

```
healthdash add-person                  connect a Garmin account (only asks email + password)
healthdash profile [--user ID]         what was read from Garmin, and from where
healthdash sync [--user ID] [--full]   download (GarminDB) + ingest + verdicts
healthdash watch                       auto-sync: new-activity check every 2 min + hourly sync
healthdash ingest [--user ID] [--full] ingest only
healthdash evaluate [--user ID]        recompute all verdicts (e.g. after changing max_hr)
healthdash backfill-extras [--user ID] Garmin weather, heat acclimation + VO₂max history for the past
healthdash backtest [--user ID] [--sport S]
healthdash demo [--days N]
healthdash serve [--host H] [--port P]
```

## Project layout

```
backend/healthdash/
  ingest/garmindb_reader.py   read-only access to GarminDB SQLite + cached .FIT files
  ingest/fit_parser.py        fitdecode: power, swim lengths, strength sets, RPE/feel
  analytics/physio.py         GAP, efficiency, decoupling, NP, power curve, TRIMP, zones, e1RM
  analytics/features.py       per-session features + session-type classification
  analytics/load.py           fitness / fatigue / form
  models/base.py, sports.py   similar-session baseline + robust comparison → verdict
  pipeline.py                 store, evaluate, import health
  wall.py                     wall takeover rules, overview, validation
  api/main.py                 FastAPI + SSE, serves frontend/dist
  accounts.py                 Garmin login (incl. MFA) and sync jobs with live progress
  profile.py                  name, sex, max/resting HR, LTHR, FTP read from Garmin
  sync/garmindb_runner.py     runs GarminDB, differential sync, sync lock
  sync/garmindb_fast.py       runtime patches: skip cached days, adaptive pacing, changed-only import
  sync/garmin_extras.py       Garmin weather, heat acclimation, precise VO₂max
  sync/activity_watch.py      auto-sync: new-activity check (cached tokens only) + hourly sync
frontend/src/                 React + Vite wall UI (views/Wall*, detail views)
design-system/                ui-ux-pro-max design system + wall overrides
deploy/                       Pi install script + systemd units (non-Docker)
Dockerfile, docker-compose.yml  Docker deployment (web + sync)
```

Tests: `cd backend && ../.venv/bin/pytest`.

## Known limitations

- Weather comes from the nearest Garmin weather station at the start, so it doesn't capture sun, shade or temperature changes during long sessions.
- Garmin has no public webhook. A new activity is found by polling (every 2 min, 05:00–24:00); at night it waits for the hourly sync.
- Pool HR from a wrist sensor is unreliable. Swimming verdicts rely on pace and SWOLF, not HR.
- Garmin's strength categories are broad (for example "squat" covers goblet and back squat). The numeric variant is kept in the exercise key so different variants aren't mixed.
- The FIT parsing has only been tested against GarminDB's documented layout and synthetic data. Check `healthdash backtest` after your first real sync.

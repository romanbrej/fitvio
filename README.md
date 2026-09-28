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

**Overview.**
- Form, fitness and fatigue, from heart-rate-based training load so all sports count on one scale
- Last night's HRV against your baseline, resting HR against your usual, sleep with stages, Body Battery and stress
- 6-week trend per sport
- This week vs last week
- Recent activities
- VO₂max

**Glance → tap → detail.** Every card opens a detail page: every number, HR and pace/power charts, laps, sets, the exact baseline sessions you were compared with, and health trends over up to 365 days. The display returns to the wall after 2 minutes idle.

**Multi-user.** Each person has their own Garmin login and their own GarminDB. The newest activity takes over the wall with that person's avatar; tap an avatar to switch.

**Verdict check.** Rate *How did you feel* and *Perceived effort* on your watch after each activity. The app tracks how often the verdicts agree with how you felt, and lists the disagreements.

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

```bash
git clone … && cd healt-dashboard && ./deploy/install-pi.sh
```

This installs `healthdash-api.service` (the UI and API on port 8765) and `healthdash-sync.timer`.
- Use an SSD rather than an SD card if you can, because SQLite is written every 10 minutes.
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
healthdash ingest [--user ID] [--full] ingest only
healthdash evaluate [--user ID]        recompute all verdicts (e.g. after changing max_hr)
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
frontend/src/                 React + Vite wall UI (views/Wall*, detail views)
design-system/                ui-ux-pro-max design system + wall overrides
deploy/                       Pi install script + systemd units
```

Tests: `cd backend && ../.venv/bin/pytest`.

## Known limitations

- Wrist temperature reads high because of body heat, so the heat adjustment is deliberately mild.
- Pool HR from a wrist sensor is unreliable. Swimming verdicts rely on pace and SWOLF, not HR.
- Garmin's strength categories are broad (for example "squat" covers goblet and back squat). The numeric variant is kept in the exercise key so different variants aren't mixed.
- The FIT parsing has only been tested against GarminDB's documented layout and synthetic data. Check `healthdash backtest` after your first real sync.

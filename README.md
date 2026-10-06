# Health Wall

A wall-mounted fitness and health dashboard on top of your Garmin data.
When you come home from an activity, the wall answers one question: **did this session make me better?**
The rest of the time it shows today's plan, your training form, recovery and how each sport is trending — with a little
training buddy that reacts to how you're doing.

![The wall: today's mission with the week of your Garmin plan, readiness, training load, week streak and sport trends](docs/screenshots/wall.png)

![After a workout: the verdict — better, in line or worse than your similar sessions, and why](docs/screenshots/verdict.png)

<sub>Screenshots use the built-in demo data (`healthdash demo`).</sub>

```
Garmin watch → Garmin Connect → GarminDB (per person, on your server) → healthdash ingest + verdicts → API → wall display (any browser)
```

It runs on any always-on machine in your home network (a home server, NAS, mini PC or single-board computer) and is
shown on any screen with a browser — typically a tablet on the wall in kiosk mode. Nothing is exposed to the internet.

## Getting started

You need an always-on machine with **Docker** (and Docker Compose), a **Garmin Connect** account, and a screen with a browser.

1. **Get the code and start it**

   ```bash
   git clone <this repository> health-wall && cd health-wall
   mkdir -p data config
   printf 'HW_UID=%s\nHW_GID=%s\nTZ=Europe/Berlin\n' "$(id -u)" "$(id -g)" > .env   # containers run as you, not root; set your time zone
   docker compose up -d --build
   ```

   The first build takes a few minutes. Two containers start: `web` (the UI and API on port 8765) and `sync`
   (keeps your Garmin data up to date).

2. **Connect Garmin.** Open `http://<server-ip>:8765` from a device in your home network. A fresh install asks for your
   Garmin email and password (and the security code, if your account uses two-factor login). Your whole history is
   downloaded in the background — the first time this can take a while; you can watch the progress.

3. **Add more people (optional).** Accounts (the person icon, top right) → *Add a person*. Everyone gets their own
   Garmin login, data and avatar.

4. **Pick your training buddy (optional).** Accounts → *Training buddy*: mouse, cat, bunny, fox, bear, penguin, frog or
   hedgehog — one per person.

5. **Put it on the wall.** Point the display's browser at `http://<server-ip>:8765` and make it fullscreen
   (see [Display](#display)). The layout is made for a landscape tablet (around 1280 × 800 CSS pixels) and stacks on
   smaller screens.

That's it — the wall now syncs by itself (see [Syncing](#syncing)).

**Just want to look around first?** Run it with demo data on your computer, no Garmin needed:

```bash
python3 -m venv .venv && .venv/bin/pip install -e "backend[dev]"
(cd frontend && npm install && npm run build)
mkdir -p data && cp config/users.example.json data/demo-users.json   # the example file itself stays untouched
export HEALTHDASH_CONFIG=data/demo-users.json HEALTHDASH_DB=data/demo.db   # demo people, separate DB
.venv/bin/healthdash demo          # 150 days of synthetic data for 2 people
.venv/bin/healthdash serve         # → http://localhost:8765
```

Frontend development with hot reload: `cd frontend && npm run dev`. It proxies `/api` to port 8765.

## What it does

**Today's mission.** The wall opens with one headline for the day ("Ready to push.", "Keep building.", "Recover today.") from **Garmin's Training Readiness** (the score your watch shows) or, without it, from your form. Below it:
- **Today's workout from Garmin**: the planned workout in your Garmin Connect calendar (Garmin Coach's adaptive plan or a workout you scheduled), with its shape, targets and an estimated training load. Tap it for the step-by-step plan and the next days. Once you've done it, the card says *Done* with the verdict — and, when you started the run from the workout, how many work blocks hit the target pace. Nothing planned → no card. If Garmin can't be reached, the last good copy stays.
- **Training load**: fitness, fatigue and form on one chart, and this week's load against a **sweet spot** taken from your fitness (the weekly load that raises fitness by about 1–5 points: 7 × fitness + 46 … + 228). All loads are the app's heart-rate TRIMP, not Garmin's load.
- **Recovery**: Garmin Training Readiness, last night's HRV against your normal range, resting HR, sleep, Body Battery and VO₂max.
- **Week streak**: weeks in a row with at least 3 workouts of 10 minutes or more.
- **Sport cards**: your current pace, power or swim pace in real units with its 6-week trend; running also shows cadence (easy and long runs, information only — it never counts toward a verdict).

Readiness, the planned workouts and the plan come from Garmin endpoints GarminDB doesn't download; they are fetched after every successful sync with the same cached login (`sync/garmin_coach.py`).

**Training buddy.** A little animal that lives on the wall and reacts to your data: *overjoyed* after a "Better" workout or a new best, *hungry* after 3 days without training, *sleepy* when readiness or sleep is low, *happy* when you're fresh, *content* otherwise, and asleep at night. Tap it to pet it. Each person picks their own animal in Accounts.

**Post-activity verdict.** Each new activity is compared with your *similar* sessions from the last 8 to 17 weeks: same sport, same session type (easy / long / tempo / intervals / race), a comparable duration, and indoor vs outdoor kept apart. The result is **Better / In line / Worse**, with the top reasons in plain language, a confidence level, and the effect on your fitness, fatigue and form. It takes over the wall for an hour after the activity.
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

**Glance → tap → detail.** Every card opens a detail page: every number, HR and pace/power charts, laps, sets, the exact baseline sessions you were compared with, "Am I improving?" per sport, and health trends over up to 365 days. The display returns to the wall after 2 minutes idle.

**Day and night screens.** After a minute without a tap the overview fades to a calm day screen — big clock, today's headline, a few facts and your buddy. Between `night_start` and `night_end` a dark night screen takes over. A tap wakes the wall.

**Multi-user.** Each person has their own Garmin login and their own GarminDB. The newest activity takes over the wall with that person's avatar; tap an avatar to switch.

**Verdict check.** Rate *How did you feel* and *Perceived effort* on your watch after each activity. The app tracks how often the verdicts agree with how you felt, and lists the disagreements.

### Syncing

Every hour, on a new activity (see *Auto-sync* below), and on demand via the sync button in the top bar (at most once a minute), the app runs a *differential* sync:
- It only downloads days and activities that are new or changed, including today.
- It only imports files written since the last successful sync.
- It only recalculates the affected years.
- Activities you rename or rate afterwards in Garmin Connect (feel, effort) are picked up again without re-taking the wall.

A typical sync takes well under a minute. The first tap of the morning also fetches last night's sleep and HRV right away.

**Auto-sync on new activity.** Garmin offers webhooks only to approved business partners, so the app does the next best thing:
- **Quick check:** every 2 minutes (05:00–24:00) it asks Garmin for the newest activity id only. That's one tiny request per person, and nothing is downloaded.
- **Sync on change:** if the id is new, the normal differential sync starts, and the workout is on the wall about 2–3 minutes after your watch uploaded it.
- **Hourly sync:** sleep, HRV, resting HR and the other health data sync hourly, day and night.

It protects your Garmin account, because the app uses the unofficial Garmin Connect login:
- **Expired login:** the check only uses the cached login tokens, never your password or MFA. If the tokens expire, the check pauses for that person and the top bar says *Garmin login expired*. Tap it, then *Sync now* in Accounts to log in again with the saved password.
- **Rate limit:** if Garmin answers "too many requests", the check (and the plan/readiness fetch) pauses for everyone for 6 hours.
- **Stuck activity:** an activity that doesn't arrive after 3 syncs is left alone, so it never syncs in a loop.
- **Off switch:** you can turn it off in *Accounts → Auto-sync on new activity*. The hourly sync and the sync button keep working.

**Failure handling.** If the Garmin sync breaks (GarminDB uses the unofficial Garmin Connect login), the wall shows an amber "Last sync X ago" banner after 24 h. An old verdict is never re-shown as if it were new.

## Connecting Garmin from a terminal

The UI (Getting started, step 2) is the easiest way. The same works from a terminal on the server:

```bash
.venv/bin/healthdash add-person            # or: docker compose exec web healthdash add-person
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

Logins are only accepted from your home network (private or loopback addresses), because the dashboard serves plain HTTP.
Don't expose port 8765 to the internet.

## Hosting

### With Docker (recommended)

`docker compose up -d --build` (Getting started, step 1) builds the image on the machine itself and runs it as two containers:

| Container | Job |
|---|---|
| `web` | UI and API on port 8765 |
| `sync` | Auto-sync: checks for a new activity every 2 min, full differential sync hourly |

Your data and logins stay on the host in `./data` and `./config`. They are mounted into the containers and never built into the image (see `.dockerignore`).

- **Updating:** `git pull && docker compose up -d --build`.
- **Logs:** `docker compose logs -f sync` (or `web`).
- **Prebuilt images (optional):** `.github/workflows/build.yml` runs the tests, builds an image and pushes it to a container registry on every push to `main`; adjust the image name and the target platform (`platforms:`) to yours. Set the same image in `docker-compose.yml`, then `docker compose pull && docker compose up -d` instead of building. To deploy automatically after each build, register a self-hosted GitHub Actions runner on the server (`deploy/install-runner.sh <registration token>`); its `deploy` job pulls, restarts and runs a health check.
- **Rollback (prebuilt images):** put `HW_TAG=sha-<commit>` in `.env`, then `docker compose up -d`. Remove it again to follow `latest`.

### Without Docker (systemd)

On a systemd-based Linux with Python ≥ 3.11:

```bash
git clone <this repository> health-wall && cd health-wall && ./deploy/install.sh
```

This installs `healthdash-api.service` (the UI and API on port 8765) and `healthdash-sync.timer`. It builds the frontend if Node is installed; otherwise build it elsewhere (`cd frontend && npm run build`) and copy `frontend/dist` over.

Tip: SQLite is written regularly — prefer an SSD over an SD card or USB stick.

### Display

Any screen with a modern browser works. For a wall display:
- **Android tablet:** a kiosk browser (e.g. *Fully Kiosk Browser*) pointed at `http://<server-ip>:8765`, screen always on, status and navigation bars hidden. Turn on *auto reload on network reconnect / page error*, so the wall recovers by itself after a server restart.
- **iPad:** in Safari, *Add to Home Screen* (it opens fullscreen), then *Guided Access*, and set Auto-Lock to Never.
- **Any other screen:** a browser in fullscreen / kiosk mode.

Accounts → *This screen* shows the display's size and whether the wall fits on one screen. The night screen times are set with `night_start` and `night_end` in `config/users.json` (`wall` section).

## Security

What stays on your server and never goes into git (everything under `data/` and `config/users.json` is git-ignored):

| What | Where | Protection |
|---|---|---|
| Garmin password | `data/garmindb/<id>/config/password.txt` | `chmod 600`, directory `700`. Only needed if the cached login tokens expire |
| Garmin login tokens | `data/garmindb/<id>/config/garmin_tokens.json` | `chmod 600` |
| Your health data | `data/garmindb/<id>/HealthData`, `data/app.db` | directory `700`, DB `600` |
| Who is connected | `config/users.json` | `chmod 600`. A real account is never written into `users.example.json` |

How the web app is protected:
- **Home network only.** Garmin logins and settings changes are only accepted from private or loopback addresses. The dashboard speaks plain HTTP, so never forward port 8765 to the internet.
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

With Docker, run them inside a container: `docker compose exec web healthdash <command>`.

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
  coach.py                    today's workout, readiness, week streak, sweet spot, cadence
  buddy.py                    training buddy: animal per person + mood
  api/main.py                 FastAPI + SSE, serves frontend/dist
  accounts.py                 Garmin login (incl. MFA) and sync jobs with live progress
  profile.py                  name, sex, max/resting HR, LTHR, FTP read from Garmin
  sync/garmindb_runner.py     runs GarminDB, differential sync, sync lock
  sync/garmindb_fast.py       runtime patches: skip cached days, adaptive pacing, changed-only import
  sync/garmin_extras.py       Garmin weather, heat acclimation, precise VO₂max
  sync/garmin_coach.py        Garmin calendar workouts, training plan, Training Readiness
  sync/activity_watch.py      auto-sync: new-activity check (cached tokens only) + hourly sync
frontend/src/                 React + Vite wall UI (views/Wall*, detail views, components/Buddy, Day/NightScreen)
design-system/                design notes for the wall
deploy/                       non-Docker install script + systemd units, CI runner setup
Dockerfile, docker-compose.yml  Docker deployment (web + sync)
.github/workflows/build.yml   CI: tests → image → registry (→ optional deploy)
```

Tests: `cd backend && ../.venv/bin/pytest`.

## Known limitations

- Garmin's endpoints used here are unofficial and can change; the parsers are pinned to real (anonymized) answers in `backend/tests/fixtures/garmin`.
- Garmin Coach's adaptive plan only schedules about a week ahead, so the wall shows the next ~7 planned days.
- Weather comes from the nearest Garmin weather station at the start, so it doesn't capture sun, shade or temperature changes during long sessions.
- Garmin has no public webhook. A new activity is found by polling (every 2 min, 05:00–24:00); at night it waits for the hourly sync.
- Pool HR from a wrist sensor is unreliable. Swimming verdicts rely on pace and SWOLF, not HR.
- Garmin's strength categories are broad (for example "squat" covers goblet and back squat). The numeric variant is kept in the exercise key so different variants aren't mixed.
- The FIT parsing has only been tested against GarminDB's documented layout and synthetic data. Check `healthdash backtest` after your first real sync.

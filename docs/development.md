# Development

## Run it locally with demo data

```bash
python3 -m venv .venv && .venv/bin/pip install -e "backend[dev]"
(cd frontend && npm install && npm run build)
mkdir -p data && cp config/users.example.json data/demo-users.json   # the example file itself stays untouched
export HEALTHDASH_CONFIG=data/demo-users.json HEALTHDASH_DB=data/demo.db   # demo people, separate DB
.venv/bin/healthdash demo          # 150 days of synthetic data for 2 people
.venv/bin/healthdash serve         # → http://localhost:8765
```

Frontend development with hot reload: `cd frontend && npm run dev` (proxies `/api` to port 8765).

Tests: `cd backend && ../.venv/bin/pytest`. Lint: `cd frontend && npm run lint`.

CI (`.github/workflows/build.yml`) runs the tests and lint on every push to `main`, then builds the multi-arch image (amd64 + arm64) and pushes it to GHCR.

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
  coach.py                    Garmin plan week, today's workout, readiness, week streak, sweet spot, cadence
  buddy.py                    training buddy: animal per person + mood
  api/main.py                 FastAPI + SSE, serves frontend/dist
  accounts.py                 Garmin login (incl. MFA) and sync jobs with live progress
  profile.py                  name, sex, max/resting HR, LTHR, FTP read from Garmin
  sync/garmindb_runner.py     runs GarminDB, differential sync, sync lock
  sync/garmindb_fast.py       runtime patches: skip cached days, adaptive pacing, changed-only import
  sync/garmin_extras.py       Garmin weather, heat acclimation, precise VO₂max
  sync/garmin_coach.py        Garmin calendar workouts, training plan, Training Readiness
  sync/activity_watch.py      auto-sync: new-activity check (cached tokens only) + hourly sync
frontend/src/                 React + Vite wall UI (views/Wall*, PlanDetail, detail views, components/WeekStrip, Buddy, Day/NightScreen)
docs/                         these docs + README screenshots
deploy/                       update.sh + install-updater.sh (Docker auto-update), install.sh + systemd units (without Docker)
Dockerfile, docker-compose.yml  Docker deployment (web + sync)
.github/workflows/build.yml   CI: tests → multi-arch image → GHCR
```

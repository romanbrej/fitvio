# Health Wall

**Your Garmin data on the wall — and one honest answer after every workout: *did this session make me better?***

[![build](https://github.com/romanbrej/fitness-dashboard/actions/workflows/build.yml/badge.svg)](https://github.com/romanbrej/fitness-dashboard/actions/workflows/build.yml)
[![License: GPL v2](https://img.shields.io/badge/license-GPL--2.0-blue.svg)](LICENSE)
![Docker: amd64 + arm64](https://img.shields.io/badge/docker-amd64%20%7C%20arm64-2496ED?logo=docker&logoColor=white)
![Self-hosted](https://img.shields.io/badge/self--hosted-home%20network%20only-success)

A self-hosted dashboard for a tablet on your wall. It pulls your activities and health data from Garmin Connect, compares every new workout with your own similar sessions, and shows today's plan, your recovery and how each sport is trending — with a little training buddy that reacts to how you're doing.

![The wall: today's mission with the week of your Garmin plan, readiness, training load, week streak and sport trends](docs/screenshots/wall.png)

![After a workout: the verdict — better, in line or worse than your similar sessions, and why](docs/screenshots/verdict.png)

<sub>Screenshots use the built-in demo data.</sub>

## Quick start

You need a machine in your home network with **Docker** (amd64 or arm64) and a **Garmin Connect** account.

```bash
mkdir health-wall && cd health-wall
curl -fsSLO https://raw.githubusercontent.com/romanbrej/fitness-dashboard/main/docker-compose.yml
mkdir -p data config && printf 'HW_UID=%s\nHW_GID=%s\nTZ=Europe/Berlin\n' "$(id -u)" "$(id -g)" > .env
docker compose up -d
```

Open **`http://<server-ip>:8765`**, sign in with your Garmin account, and watch your history arrive. That's it — the wall keeps itself in sync from now on. Put it on a tablet in kiosk mode ([how](docs/setup.md#put-it-on-the-wall)).

**Just want to look around?** One command, no Garmin account, made-up data:

```bash
docker run --rm -p 8765:8765 -e HEALTHDASH_CONFIG=/tmp/demo/users.json -e HEALTHDASH_DB=/tmp/demo/app.db \
  ghcr.io/romanbrej/fitness-dashboard sh -c 'mkdir -p /tmp/demo && cp config/users.example.json /tmp/demo/users.json && healthdash demo && healthdash serve --host 0.0.0.0'
```

…then open `http://localhost:8765`.

## What you get

- **A verdict after every workout** — *Better / In line / Worse* than your similar sessions from the last weeks, with the reasons in plain words: pace per heartbeat (grade- and heat-adjusted), HR drift, power, SWOLF, estimated 1-rep max.
- **Today's mission** — one headline from Garmin's Training Readiness, and the week of your **Garmin Coach plan**: done ✓, missed ×, today, planned. Tap any day for its workout, step by step.
- **Training load that makes sense** — fitness, fatigue and form on one chart, plus a weekly *sweet spot* that keeps you improving without overdoing it.
- **Recovery at a glance** — readiness, HRV against your normal range, resting HR, sleep, Body Battery, VO₂max.
- **Every sport, one trend** — running, cycling, swimming and gym, each with the number that matters and its 6-week trend.
- **A training buddy** — pick one of 8 animals; it cheers after a good session, gets hungry when you skip, sleeps at night.
- **Made for the wall** — big type, day and night screens, the newest activity takes over the screen, auto-scales to big tablets.
- **For the whole household** — one Garmin login per person; tap an avatar to switch.
- **Private by design** — runs on your server, LAN only; your Garmin login and health data never leave your home.

## How it works

```
Garmin watch → Garmin Connect → GarminDB (on your server) → healthdash: ingest, analyse, verdicts → wall (any browser)
```

New activities show up on the wall about 2–3 minutes after your watch syncs: the app checks Garmin for a new activity every 2 minutes and runs a quick differential sync; health data syncs hourly. More in [How it works](docs/how-it-works.md).

## Documentation

| | |
|---|---|
| [Setup and hosting](docs/setup.md) | Docker, automatic updates, connecting Garmin, without Docker, putting it on the wall |
| [How it works](docs/how-it-works.md) | Verdicts per sport, heat adjustment, the Garmin plan, the buddy, syncing, limitations |
| [Security and privacy](docs/security.md) | What's stored where, how the web app is protected, reporting issues |
| [Development](docs/development.md) | Local setup with demo data, tests, CLI, project layout |

## Credits and disclaimer

Built on [GarminDB](https://github.com/tcgoetz/GarminDB), [garminconnect](https://github.com/cyberjunky/python-garminconnect) and [fitdecode](https://github.com/polyvertex/fitdecode).

Health Wall is not affiliated with or endorsed by Garmin. It uses the unofficial Garmin Connect login (through GarminDB and garminconnect), which Garmin can change at any time. It is not a medical device — its verdicts are training feedback, not health advice.

Licensed under the [GNU General Public License v2.0](LICENSE).

"""fitvio command line.

  fitvio init-user <user_id> <garmin_email>   create the GarminDB config for a user
  fitvio sync [--user ID] [--full]            GarminDB download + ingest + verdicts
  fitvio watch                                auto-sync on new activities (+ hourly full sync)
  fitvio ingest [--user ID] [--full]          ingest only (GarminDB data already present)
  fitvio evaluate [--user ID]                 recompute all verdicts
  fitvio backtest [--user ID] [--sport S]     print verdicts over history
  fitvio demo [--days N]                      fill the DB with synthetic data
  fitvio demo-export <out_dir>                made-up people + data as static JSON (the GitHub Pages demo)
  fitvio heat-report [--user ID]              how much heat costs each person, learned from their sessions
  fitvio wind-report [--user ID]              whether the wind correction makes runs more comparable
  fitvio serve [--host H] [--port P]          run the API + wall UI
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import db, pipeline
from .config import load_config


def _users(cfg, user_id):
    return [cfg.user(user_id)] if user_id else cfg.users


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fitvio")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add-person", help="connect a Garmin account (asks for email + password)")
    s.add_argument("--id", help="short id, default: from the email address")
    s.add_argument("--since", help="download health data from this date (YYYY-MM-DD), default: 5 years back")
    s.add_argument("--no-sync", action="store_true", help="only connect, download later with `fitvio sync --full`")
    s = sub.add_parser("profile", help="show what was detected from Garmin")
    s.add_argument("--user")
    s = sub.add_parser("init-user")
    s.add_argument("user_id")
    s.add_argument("email")
    for name in ("sync", "ingest", "evaluate"):
        s = sub.add_parser(name)
        s.add_argument("--user")
        s.add_argument("--full", action="store_true", help="full history instead of latest")
    sub.add_parser("watch", help="auto-sync: check Garmin every 2 min and Intervals.icu every 10 min for new "
                                 "activities, full sync hourly")
    s = sub.add_parser("backfill-extras", help="download Garmin's weather + heat acclimation for past activities")
    s.add_argument("--user")
    s = sub.add_parser("backtest")
    s.add_argument("--user")
    s.add_argument("--sport")
    s = sub.add_parser("demo")
    s.add_argument("--days", type=int, default=150)
    s = sub.add_parser("demo-export", help="made-up people and data as static JSON for the try-it demo")
    s.add_argument("out_dir")
    s.add_argument("--days", type=int, default=150)
    s.add_argument("--deny", default="", help="comma-separated words that must not appear in the output "
                                              "(also FITVIO_DEMO_DENY), e.g. real names")
    s = sub.add_parser("heat-report", help="how much heat costs each person per sport (reads FITVIO_DB only, "
                                           "read-only; prints numbers, no names)")
    s.add_argument("--user")
    s = sub.add_parser("wind-report", help="runs compared with their neighbours with and without the wind "
                                           "correction (reads the FIT files and cached weather, writes nothing; "
                                           "prints numbers, no names)")
    s.add_argument("--user")
    s = sub.add_parser("serve")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8765)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if a.cmd == "demo-export":  # before load_config: the demo never touches the real config or database
        from pathlib import Path

        from .config import env
        from .demo_export import export
        deny = f"{a.deny},{env('DEMO_DENY', '')}".split(",")
        print(json.dumps(export(Path(a.out_dir), days=a.days, deny=deny)))
        return 0
    if a.cmd == "heat-report":  # before load_config: needs only the database, opened read-only
        return heat_report(a.user)
    cfg = load_config()
    if a.cmd == "wind-report":  # the database read-only, no weather is fetched
        return wind_report(cfg, a.user)

    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("fitvio.api.main:app", host=a.host, port=a.port)
        return 0

    conn = db.connect(cfg.db_path)

    if a.cmd == "add-person":
        return add_person(conn, a)

    if a.cmd == "profile":
        from .profile import describe
        for u in _users(cfg, a.user):
            print_profile(u, describe(conn, u))
        return 0

    if a.cmd == "init-user":
        from .sync.garmindb_runner import init_user_config
        d = init_user_config(cfg.user(a.user_id), a.email)
        print(f"GarminDB config written to {d}\n"
              f"Now put your Garmin password (only) into {d / 'password.txt'} and set\n"
              f'  "garmindb_config_dir": "{d}"\nfor user "{a.user_id}" in config/users.json, then run:\n'
              f"  fitvio sync --user {a.user_id} --full")
        return 0

    if a.cmd == "sync":
        from .sync.garmindb_runner import SyncBusy
        from .sync.sources import sync_user
        rc = 0
        for u in _users(cfg, a.user):
            try:
                ok, result = sync_user(conn, u, full=a.full)
            except SyncBusy as e:
                print(f"{u.id}: skipped — {e}", file=sys.stderr)
                continue
            except Exception:  # keep going for the other users
                logging.exception("sync failed for %s", u.id)
                rc = 1
                continue
            if not ok:
                err = conn.execute("SELECT last_error FROM sync_status WHERE user_id = ?", (u.id,)).fetchone()[0]
                print(f"{u.id}: sync failed — {err}", file=sys.stderr)
            if result is None:
                rc = 1
            else:
                print(u.id, result)
            rc = rc or (0 if ok else 1)
        return rc

    if a.cmd == "watch":
        from .sync.activity_watch import watch_loop
        watch_loop(conn)
        return 0

    if a.cmd == "ingest":
        for u in _users(cfg, a.user):
            print(u.id, pipeline.ingest(conn, u, full=a.full))
        return 0

    if a.cmd == "backfill-extras":
        for u in _users(cfg, a.user):
            print(u.id, backfill_extras(u))
        return 0

    if a.cmd == "evaluate":
        for u in _users(cfg, a.user):
            print(u.id, pipeline.evaluate_all(conn, u.id), "verdicts")
        return 0

    if a.cmd == "backtest":
        for u in _users(cfg, a.user):
            q = """SELECT s.start_time, s.sport, s.session_type, s.name, s.rpe, s.feel, v.verdict, v.confidence,
                          v.score, v.headline FROM sessions s JOIN verdicts v ON v.session_id = s.id
                   WHERE s.user_id = ?"""
            args = [u.id]
            if a.sport:
                q += " AND s.sport = ?"
                args.append(a.sport)
            print(f"\n== {u.display_name} ==")
            counts: dict[str, int] = {}
            for r in conn.execute(q + " ORDER BY s.start_time", args):
                counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
                score = f"{r['score']:+.2f}" if r["score"] is not None else "  —  "
                feel = f"rpe {r['rpe']:.0f} feel {r['feel']:.0f}" if r["rpe"] is not None and r["feel"] is not None else ""
                print(f"{r['start_time'][:16]}  {r['sport']:<9} {r['session_type']:<9} {r['verdict']:<15} "
                      f"{r['confidence']:<6} {score}  {feel}")
            print(json.dumps(counts))
            from .wall import validation
            print("verdict vs feel:", json.dumps(validation(conn, u.id, days=3650)))
        return 0

    if a.cmd == "demo":
        from .demo import generate
        if not cfg.users:
            print("No users configured. Copy config/users.example.json to config/users.json first.", file=sys.stderr)
            return 1
        print(generate(conn, cfg, days=a.days))
        return 0
    return 1


def _read_only(path):
    """The database read-only, for the reports. A database from before some tables existed (a copy that
    hasn't been synced with this version) gets them empty, as TEMP tables: nothing is written to it."""
    import sqlite3
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    have = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "baseline_exclusions" not in have:
        conn.execute("CREATE TEMP TABLE baseline_exclusions (session_id TEXT PRIMARY KEY, user_id TEXT, excluded_at TEXT)")
    if "wall_state" not in have:
        conn.execute("CREATE TEMP TABLE wall_state (key TEXT PRIMARY KEY, value TEXT)")
    return conn


def _robust_sd(values: list[float]) -> float | None:
    from statistics import median
    if len(values) < 3:
        return None
    m = median(values)
    return 1.4826 * median(abs(v - m) for v in values)


def wind_report(cfg, user_id: str | None) -> int:
    """For each person's steady outdoor runs: how far each one's efficiency and HR drift sit from its
    similar neighbours (±21 days, heat adjusted with the person's heat response), without the wind
    correction and with it at a few exposures, as the verdicts use it (efficiency corrected, HR drift as
    run). The correction helps when the spread gets smaller. Two experiments show what correcting drift
    would do: on out-and-backs only (halves' headwind wind.DRIFT_HALVES_KMH apart) and on every run."""
    from . import heat_response, weather
    from .analytics import heat, physio, wind

    conn = _read_only(cfg.db_path)
    variants = ["none", *sorted({0.4, wind.EXPOSURE, 0.6}), "drift: out-and-backs", "drift: always"]
    for n, user in enumerate(_users(cfg, user_id), 1):
        print(f"\n== person {n} ==")
        try:
            reader = pipeline.reader_for(user)
        except RuntimeError:
            print("  no downloaded data")
            continue
        wx_dir, use_om = getattr(reader, "weather_dir", None), weather.enabled(conn, user.id)
        resp = heat_response.current(conn, user.id)["running"]
        runs: dict = {v: [] for v in variants}
        moved, out_and_back, read = [], set(), 0
        for s in pipeline.user_sessions(conn, user.id):
            if not heat._usable(s, "running") or (act := reader.load_activity(s["activity_id"])) is None:
                continue
            read += 1
            weather.apply(act, wx_dir, use_om)
            recs = act.records
            steady = physio.steady_slice(recs)
            cut = len(recs) - len(steady)
            gap = physio.grade_adjusted_speeds(recs)
            ef = physio.efficiency_factor(steady, gap[cut:])
            if not ef:
                continue
            f = {k: v for k, v in s["features"].items() if k != "wind"}
            f.update(ef=ef, decoupling=physio.decoupling(steady, gap[cut:]))
            halves = wind.halves_headwind_kmh(steady, act.weather, act.start_time)
            if halves is not None and abs(halves) >= wind.DRIFT_HALVES_KMH:
                out_and_back.add(s["id"])
            for v in variants:
                fe = dict(f)
                windy = None if v == "none" else wind.adjusted_speeds(
                    recs, gap, act.weather, act.start_time, v if isinstance(v, float) else wind.EXPOSURE)
                if windy and (w_ef := physio.efficiency_factor(steady, windy[cut:])):
                    drift = v == "drift: always" or (v == "drift: out-and-backs" and s["id"] in out_and_back)
                    fe["wind"] = {"ef": w_ef, "decoupling": physio.decoupling(steady, windy[cut:]) if drift else None}
                    if v == wind.EXPOSURE:
                        moved.append(abs(w_ef / ef - 1) * 100)
                runs[v].append({**s, "features": fe})
        print(f"running: {read} steady outdoor runs read, {len(moved)} with headings and wind data, "
              f"{len(out_and_back)} out-and-back (halves' headwind ≥ {wind.DRIFT_HALVES_KMH:g} km/h apart)")
        if moved:
            moved.sort()
            print(f"  at exposure {wind.EXPOSURE:g}: efficiency moved median {moved[len(moved) // 2]:.2f} %, "
                  f"max {moved[-1]:.2f} %, {sum(1 for m in moved if m > 1)} runs by more than 1 %")
        print("  spread vs neighbours (robust SD):  exposure    n   efficiency %   HR drift points   "
              "drift, out-and-backs only")
        eff, drift, oab = {}, {}, {}
        for v, sessions in runs.items():
            res = heat.residuals(sessions, "running", wind=True)
            eff[v] = _robust_sd([(p["r"] + resp["k"] * p["x"] / 100) * 100 for p in res])
            d = [(p["id"], p["rd"] - resp["d"] * p["x"]) for p in res if p["rd"] is not None]
            drift[v] = _robust_sd([x for _, x in d])
            oab[v] = _robust_sd([x for i, x in d if i in out_and_back])
            label = v if isinstance(v, str) else f"{v:g}" + (" (used)" if v == wind.EXPOSURE else "")
            cells = [f"{x:.2f}" if x is not None else "—" for x in (eff[v], drift[v], oab[v])]
            print(f"  {label:>44} {len(res):>4} {cells[0]:>13} {cells[1]:>17} {cells[2]:>27}")

        def verdict(what, new, old, unit):
            if new is not None and old is not None:
                print(f"  → {what}: {'not larger' if new <= old else 'LARGER'} with the wind correction "
                      f"({new:.2f} vs {old:.2f}{unit})")
        verdict("efficiency spread", eff[wind.EXPOSURE], eff["none"], " %")
        verdict("if drift were corrected on out-and-backs, its spread", drift["drift: out-and-backs"],
                drift["none"], " points")
    return 0


def heat_report(user_id: str | None) -> int:
    from pathlib import Path

    from . import weather
    from .analytics import heat
    from .config import PROJECT_ROOT, env
    path = Path(env("DB") or PROJECT_ROOT / "data" / "app.db").expanduser()
    if not path.exists():
        print(f"No database at {path} (set FITVIO_DB)", file=sys.stderr)
        return 1
    conn = _read_only(path)
    ids = [user_id] if user_id else [r[0] for r in conn.execute("SELECT DISTINCT user_id FROM sessions ORDER BY 1")]
    for n, uid in enumerate(ids, 1):
        sessions = pipeline.user_sessions(conn, uid)
        wind = weather.wind_enabled(conn, uid)
        print(f"\n== person {n} ==")
        for sport in heat.SPORTS:
            r = heat.fit_response(sessions, sport, wind)
            om = sum(1 for s in sessions if s["sport"] == sport and not s.get("indoor")
                     and ((s.get("features") or {}).get("weather") or {}).get("source") == "Open-Meteo")

            def est(v, se):
                return f"{v:+.2f} ± {se:.2f}" if v is not None and se else "—"
            print(f"{sport}: {r['sessions']} steady outdoor sessions ({om} {sport} sessions with Open-Meteo), "
                  f"{r['n']} with ≥{heat.MIN_NEIGHBOURS} neighbours, {r['warm']} warm (load ≥ {heat.WARM_PCT:g} %)")
            print(f"  heat response k: measured {est(r['k_hat'], r['k_se'])} → used {r['k']:.2f} "
                  f"(prior {r['prior']['k']:g} ± {heat.PRIOR_SD['k']:g})")
            print(f"  extra HR drift d: measured {est(r['d_hat'], r['d_se'])} points per % → used {r['d']:.2f} "
                  f"(prior {r['prior']['d']:g} ± {heat.PRIOR_SD['d']:g})")
            cov = heat.coverage(sessions, sport)
            if cov:
                print("  per month:  all indoor  Open-Meteo  platform  no-weather  steady  no-EF  usable  warm  max load %")
                for m in cov[-18:]:
                    print(f"  {m['month']:>9} {m['all']:>4} {m['indoor']:>6} {m['open_meteo']:>11} {m['platform']:>9} "
                          f"{m['no_weather']:>11} {m['steady']:>7} {m['no_ef']:>6} {m['usable']:>7} {m['warm']:>5} "
                          f"{m['max_load'] if m['max_load'] is not None else '—':>11}")
            rows = heat.binned(sessions, sport, r["k"], wind)
            if rows:
                print("  efficiency vs neighbours by heat load:  load %   n   as measured   heat adjusted")
                for b in rows:
                    print(f"  {'':40}{b['bin']:>6} {b['n']:>4} {b['raw_pct']:>+11.2f} % {b['adjusted_pct']:>+11.2f} %")
    return 0


def backfill_extras(user, on_progress=None) -> dict:
    """Garmin's weather + heat acclimation for every activity this person has (missing ones only)."""
    from .ingest.garmindb_reader import GarminDbReader, base_dir_from_config
    from .sync import garmin_extras
    from .sync.garmindb_runner import garmin_client

    reader = GarminDbReader(base_dir_from_config(user.garmindb_dir))
    if not reader.available:
        return {"missing": 0, "fetched": 0, "failed": 0}
    items = [(aid, str(start)[:10]) for aid, start in reader.activity_ids(None)]
    client = garmin_client(user)
    result = garmin_extras.backfill(client.connectapi, reader.extras_dir, items, on_progress=on_progress)
    result["vo2max_days"] = garmin_extras.update_vo2max(client.connectapi, reader.extras_dir)
    return result


LABELS = {"name": "Name", "sex": "Sex", "max_hr": "Max HR", "rest_hr": "Resting HR", "lthr": "Threshold HR", "ftp": "FTP", "weight_kg": "Weight"}


def print_profile(user, prof: dict) -> None:
    print(f"\n{prof['name']['value'] or user.id}  ({user.id})")
    for f, label in LABELS.items():
        v = prof[f]["value"]
        unit = {"max_hr": " bpm", "rest_hr": " bpm", "lthr": " bpm", "ftp": " W", "weight_kg": " kg"}.get(f, "")
        shown = f"{v:.0f}{unit}" if isinstance(v, (int, float)) else (v or "—")
        print(f"  {label:<13} {shown:<22} {prof[f]['source']}")


def add_person(conn, a) -> int:
    import getpass
    from datetime import datetime

    from . import accounts
    from .config import load_config
    from .profile import describe
    from .sync.garmindb_runner import login_interactive, run_sync

    print("Connect a Garmin account. Everything else (name, heart-rate zones, FTP, history) is read from Garmin.")
    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")
    if not email or not password:
        print("Email and password are required.", file=sys.stderr)
        return 1
    if (existing := accounts.is_connected(email)):
        print(f"{email} is already connected as '{existing}'.", file=sys.stderr)
        return 1
    user_id = accounts.new_user_id(email, a.id)
    user = accounts.prepare(email, password, user_id, datetime.fromisoformat(a.since) if a.since else None)

    print("Logging in to Garmin Connect…")
    try:
        name = login_interactive(user)
    except Exception as e:
        accounts.discard(user)
        print(f"Login failed: {e}\nNothing was saved — check email/password and run `fitvio add-person` again.",
              file=sys.stderr)
        return 1
    accounts.register(user)
    print(f"Connected as {name or email}.")
    if a.no_sync:
        print(f"Download later with: fitvio sync --user {user_id} --full")
        return 0

    print("Downloading your complete Garmin history. The first time this can take a long while "
          "(years of daily data); later syncs only fetch what is new.")
    user = load_config().user(user_id)
    accounts.shorten_first_download(user, datetime.fromisoformat(a.since) if a.since else None,
                                    lambda line: print("  " + line))
    ok = run_sync(conn, user, full=True, timeout_s=accounts.FULL_SYNC_TIMEOUT_S, on_line=lambda ln: print("  " + ln),
                  on_step=lambda i, n, key, label: print(f"\nStep {i + 1} of {n}: {label}"))
    if not ok:
        err = conn.execute("SELECT last_error FROM sync_status WHERE user_id = ?", (user_id,)).fetchone()[0]
        print(f"Download failed: {err}\nRetry with: fitvio sync --user {user_id} --full", file=sys.stderr)
        return 1
    result = pipeline.ingest(conn, user, full=True)
    print(f"Imported {result['activities']} activities.")
    print_profile(user, describe(conn, user))
    print("\nAll values above come from Garmin and update themselves on every sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

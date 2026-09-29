"""healthdash command line.

  healthdash init-user <user_id> <garmin_email>   create the GarminDB config for a user
  healthdash sync [--user ID] [--full]            GarminDB download + ingest + verdicts
  healthdash ingest [--user ID] [--full]          ingest only (GarminDB data already present)
  healthdash evaluate [--user ID]                 recompute all verdicts
  healthdash backtest [--user ID] [--sport S]     print verdicts over history
  healthdash demo [--days N]                      fill the DB with synthetic data
  healthdash serve [--host H] [--port P]          run the API + wall UI
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
    p = argparse.ArgumentParser(prog="healthdash")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add-person", help="connect a Garmin account (asks for email + password)")
    s.add_argument("--id", help="short id, default: from the email address")
    s.add_argument("--since", help="download health data from this date (YYYY-MM-DD), default: 5 years back")
    s.add_argument("--no-sync", action="store_true", help="only connect, download later with `healthdash sync --full`")
    s = sub.add_parser("profile", help="show what was detected from Garmin")
    s.add_argument("--user")
    s = sub.add_parser("init-user")
    s.add_argument("user_id")
    s.add_argument("email")
    for name in ("sync", "ingest", "evaluate"):
        s = sub.add_parser(name)
        s.add_argument("--user")
        s.add_argument("--full", action="store_true", help="full history instead of latest")
    s = sub.add_parser("backtest")
    s.add_argument("--user")
    s.add_argument("--sport")
    s = sub.add_parser("demo")
    s.add_argument("--days", type=int, default=150)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8765)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()

    if a.cmd == "serve":
        import uvicorn
        uvicorn.run("healthdash.api.main:app", host=a.host, port=a.port)
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
              f"  healthdash sync --user {a.user_id} --full")
        return 0

    if a.cmd == "sync":
        from .sync.garmindb_runner import SyncBusy, changed_since, run_sync
        rc = 0
        for u in _users(cfg, a.user):
            since = None if a.full else changed_since(conn, u.id)  # before the sync moves it
            try:
                ok = run_sync(conn, u, full=a.full)
            except SyncBusy as e:
                print(f"{u.id}: skipped — {e}", file=sys.stderr)
                continue
            if not ok:
                err = conn.execute("SELECT last_error FROM sync_status WHERE user_id = ?", (u.id,)).fetchone()[0]
                print(f"{u.id}: sync failed — {err}", file=sys.stderr)
            try:
                print(u.id, pipeline.ingest_from_garmindb(conn, u, full=a.full, changed_since=since))
            except RuntimeError as e:  # e.g. nothing downloaded yet
                print(f"{u.id}: ingest skipped — {e}", file=sys.stderr)
                rc = 1
            except Exception:  # keep going for the other users
                logging.exception("ingest failed for %s", u.id)
                rc = 1
            rc = rc or (0 if ok else 1)
        return rc

    if a.cmd == "ingest":
        for u in _users(cfg, a.user):
            print(u.id, pipeline.ingest_from_garmindb(conn, u, full=a.full))
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


LABELS = {"name": "Name", "sex": "Sex", "max_hr": "Max HR", "rest_hr": "Resting HR", "lthr": "Threshold HR", "ftp": "FTP"}


def print_profile(user, prof: dict) -> None:
    print(f"\n{prof['name']['value'] or user.id}  ({user.id})")
    for f, label in LABELS.items():
        v = prof[f]["value"]
        unit = {"max_hr": " bpm", "rest_hr": " bpm", "lthr": " bpm", "ftp": " W"}.get(f, "")
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
        print(f"Login failed: {e}\nNothing was saved — check email/password and run `healthdash add-person` again.",
              file=sys.stderr)
        return 1
    accounts.register(user)
    print(f"Connected as {name or email}.")
    if a.no_sync:
        print(f"Download later with: healthdash sync --user {user_id} --full")
        return 0

    print("Downloading your complete Garmin history. The first time this can take a long while "
          "(years of daily data); later syncs only fetch what is new.")
    user = load_config().user(user_id)
    ok = run_sync(conn, user, full=True, timeout_s=accounts.FULL_SYNC_TIMEOUT_S, on_line=lambda ln: print("  " + ln),
                  on_step=lambda i, n, key, label: print(f"\nStep {i + 1} of {n}: {label}"))
    if not ok:
        err = conn.execute("SELECT last_error FROM sync_status WHERE user_id = ?", (user_id,)).fetchone()[0]
        print(f"Download failed: {err}\nRetry with: healthdash sync --user {user_id} --full", file=sys.stderr)
        return 1
    result = pipeline.ingest_from_garmindb(conn, user, full=True)
    print(f"Imported {result['activities']} activities.")
    print_profile(user, describe(conn, user))
    print("\nAll values above come from Garmin and update themselves on every sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

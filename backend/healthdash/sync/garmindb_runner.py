"""Run GarminDB for each user and record sync health.

Each user gets their own GarminDB config dir (credentials, data dir), so accounts never mix.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .. import db
from ..config import PROJECT_ROOT, UserConfig
from ..ingest.garmindb_reader import base_dir_from_config

FAILURE_MARKERS = ("failed to login", "traceback (most recent call last)", "login failed", "401 client error",
                   "403 client error", "too many requests")

log = logging.getLogger(__name__)


def garmindb_command() -> list[str]:
    if os.environ.get("HEALTHDASH_PLAIN_GARMINDB") == "1":  # escape hatch: unpatched GarminDB
        return [garmindb_cli()]
    return [sys.executable, "-m", "healthdash.sync.garmindb_fast"]


def garmindb_cli() -> str:
    exe = Path(sys.executable).parent / "garmindb_cli.py"
    return str(exe) if exe.exists() else (shutil.which("garmindb_cli.py") or "garmindb_cli.py")


def init_user_config(user: UserConfig, email: str, data_root: Path | None = None,
                     since: datetime | None = None) -> Path:
    """Create the GarminDB config for a user. The password goes in a separate chmod-600 file
    that the user fills in themselves; it is never written by this code."""
    import garmindb

    cfg_dir = user.garmindb_dir or (PROJECT_ROOT / "data" / "garmindb" / user.id / "config")
    cfg_dir.mkdir(parents=True, exist_ok=True)
    # Credentials, tokens and health data: readable by the dashboard's user only.
    for d in (cfg_dir, cfg_dir.parent):
        os.chmod(d, 0o700)
    # Paths relative to the person's folder, so the project can be moved or copied to the Pi.
    data_dir = data_root.expanduser() if data_root else Path("HealthData")
    example = Path(garmindb.__file__).parent / "GarminConnectConfig.json.example"
    cfg = json.loads(example.read_text())
    pw_file = cfg_dir / "password.txt"
    if not pw_file.exists():
        pw_file.write_text("")
    os.chmod(pw_file, 0o600)
    start = (since or datetime.now().replace(year=datetime.now().year - 5)).strftime("%m/%d/%Y")
    cfg["credentials"].update({"user": email, "password": "", "password_file": f"{cfg_dir.name}/password.txt"})
    cfg["directories"].update({"relative_to_home": False, "base_dir": str(data_dir)})
    cfg["settings"]["metric"] = True
    for k in ("weight_start_date", "sleep_start_date", "rhr_start_date", "hrv_start_date", "monitoring_start_date"):
        cfg["data"][k] = start
    cfg["data"]["download_all_activities"] = 10000  # i.e. every activity you ever recorded
    (cfg_dir / "GarminConnectConfig.json").write_text(json.dumps(cfg, indent=4))
    os.chmod(cfg_dir / "GarminConnectConfig.json", 0o600)
    return cfg_dir


# GarminDB works through these in order, each over the whole date range (its progress bar restarts
# at 0 % for every one). Matched against its log so the UI can say "step 3 of 10: hydration".
STEPS = [
    ("activities", "Activities", ("Getting activities", "get_activity_types")),
    ("summaries", "Daily summaries", ("Getting daily summaries",)),
    ("hydration", "Hydration", ("Getting hydration",)),
    ("monitoring", "All-day heart rate & monitoring", ("Getting monitoring",)),
    ("sleep", "Sleep", ("Getting sleep",)),
    ("weight", "Weight", ("Getting weight",)),
    ("rhr", "Resting heart rate", ("Getting rhr",)),
    ("hrv", "Heart-rate variability", ("Getting hrv",)),
    ("import", "Importing into the database", ("___Importing",)),
    ("analyze", "Analysing", ("___Analyzing",)),
]


def step_for(log_line: str) -> tuple[int, str, str] | None:
    for i, (key, label, markers) in enumerate(STEPS):
        if any(m in log_line for m in markers):
            return i, key, label
    return None


_LOG_TIME = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3}) ")


def phase_times(log_lines: list[str]) -> dict[str, float]:
    """Seconds per step from GarminDB's timestamped log (garmindb_fast adds the times). Everything
    before the first step (start-up, login) counts as "login"."""
    out: dict[str, float] = {}
    current, since, last = "login", None, None
    for line in log_lines:
        m = _LOG_TIME.match(line)
        if not m:
            continue
        last = datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S,%f")
        since = since or last
        hit = step_for(line)
        if hit and hit[1] != current:
            out[current] = out.get(current, 0.0) + (last - since).total_seconds()
            current, since = hit[1], last
    if since is not None:
        out[current] = out.get(current, 0.0) + (last - since).total_seconds()
    return out


def format_times(times: dict[str, float]) -> str:
    return " · ".join(f"{k} {v:.0f}s" for k, v in times.items())


class LogFollower:
    """Reads what GarminDB appended to its log since the last call (it truncates the file on start)."""

    def __init__(self, path: Path):
        self.path, self.fh, self.buf = path, None, ""

    def new_lines(self) -> list[str]:
        if self.fh is None:
            if not self.path.exists():
                return []
            self.fh = open(self.path, "r", errors="replace")
        if self.path.stat().st_size < self.fh.tell():  # truncated → start over
            self.fh.seek(0)
        self.buf += self.fh.read()
        *lines, self.buf = self.buf.split("\n")
        return lines

    def close(self):
        if self.fh:
            self.fh.close()


def normalize_config(config_dir: Path) -> None:
    """Rewrite absolute data/password paths into paths relative to the person's folder.

    Older configs stored absolute paths; after moving the project (or copying it to the Pi) they
    point to a folder that no longer exists. Everything below .../<person>/ is kept.
    """
    # credentials, tokens, health data and logs: readable by the dashboard's user only
    # (accounts created before this existed had a world-readable person folder)
    for d in (config_dir, config_dir.parent):
        if d.exists():
            os.chmod(d, 0o700)
    f = config_dir / "GarminConnectConfig.json"
    if not f.exists():
        return
    cfg = json.loads(f.read_text())
    person = config_dir.parent.name
    changed = False
    for section, key in (("directories", "base_dir"), ("credentials", "password_file")):
        value = cfg.get(section, {}).get(key)
        if not value or not Path(value).is_absolute():
            continue
        parts = Path(value).parts
        if person in parts:
            i = len(parts) - 1 - parts[::-1].index(person)
            cfg[section][key] = str(Path(*parts[i + 1:]))
            changed = True
    if changed:
        f.write_text(json.dumps(cfg, indent=4))
        os.chmod(f, 0o600)
        log.info("made GarminDB paths relative in %s", f)


SINCE_MARGIN = timedelta(minutes=2)


def changed_since(conn: sqlite3.Connection, user_id: str) -> datetime | None:
    """Start of the last successful sync (minus a safety margin): everything written after it is
    new or changed. None until a first sync has succeeded — then everything is imported."""
    row = conn.execute("SELECT last_success FROM sync_status WHERE user_id = ?", (user_id,)).fetchone()
    if not row or not row[0]:
        return None
    return datetime.fromisoformat(row[0]) - SINCE_MARGIN


class SyncBusy(RuntimeError):
    """Another sync for this person is running (e.g. the timer while you pressed "Sync now")."""


@contextmanager
def sync_lock(user: UserConfig):
    """One GarminDB run per person at a time: two runs on the same data dir corrupt its databases."""
    path = user.garmindb_dir.parent / ".sync.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncBusy(f"a sync for {user.id} is already running") from None
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


# The morning sync: only what the wall shows after a night (sleep, HRV, resting HR, and the daily
# summary with Body Battery / stress, which GarminDB fetches under monitoring). No activities, no weight.
QUICK_STATS = ["--monitoring", "--sleep", "--rhr", "--hrv"]


def run_sync(conn: sqlite3.Connection, user: UserConfig, full: bool = False, timeout_s: int = 1800,
             on_line: Callable[[str], None] | None = None,
             on_step: Callable[[int, int, str, str], None] | None = None, quick: bool = False) -> bool:
    """Run GarminDB for one person. `on_line` receives its output live, `on_step(index, total, key,
    label)` which data type it is working on (progress in the UI). `quick` fetches the health data only
    (QUICK_STATS) and leaves `last_success` alone: the next normal sync still imports everything since
    the last complete one."""
    now = datetime.now().isoformat(timespec="seconds")
    started = time.monotonic()
    row = db.row_to_dict(conn.execute("SELECT * FROM sync_status WHERE user_id = ?", (user.id,)).fetchone()) or {}
    # GarminDB's CLI, run through our wrapper with faster, resumable download loops (garmindb_fast.py)
    stats = QUICK_STATS if quick and not full else ["--all"]
    cmd = [*garmindb_command(), "-f", str(user.garmindb_dir), *stats, "--download", "--import", "--analyze"]
    env = os.environ.copy()
    if not full:
        cmd.append("--latest")
        since = changed_since(conn, user.id)
        if since:
            # differential import: only files written since the last successful sync (garmindb_fast.py)
            env["HEALTHDASH_SYNC_SINCE"] = since.isoformat(timespec="seconds")
    normalize_config(user.garmindb_dir)
    log.info("sync %s: %s (changes since %s)", user.id, " ".join(cmd), env.get("HEALTHDASH_SYNC_SINCE", "-"))
    error = None
    lines: list[str] = []
    try:
        with sync_lock(user):
            # GarminDB writes garmindb.log into its working directory: keep it inside the person's
            # private data dir (700), not in the project root, and separate per person.
            workdir = user.garmindb_dir.parent
            log_file = workdir / "garmindb.log"
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                    stdin=subprocess.DEVNULL, cwd=workdir, env=env)
            timer = threading.Timer(timeout_s, proc.kill)
            timer.start()
            follower = LogFollower(log_file)
            current = -1
            try:
                for line in proc.stdout:
                    if on_step:
                        for log_line in follower.new_lines():
                            hit = step_for(log_line)
                            if hit and hit[0] != current:
                                current = hit[0]
                                on_step(hit[0], len(STEPS), hit[1], hit[2])
                    line = line.rstrip()
                    if line:
                        lines.append(line)
                        del lines[:-200]
                        if on_line:
                            on_line(line)
                rc = proc.wait()
            finally:
                timed_out = not timer.is_alive()
                timer.cancel()
                follower.close()
                if log_file.exists():
                    os.chmod(log_file, 0o600)
                    times = phase_times(log_file.read_text(errors="replace").splitlines())
                    log.info("sync %s%s: garmindb %.0fs — %s", user.id, " (quick)" if quick else "",
                             time.monotonic() - started, format_times(times) or "no step times in log")
            # GarminDB exits 0 even when the login fails, so also look at what it printed.
            hit = next((ln for ln in lines if any(m in ln.lower() for m in FAILURE_MARKERS)), None)
            if timed_out:
                error = f"garmindb timed out after {timeout_s}s"
            elif rc != 0:
                error = "\n".join(lines[-5:])[-500:] or "garmindb failed"
            elif hit:
                error = hit.strip()[:500]
            elif not (base_dir_from_config(user.garmindb_dir) / "DBs" / "garmin_activities.db").exists():
                error = "garmindb finished but produced no activities database"
    except SyncBusy:
        raise
    except OSError as e:
        error = str(e)
    db.upsert(conn, "sync_status", {
        "user_id": user.id, "last_attempt": now,
        "last_success": now if error is None and not quick else row.get("last_success"),
        "last_error": error,
    })
    conn.commit()
    if error:
        log.error("sync %s failed: %s", user.id, error)
    else:
        from . import garmin_coach
        garmin_coach.update_user(conn, user)  # today's training + readiness; never fails the sync
    return error is None


def sync_user(conn: sqlite3.Connection, user: UserConfig, full: bool = False) -> tuple[bool, dict | None]:
    """Download (GarminDB) + ingest + verdicts for one person — what `healthdash sync` does per person.
    Returns (download ok, ingest result or None). Raises SyncBusy when another sync holds the lock."""
    since = None if full else changed_since(conn, user.id)  # before the sync moves it
    ok = run_sync(conn, user, full=full)
    try:
        return ok, timed_ingest(conn, user, full=full, changed_since=since)
    except RuntimeError as e:  # e.g. nothing downloaded yet
        log.warning("%s: ingest skipped — %s", user.id, e)
        return ok, None


def timed_ingest(conn: sqlite3.Connection, user: UserConfig, **kw) -> dict:
    """pipeline.ingest_from_garmindb, with its duration in the log (next to the GarminDB step times)."""
    from .. import pipeline

    started = time.monotonic()
    result = pipeline.ingest_from_garmindb(conn, user, **kw)
    log.info("sync %s: ingest %.0fs", user.id, time.monotonic() - started)
    return result


def garmin_client(user: UserConfig, mfa_prompt: Callable[[], str] | None = None):
    """A logged-in Garmin Connect client for this person (GarminDB's auth adapter). Uses the cached
    login tokens; only falls back to the password (and MFA) when they are missing or expired."""
    from garmindb.garmin_connect_auth_adapter import GarminConnectAuthAdapter
    from garmindb.garmin_connect_config_manager import GarminConnectConfigManager

    normalize_config(user.garmindb_dir)
    gc = GarminConnectConfigManager(str(user.garmindb_dir))
    pw_file = gc.get_node_value_default("credentials", "password_file", None)
    if pw_file and not Path(pw_file).is_absolute():
        # relative to the person's folder; this process runs elsewhere, so resolve it here
        path = user.garmindb_dir.parent / pw_file
        gc.get_password = lambda: path.read_text().strip()
    adapter = GarminConnectAuthAdapter(gc, mfa_prompt=mfa_prompt)
    adapter.login()  # raises GarminConnectAuthError on bad credentials
    return adapter


def login_interactive(user: UserConfig, mfa_prompt: Callable[[], str] | None = None) -> str | None:
    """First login in this process, so Garmin's MFA prompt (if enabled) can be answered — in the
    terminal by default, or via `mfa_prompt` (the web UI). GarminDB caches the resulting tokens in
    the config dir; background syncs reuse them. Returns the full name from the Garmin profile."""
    adapter = garmin_client(user, mfa_prompt)
    return adapter.full_name or adapter.display_name

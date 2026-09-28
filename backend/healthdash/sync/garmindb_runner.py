"""Run GarminDB for each user and record sync health.

Each user gets their own GarminDB config dir (credentials, data dir), so accounts never mix.
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable

from .. import db
from ..config import PROJECT_ROOT, UserConfig
from ..ingest.garmindb_reader import base_dir_from_config

FAILURE_MARKERS = ("failed to login", "traceback (most recent call last)", "login failed", "401 client error",
                   "403 client error", "too many requests")

log = logging.getLogger(__name__)


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
    data_dir = (data_root or cfg_dir.parent / "HealthData").expanduser()
    example = Path(garmindb.__file__).parent / "GarminConnectConfig.json.example"
    cfg = json.loads(example.read_text())
    pw_file = cfg_dir / "password.txt"
    if not pw_file.exists():
        pw_file.write_text("")
    os.chmod(pw_file, 0o600)
    start = (since or datetime.now().replace(year=datetime.now().year - 5)).strftime("%m/%d/%Y")
    cfg["credentials"].update({"user": email, "password": "", "password_file": str(pw_file)})
    cfg["directories"].update({"relative_to_home": False, "base_dir": str(data_dir)})
    cfg["settings"]["metric"] = True
    for k in ("weight_start_date", "sleep_start_date", "rhr_start_date", "hrv_start_date", "monitoring_start_date"):
        cfg["data"][k] = start
    cfg["data"]["download_all_activities"] = 10000  # i.e. every activity you ever recorded
    (cfg_dir / "GarminConnectConfig.json").write_text(json.dumps(cfg, indent=4))
    os.chmod(cfg_dir / "GarminConnectConfig.json", 0o600)
    return cfg_dir


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


def run_sync(conn: sqlite3.Connection, user: UserConfig, full: bool = False, timeout_s: int = 1800,
             on_line: Callable[[str], None] | None = None) -> bool:
    """Run GarminDB for one person. `on_line` receives its output live (progress in the UI)."""
    now = datetime.now().isoformat(timespec="seconds")
    row = db.row_to_dict(conn.execute("SELECT * FROM sync_status WHERE user_id = ?", (user.id,)).fetchone()) or {}
    cmd = [garmindb_cli(), "-f", str(user.garmindb_dir), "--all", "--download", "--import", "--analyze"]
    if not full:
        cmd.append("--latest")
    log.info("sync %s: %s", user.id, " ".join(cmd))
    error = None
    lines: list[str] = []
    try:
        with sync_lock(user):
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                                    stdin=subprocess.DEVNULL)
            timer = threading.Timer(timeout_s, proc.kill)
            timer.start()
            try:
                for line in proc.stdout:
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
        "last_success": now if error is None else row.get("last_success"),
        "last_error": error,
    })
    conn.commit()
    if error:
        log.error("sync %s failed: %s", user.id, error)
    return error is None


def login_interactive(user: UserConfig, mfa_prompt: Callable[[], str] | None = None) -> str | None:
    """First login in this process, so Garmin's MFA prompt (if enabled) can be answered — in the
    terminal by default, or via `mfa_prompt` (the web UI). GarminDB caches the resulting tokens in
    the config dir; background syncs reuse them. Returns the full name from the Garmin profile."""
    from garmindb.garmin_connect_auth_adapter import GarminConnectAuthAdapter
    from garmindb.garmin_connect_config_manager import GarminConnectConfigManager

    adapter = GarminConnectAuthAdapter(GarminConnectConfigManager(str(user.garmindb_dir)), mfa_prompt=mfa_prompt)
    adapter.login()  # raises GarminConnectAuthError on bad credentials
    return adapter.full_name or adapter.display_name

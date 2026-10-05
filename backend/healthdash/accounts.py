"""Connecting Garmin accounts and running syncs as background jobs.

Used by the web UI (Accounts screen) and the `add-person` CLI. A connect job walks through:
    logging_in → (mfa_required → logging_in) → downloading → importing → done | error
The password is written once to the person's chmod-600 password file and never kept, logged or
returned by the API.
"""
from __future__ import annotations

import logging
import re
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import db, pipeline
from .config import UserConfig, add_user, load_config
from .sync.garmindb_runner import (SyncBusy, changed_since, init_user_config, login_interactive, run_sync,
                                   timed_ingest)

log = logging.getLogger(__name__)

MFA_TIMEOUT_S = 300
FULL_SYNC_TIMEOUT_S = 12 * 3600  # 5 years × 8 data types at ~1 s/day ≈ 5–6 h


# --- account setup steps (shared by CLI and web) --------------------------------

def new_user_id(email: str, requested: str | None = None) -> str:
    existing = {u.id for u in load_config().users}
    base = requested or re.sub(r"[^a-z0-9]+", "_", email.split("@")[0].lower()).strip("_") or "person"
    user_id, n = base, 2
    while user_id in existing:
        user_id, n = f"{base}_{n}", n + 1
    return user_id


def prepare(email: str, password: str, user_id: str, since: datetime | None = None) -> UserConfig:
    """Write the GarminDB config + password file for a not-yet-registered person."""
    user = UserConfig(id=user_id, garmindb_config_dir=f"data/garmindb/{user_id}/config")
    cfg_dir = init_user_config(user, email, since=since)
    (cfg_dir / "password.txt").write_text(password)  # chmod 600, set by init_user_config
    return user


def discard(user: UserConfig) -> None:
    """Undo `prepare` after a failed login, so nothing half-configured is left behind."""
    if user.garmindb_dir:
        shutil.rmtree(user.garmindb_dir.parent, ignore_errors=True)


def register(user: UserConfig) -> None:
    add_user(user.id, user.garmindb_config_dir)


def is_connected(email: str) -> str | None:
    """User id already connected with this Garmin email, if any."""
    import json
    for u in load_config().users:
        f = u.garmindb_dir / "GarminConnectConfig.json" if u.garmindb_dir else None
        if f and f.exists():
            try:
                if json.loads(f.read_text())["credentials"]["user"].lower() == email.lower():
                    return u.id
            except (ValueError, KeyError):
                pass
    return None


# --- background jobs -----------------------------------------------------------------

@dataclass
class Job:
    kind: str                       # connect | sync
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str | None = None
    phase: str = "logging_in"
    message: str = ""
    error: str | None = None
    name: str | None = None
    result: dict | None = None
    log: list[str] = field(default_factory=list)
    step: str | None = None          # e.g. "Hydration" — GarminDB's current data type
    step_index: int | None = None    # 0-based
    step_total: int | None = None
    started_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    finished_at: str | None = None
    _mfa_event: threading.Event = field(default_factory=threading.Event, repr=False)
    _mfa_code: str | None = field(default=None, repr=False)

    def on_step(self, index: int, total: int, key: str, label: str) -> None:
        self.step, self.step_index, self.step_total = label, index, total
        self.log.clear()  # the previous step's progress bar is finished; don't show it as current

    def line(self, text: str) -> None:
        self.log.append(text)
        del self.log[:-8]

    def public(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    @property
    def active(self) -> bool:
        return self.phase not in ("done", "error")


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def active_for(user_id: str) -> Job | None:
    with _lock:
        return next((j for j in reversed(list(_jobs.values())) if j.user_id == user_id and j.active), None)


def connect_in_progress() -> bool:
    with _lock:
        return any(j.kind == "connect" and j.active for j in _jobs.values())


def submit_mfa(job_id: str, code: str) -> bool:
    job = _jobs.get(job_id)
    if not job or job.phase != "mfa_required":
        return False
    job._mfa_code = code.strip()
    job._mfa_event.set()
    return True


def _add(job: Job) -> Job:
    with _lock:
        _jobs[job.id] = job
        # keep memory bounded: forget old finished jobs
        for old in [j for j in _jobs.values() if not j.active][:-20]:
            _jobs.pop(old.id, None)
    return job


def result_message(result: dict, full: bool) -> str:
    n, u = result.get("activities", 0), result.get("updated", 0)
    if full:
        return f"{n} activities imported"
    parts = []
    if n:
        parts.append(f"{n} new activit{'y' if n == 1 else 'ies'}")
    if u:
        parts.append(f"{u} updated")
    return " · ".join(parts) or "Up to date"


def _download_and_import(job: Job, user: UserConfig, db_path: Path, full: bool, quick: bool = False) -> None:
    conn = db.connect(db_path)
    try:
        job.phase = "downloading"
        job.message = ("Downloading your complete Garmin history — the first time this can take a long while"
                       if full else "Fetching last night's data from Garmin" if quick else "Fetching new data from Garmin")
        # read before the sync: a successful run moves this marker forward (a quick one only fetches
        # health data, so it has no edited activities to look for)
        since = None if full or quick else changed_since(conn, user.id)
        try:
            ok = run_sync(conn, user, full=full, timeout_s=FULL_SYNC_TIMEOUT_S if full else 1800,
                          on_line=job.line, on_step=job.on_step, quick=quick)
        except SyncBusy as e:
            job.phase, job.error = "error", str(e)
            return
        if not ok:
            err = conn.execute("SELECT last_error FROM sync_status WHERE user_id = ?", (user.id,)).fetchone()[0]
            job.phase, job.error = "error", f"Download failed: {err}"
            return
        if full:
            # Garmin's weather + heat acclimation for the whole history (what Garmin Connect shows)
            from .cli import backfill_extras
            job.message = "Loading weather and heat acclimation for your activities"
            job.on_step(10, 11, "extras", "Weather & heat acclimation")
            try:
                backfill_extras(user, on_progress=lambda i, n: job.line(f"{i}/{n} activities"))
            except Exception as e:  # nice-to-have: never fail the first import because of it
                log.warning("extras backfill failed for %s: %s", user.id, e)
        job.phase = "importing"
        job.message = "Analysing your activities and working out every verdict"
        job.result = timed_ingest(conn, user, full=full, changed_since=since)
        job.phase = "done"
        job.message = result_message(job.result, full)
    except Exception as e:  # surface anything unexpected in the UI instead of a silent dead thread
        log.exception("job %s failed", job.id)
        job.phase, job.error = "error", str(e)
    finally:
        job.finished_at = datetime.now().isoformat(timespec="seconds")
        conn.close()


def start_connect(email: str, password: str, db_path: Path, on_registered: Callable[[], None] = lambda: None,
                  since: datetime | None = None) -> Job:
    job = _add(Job(kind="connect", message="Logging in to Garmin Connect"))

    def mfa_prompt() -> str:
        job.phase, job.message = "mfa_required", "Enter the security code Garmin just sent you"
        if not job._mfa_event.wait(MFA_TIMEOUT_S):
            raise TimeoutError("no security code entered within 5 minutes")
        job.phase, job.message = "logging_in", "Checking the code"
        return job._mfa_code or ""

    def run():
        user_id = new_user_id(email)
        user = prepare(email, password, user_id, since)
        try:
            job.name = login_interactive(user, mfa_prompt=mfa_prompt)
        except Exception as e:
            discard(user)
            job.phase, job.error = "error", f"Login failed: {e}"
            job.finished_at = datetime.now().isoformat(timespec="seconds")
            return
        register(user)
        job.user_id = user_id
        on_registered()
        _download_and_import(job, load_config().user(user_id), db_path, full=True)

    threading.Thread(target=run, name=f"connect-{job.id}", daemon=True).start()
    return job


def start_sync(user: UserConfig, db_path: Path, full: bool = False, quick: bool = False) -> Job:
    running = active_for(user.id)
    if running:
        return running
    if not full:
        # Nothing imported yet (e.g. the first download was interrupted): "latest" would only look at
        # the last days, so fetch the whole history. Cached days are skipped, so this resumes quickly.
        conn = db.connect(db_path)
        try:
            full = conn.execute("SELECT 1 FROM sessions WHERE user_id = ? LIMIT 1", (user.id,)).fetchone() is None
        finally:
            conn.close()
    job = _add(Job(kind="sync", user_id=user.id, phase="downloading"))
    threading.Thread(target=_download_and_import, args=(job, user, db_path, full, quick and not full),
                     name=f"sync-{job.id}", daemon=True).start()
    return job

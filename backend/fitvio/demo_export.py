"""The try-it demo on GitHub Pages: made-up people and made-up data, exported as the JSON the API would serve.

Never reads config/ or data/: the people are defined here, the database lives in a temporary folder, and
the output is checked for anything that looks personal before it is written. The frontend's demo build
(VITE_DEMO=1, see frontend/src/demo/) reads these files instead of calling the server.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import unquote

# Two made-up athletes: Alex trains for several sports and improves (Garmin), Sam runs and lifts (Intervals.icu).
# The source folders are placeholders that nothing reads; they only tell the UI where the data "comes from".
DEMO_USERS = [
    {"id": "alex", "name": "Alex", "color": "#3B82F6", "garmindb_config_dir": "demo/alex/garmin"},
    {"id": "sam", "name": "Sam", "color": "#F97316", "intervals_dir": "demo/sam/intervals"},
]
# Every range a screen asks for (phone Trends, wall Health and Load pages) plus the API defaults.
PMC_DAYS = (42, 90, 180, 365)
HEALTH_DAYS = (7, 30, 90, 180, 365)
PAGE = 500  # the API's largest page

# Never publish anything that looks like a home network, an email address or a local path.
LEAK_PATTERNS = [re.compile(p) for p in (r"192\.168\.", r"\b10\.\d+\.\d+\.\d+\b", r"[\w.+-]+@[\w-]+\.[\w.]+",
                                         r"/Users/", r"/home/", r"config/users")]


def file_for(path: str) -> str:
    """The file an API GET path is exported to: /api/users/alex/pmc?days=90 → users/alex/pmc-90.json.
    Anything but letters, digits, '.', '-' and '/' becomes '_' (session ids hold a ':').
    frontend/src/demo/demoApi.ts maps paths the same way."""
    route, _, query = unquote(path).removeprefix("/api/").partition("?")
    days = re.search(r"(?:^|&)days=(\d+)", query)
    return re.sub(r"[^A-Za-z0-9./-]", "_", route) + (f"-{days.group(1)}" if days else "") + ".json"


def export(out_dir: Path, days: int = 150, deny: list[str] | None = None) -> dict[str, int]:
    """Generate the demo in a temporary database and write every GET response the UI uses to `out_dir`."""
    tmp = Path(tempfile.mkdtemp(prefix="fitvio-demo-"))
    saved = {k: os.environ.get(k) for k in ("FITVIO_CONFIG", "FITVIO_DB")}
    try:
        (tmp / "users.json").write_text(json.dumps({"users": DEMO_USERS}))
        os.environ["FITVIO_CONFIG"] = str(tmp / "users.json")
        os.environ["FITVIO_DB"] = str(tmp / "app.db")
        files = _export(out_dir, days)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(tmp, ignore_errors=True)
    check_no_leaks(out_dir, deny or [])
    return files


def _export(out_dir: Path, days: int) -> dict[str, int]:
    from fastapi.testclient import TestClient

    from . import db
    from .api import main as api
    from .config import load_config
    from .demo import generate

    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per exported file is noise
    cfg = load_config()
    assert [u.id for u in cfg.users] == [u["id"] for u in DEMO_USERS], "the demo must only use its own people"
    conn = db.connect(cfg.db_path)
    try:
        generate(conn, cfg, days=days)
    finally:
        conn.close()
    api.reset_config()
    client = TestClient(api.app)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    counts = {"files": 0, "sessions": 0}

    def save(path: str, data=None):
        if data is None:
            r = client.get(path)
            r.raise_for_status()
            data = r.json()
        f = out_dir / file_for(path)
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
        counts["files"] += 1
        return data

    for path in ("/api/config", "/api/wall", "/api/accounts", "/api/settings/buddy", "/api/settings/activity-check"):
        save(path)
    for u in cfg.users:
        base = f"/api/users/{u.id}"
        for path in ("ambient", "profile", "validation", "weather", "heat"):
            save(f"{base}/{path}")
        for d in PMC_DAYS:
            save(f"{base}/pmc?days={d}")
        for d in HEALTH_DAYS:
            save(f"{base}/health?days={d}")
        sessions = []
        while page := client.get(f"{base}/sessions?limit={PAGE}&offset={len(sessions)}").raise_for_status().json():
            sessions += page
        save(f"{base}/sessions", sessions)  # the demo filters and pages these in the browser
        for s in sessions:
            save(f"/api/sessions/{s['id']}")
        counts["sessions"] += len(sessions)
    return counts


def check_no_leaks(out_dir: Path, deny: list[str]) -> None:
    """Fails if an exported file contains a denied word (e.g. real names, passed in locally) or anything that
    looks like a home address, an email address or a local path."""
    words = [w.strip().lower() for w in deny if w.strip()]
    for f in sorted(out_dir.rglob("*.json")):
        text = f.read_text()
        low = text.lower()
        hits = [w for w in words if re.search(rf"\b{re.escape(w)}\b", low)]
        hits += [p.pattern for p in LEAK_PATTERNS if p.search(text)]
        if hits:
            raise ValueError(f"{f.relative_to(out_dir)} contains {', '.join(sorted(set(hits)))}: not publishing it")

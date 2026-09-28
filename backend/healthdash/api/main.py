"""FastAPI backend for the wall tablet. Serves the built frontend too."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import accounts, db, profile, wall
from ..analytics import load as load_model
from ..config import PROJECT_ROOT, AppConfig, load_config
from ..pipeline import user_sessions

app = FastAPI(title="Health Dashboard", docs_url=None, redoc_url=None, openapi_url=None)
_cfg: AppConfig | None = None

# Extra hostnames the wall may be reached by (e.g. "healthwall" or "pi.fritz.box"), comma-separated.
EXTRA_HOSTS = {h.strip().lower() for h in os.environ.get("HEALTHDASH_ALLOWED_HOSTS", "").split(",") if h.strip()}
LOCAL_SUFFIXES = (".local", ".lan", ".home", ".internal", ".fritz.box", ".home.arpa")

SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",  # nobody can embed the login form in a frame (clickjacking)
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": ("default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                                "font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
                                "form-action 'self'"),
}


def host_allowed(host: str) -> bool:
    """Only answer to IP literals, localhost and local-network names. Blocks DNS-rebinding attacks,
    where a malicious website points its own domain at the Pi to talk to the API from the tablet."""
    try:
        name = (urlsplit(f"//{host}").hostname or "").lower()  # drops the port, unwraps [IPv6]
    except ValueError:
        return False
    if not name:
        return False
    if name in {"localhost", "testserver"} or name in EXTRA_HOSTS or name.endswith(LOCAL_SUFFIXES):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return "." not in name  # bare LAN hostnames like "raspberrypi"


@app.middleware("http")
async def guard(request: Request, call_next):
    host = request.headers.get("host", "")
    if not host_allowed(host):
        return JSONResponse({"detail": "unknown host"}, status_code=421)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        # State-changing requests must come from the dashboard page itself.
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc.lower() != host.lower():
            return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
    response = await call_next(request)
    for k, v in SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def cfg() -> AppConfig:
    global _cfg
    if _cfg is None:
        _cfg = load_config()
    return _cfg


def conn(c: AppConfig = Depends(cfg)):
    cn = db.connect(c.db_path)
    try:
        yield cn
    finally:
        cn.close()


def _user_or_404(c: AppConfig, user_id: str):
    try:
        return c.user(user_id)
    except KeyError:
        raise HTTPException(404, f"unknown user {user_id}")


@app.get("/api/config")
def get_config(c: AppConfig = Depends(cfg), cn=Depends(conn)):
    users = [profile.resolve(cn, u) for u in c.users]  # names come from the Garmin profile
    return {
        "users": [{"id": u.id, "name": u.display_name, "color": u.color, "initials": u.initials} for u in users],
        "wall": {"idle_return_seconds": c.wall.idle_return_seconds, "night_start": c.wall.night_start,
                 "night_end": c.wall.night_end, "verdict_minutes": c.wall.verdict_minutes},
    }


@app.get("/api/wall")
def get_wall(c: AppConfig = Depends(cfg), cn=Depends(conn)):
    if not c.users:
        return {"mode": "setup", "job": None}
    if cn.execute("SELECT 1 FROM sessions LIMIT 1").fetchone() is None:
        # Connected, but the first download isn't finished: keep showing its progress, not an empty wall.
        job = next((j for j in (accounts.active_for(u.id) for u in c.users) if j), None)
        return {"mode": "setup", "job": job.public() if job else None, "user_id": c.users[0].id}
    fresh = wall.fresh_verdict(cn, c)
    selected = db.get_state(cn, "selected_user", c.users[0].id)
    if selected not in {u.id for u in c.users}:
        selected = c.users[0].id
    if fresh:
        wall.mark_shown(cn, fresh["session_id"])
        return {"mode": "verdict", "user_id": fresh["user_id"],
                "session": wall.session_card(cn, fresh["session_id"]),
                "ambient": wall.ambient(cn, c, fresh["user_id"])}
    return {"mode": "ambient", "user_id": selected, "ambient": wall.ambient(cn, c, selected)}


class Select(BaseModel):
    user_id: str


class Dismiss(BaseModel):
    session_id: str


@app.post("/api/wall/select")
def select_user(body: Select, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    _user_or_404(c, body.user_id)
    db.set_state(cn, "selected_user", body.user_id)
    fresh = wall.fresh_verdict(cn, c)
    if fresh:  # an explicit tap on an avatar beats the automatic takeover
        wall.dismiss(cn, fresh["session_id"], c)
    return {"ok": True}


@app.post("/api/wall/dismiss")
def dismiss(body: Dismiss, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    wall.dismiss(cn, body.session_id, c)
    return {"ok": True}


@app.get("/api/users/{user_id}/ambient")
def get_ambient(user_id: str, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    _user_or_404(c, user_id)
    return wall.ambient(cn, c, user_id)


@app.get("/api/users/{user_id}/sessions")
def list_sessions(user_id: str, sport: str | None = None, limit: int = Query(60, ge=1, le=500), c: AppConfig = Depends(cfg),
                  cn=Depends(conn)):
    _user_or_404(c, user_id)
    q = """SELECT s.id, s.name, s.sport, s.session_type, s.start_time, s.duration_s, s.distance_m, s.avg_hr,
                  s.load, s.rpe, s.feel, s.features, v.verdict, v.headline, v.confidence
           FROM sessions s LEFT JOIN verdicts v ON v.session_id = s.id WHERE s.user_id = ?"""
    args: list = [user_id]
    if sport:
        q += " AND s.sport = ?"
        args.append(sport)
    q += " ORDER BY s.start_time DESC LIMIT ?"
    args.append(min(limit, 500))
    return [db.row_to_dict(r) for r in cn.execute(q, args)]


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str, cn=Depends(conn)):
    s = wall.session_detail(cn, session_id)
    if not s:
        raise HTTPException(404, "session not found")
    return s


@app.get("/api/users/{user_id}/pmc")
def get_pmc(user_id: str, days: int = Query(180, ge=1, le=3650), c: AppConfig = Depends(cfg), cn=Depends(conn)):
    _user_or_404(c, user_id)
    sessions = user_sessions(cn, user_id)
    series = load_model.pmc(load_model.daily_loads(sessions), None, date.today()) if sessions else []
    return series[-days:]


@app.get("/api/users/{user_id}/health")
def get_health(user_id: str, days: int = Query(90, ge=1, le=3650), c: AppConfig = Depends(cfg), cn=Depends(conn)):
    _user_or_404(c, user_id)
    d0 = (date.today() - timedelta(days=days)).isoformat()
    return [dict(r) for r in cn.execute("SELECT * FROM health_days WHERE user_id = ? AND day >= ? ORDER BY day",
                                        (user_id, d0))]


@app.get("/api/users/{user_id}/profile")
def get_profile(user_id: str, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    return profile.describe(cn, _user_or_404(c, user_id))


@app.get("/api/users/{user_id}/validation")
def get_validation(user_id: str, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    _user_or_404(c, user_id)
    return wall.validation(cn, user_id)


@app.get("/api/events")
async def events(request: Request, c: AppConfig = Depends(cfg)):
    """Server-sent events: pushes 'refresh' whenever a verdict or sync status changes."""

    def fingerprint() -> str:
        cn = db.connect(c.db_path)
        try:
            v = cn.execute("SELECT MAX(created_at) AS m, COUNT(*) AS n FROM verdicts").fetchone()
            s = cn.execute("SELECT MAX(last_attempt) AS m FROM sync_status").fetchone()
            return f"{v['m']}|{v['n']}|{s['m']}"
        finally:
            cn.close()

    async def stream():
        last = fingerprint()
        yield "event: hello\ndata: {}\n\n"
        while not await request.is_disconnected():
            await asyncio.sleep(10)
            fp = fingerprint()
            if fp != last:
                last = fp
                yield f"event: refresh\ndata: {json.dumps({'at': fp})}\n\n"
            else:
                yield ": keep-alive\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- accounts (connect Garmin from the UI) -------------------------------------

def local_network_only(request: Request) -> None:
    """The dashboard speaks plain HTTP, so Garmin credentials may only be sent from the home network."""
    host = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise HTTPException(403, "account setup is only allowed from your home network")
    if not (ip.is_private or ip.is_loopback):
        raise HTTPException(403, "account setup is only allowed from your home network")


def reset_config() -> None:
    global _cfg
    _cfg = None


class Connect(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class Mfa(BaseModel):
    code: str = Field(pattern=r"^[0-9]{4,10}$")


@app.get("/api/accounts")
def list_accounts(c: AppConfig = Depends(cfg), cn=Depends(conn)):
    out = []
    for u in c.users:
        r = profile.resolve(cn, u)
        job = accounts.active_for(u.id)
        out.append({"id": u.id, "name": r.display_name, "color": u.color, "initials": r.initials,
                    "sync": wall.sync_info(cn, c, u.id), "job": job.public() if job else None,
                    "activities": cn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (u.id,)).fetchone()[0],
                    "profile": profile.describe(cn, u)})
    return out


@app.post("/api/accounts", dependencies=[Depends(local_network_only)])
def connect_account(body: Connect, c: AppConfig = Depends(cfg)):
    email = body.email.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "please enter a valid email address")
    if accounts.connect_in_progress():
        raise HTTPException(429, "another account is being connected — wait for it to finish")
    if (existing := accounts.is_connected(email)):
        raise HTTPException(409, f"this Garmin account is already connected (as '{existing}')")
    job = accounts.start_connect(email, body.password, c.db_path, on_registered=reset_config)
    return job.public()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = accounts.get(job_id)
    if not job:
        raise HTTPException(404, "job not found (the server may have restarted)")
    return job.public()


@app.post("/api/jobs/{job_id}/mfa", dependencies=[Depends(local_network_only)])
def post_mfa(job_id: str, body: Mfa):
    if not accounts.submit_mfa(job_id, body.code):
        raise HTTPException(409, "this login is not waiting for a code")
    return {"ok": True}


@app.post("/api/users/{user_id}/sync", dependencies=[Depends(local_network_only)])
def sync_now(user_id: str, full: bool = False, c: AppConfig = Depends(cfg)):
    return accounts.start_sync(_user_or_404(c, user_id), c.db_path, full=full).public()


@app.get("/api/health")
def healthcheck():
    return {"ok": True}


# --- built frontend (SPA) ---------------------------------------------------
DIST = PROJECT_ROOT / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")

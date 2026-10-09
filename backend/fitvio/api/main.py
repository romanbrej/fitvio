"""FastAPI backend for the wall tablet. Serves the built frontend too."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import re
from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import accounts, buddy, db, heat_response, pipeline, profile, wall, weather
from ..analytics import load as load_model
from ..config import PROJECT_ROOT, AppConfig, env, load_config
from ..pipeline import user_sessions
from ..sync import activity_watch

class SafeJSONResponse(JSONResponse):
    """Non-finite numbers become null instead of an HTTP 500, so one bad value from a provider
    can't take down the shared wall for the whole household."""

    def render(self, content) -> bytes:
        return json.dumps(db.finite(content), ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")


app = FastAPI(title="Fitvio", docs_url=None, redoc_url=None, openapi_url=None,
              default_response_class=SafeJSONResponse)
_cfg: AppConfig | None = None

# Extra hostnames the wall may be reached by (e.g. "fitvio" or "pi.fritz.box"), comma-separated.
EXTRA_HOSTS = {h.strip().lower() for h in env("ALLOWED_HOSTS", "").split(",") if h.strip()}
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
    where a malicious website points its own domain at the server to talk to the API from the wall display."""
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
        return "." not in name  # bare LAN hostnames like "homeserver"


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
    # A tap on an avatar doesn't end a takeover: the wall pauses it on screen and it comes back when idle.
    # Only "Overview" on the verdict (/api/wall/dismiss) ends it early.
    db.set_state(cn, "selected_user", body.user_id)
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
def list_sessions(user_id: str, sport: str | None = None, limit: int = Query(60, ge=1, le=500),
                  offset: int = Query(0, ge=0), session_type: str | None = Query(None, alias="type", max_length=20),
                  c: AppConfig = Depends(cfg), cn=Depends(conn)):
    """Newest first. `offset` pages through the whole history (the phone loads 50 at a time); `type` = session type."""
    _user_or_404(c, user_id)
    q = """SELECT s.id, s.name, s.sport, s.session_type, s.start_time, s.duration_s, s.distance_m, s.avg_hr,
                  s.load, s.rpe, s.feel, s.features, v.verdict, v.headline, v.confidence,
                  x.session_id IS NOT NULL AS excluded
           FROM sessions s LEFT JOIN verdicts v ON v.session_id = s.id
           LEFT JOIN baseline_exclusions x ON x.session_id = s.id WHERE s.user_id = ?"""
    args: list = [user_id]
    if sport:
        q += " AND s.sport = ?"
        args.append(sport)
    if session_type:
        q += " AND s.session_type = ?"
        args.append(session_type)
    q += " ORDER BY s.start_time DESC, s.id DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    return [db.row_to_dict(r) for r in cn.execute(q, args)]


@app.get("/api/users/{user_id}/session-types")
def session_types(user_id: str, sport: str | None = None, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    """How many sessions of each type (easy, long, …) someone has — the phone's filter chips."""
    _user_or_404(c, user_id)
    q = "SELECT session_type AS type, COUNT(*) AS count FROM sessions WHERE user_id = ?"
    args: list = [user_id]
    if sport:
        q += " AND sport = ?"
        args.append(sport)
    q += " GROUP BY session_type ORDER BY count DESC"
    return [{"type": r["type"], "count": r["count"]} for r in cn.execute(q, args)]


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
    return wall.health_series(cn, user_id, days)


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

    def fingerprint() -> str:  # blocking SQLite: runs in a worker thread, not on the event loop
        cn = db.connect(c.db_path)
        try:
            v = cn.execute("SELECT MAX(created_at) AS m, COUNT(*) AS n FROM verdicts").fetchone()
            s = cn.execute("SELECT MAX(last_attempt) AS m FROM sync_status").fetchone()
            return f"{v['m']}|{v['n']}|{s['m']}"
        finally:
            cn.close()

    async def stream():
        last = await asyncio.to_thread(fingerprint)
        yield "event: hello\ndata: {}\n\n"
        while not await request.is_disconnected():
            await asyncio.sleep(10)
            fp = await asyncio.to_thread(fingerprint)
            if fp != last:
                last = fp
                yield f"event: refresh\ndata: {json.dumps({'at': fp})}\n\n"
            else:
                yield ": keep-alive\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- accounts (connect Garmin from the UI) -------------------------------------

# Home-network address ranges, listed explicitly: Python's is_private also counts internet tunnel
# prefixes (Teredo 2001::/32, 6to4 2002::/16) and other special ranges as private.
HOME_NETWORKS = tuple(ipaddress.ip_network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8",  # RFC 1918, link-local, loopback
    "fc00::/7", "fe80::/10", "::1/128"))                                              # ULA, link-local, loopback


def local_network_only(request: Request) -> None:
    """The dashboard speaks plain HTTP, so Garmin credentials may only be sent from the home network."""
    host = request.client.host if request.client else ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        raise HTTPException(403, "changes are only allowed from your home network")
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped  # a dual-stack socket reports IPv4 clients as ::ffff:a.b.c.d
    if not any(ip in net for net in HOME_NETWORKS):
        raise HTTPException(403, "changes are only allowed from your home network")


def reset_config() -> None:
    global _cfg
    _cfg = None


class Connect(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class Mfa(BaseModel):
    code: str = Field(pattern=r"^[0-9]{4,10}$")


class ConnectIntervals(BaseModel):
    athlete_id: str = Field(min_length=1, max_length=120)
    api_key: str = Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class ProfileOverride(BaseModel):
    model_config = {"extra": "forbid"}
    max_hr: float | None = Field(default=None, ge=140, le=230)
    rest_hr: float | None = Field(default=None, ge=30, le=100)


@app.get("/api/accounts")
def list_accounts(c: AppConfig = Depends(cfg), cn=Depends(conn)):
    out = []
    for u in c.users:
        r = profile.resolve(cn, u)
        job = accounts.active_for(u.id)
        out.append({"id": u.id, "name": r.display_name, "color": u.color, "initials": r.initials, "source": u.source,
                    "sync": wall.sync_info(cn, c, u.id), "job": job.public() if job else None,
                    "activities": cn.execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (u.id,)).fetchone()[0],
                    "profile": profile.describe(cn, u)})
    return out


@app.post("/api/accounts", dependencies=[Depends(local_network_only)])
def connect_account(body: Connect, c: AppConfig = Depends(cfg)):
    email = body.email.strip()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "please enter a valid email address")
    if (existing := accounts.is_connected(email)):
        raise HTTPException(409, f"this Garmin account is already connected (as '{existing}')")
    try:
        job = accounts.start_connect(email, body.password, c.db_path, on_registered=reset_config)
    except accounts.ConnectBusy as e:
        raise HTTPException(429, str(e)) from None
    return job.public()


@app.post("/api/accounts/intervals", dependencies=[Depends(local_network_only)])
def connect_intervals(body: ConnectIntervals, c: AppConfig = Depends(cfg)):
    from ..ingest.intervals_reader import normalize_athlete_id
    try:
        athlete_id = normalize_athlete_id(body.athlete_id)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    if (existing := accounts.intervals_connected(athlete_id)):
        raise HTTPException(409, f"this Intervals.icu athlete is already connected (as '{existing}')")
    try:
        job = accounts.start_connect_intervals(athlete_id, body.api_key, c.db_path, on_registered=reset_config)
    except accounts.ConnectBusy as e:
        raise HTTPException(429, str(e)) from None
    return job.public()


class WeatherChoice(BaseModel):
    model_config = {"extra": "forbid"}
    open_meteo: bool = Field(strict=True)


@app.get("/api/users/{user_id}/weather")
def get_weather_setting(user_id: str, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    _user_or_404(c, user_id)
    return {"open_meteo": weather.enabled(cn, user_id)}


@app.put("/api/users/{user_id}/weather", dependencies=[Depends(local_network_only)])
def set_weather_setting(user_id: str, body: WeatherChoice, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    """Open-Meteo's hourly weather (on) or only what Garmin / Intervals.icu give (off). Every verdict is
    worked out again from what is already downloaded; weather fetched before stays cached."""
    user = _user_or_404(c, user_id)
    if weather.enabled(cn, user.id) != body.open_meteo:
        weather.set_enabled(cn, user.id, body.open_meteo)
        db.set_state(cn, f"analysis_version:{user.id}", "")  # → the next ingest reprocesses everything
    job = accounts.active_for(user.id) or (accounts.start_reprocess(user, c.db_path) if user.source else None)
    return {"open_meteo": body.open_meteo, "job": job.public() if job else None}


class HeatChoice(BaseModel):
    model_config = {"extra": "forbid"}
    learn: bool = Field(strict=True)


@app.get("/api/users/{user_id}/heat")
def get_heat_setting(user_id: str, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    """How much heat costs this person per sport (k × the standard table) and whether it's learned."""
    _user_or_404(c, user_id)
    return heat_response.describe(cn, user_id)


@app.put("/api/users/{user_id}/heat", dependencies=[Depends(local_network_only)])
def set_heat_setting(user_id: str, body: HeatChoice, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    """Learn the heat response from this person's sessions (on) or use the standard factors (off). The
    verdicts of runs and rides are worked out again right away from what's stored."""
    user = _user_or_404(c, user_id)
    if not heat_response.LEARN_HEAT_RESPONSE:
        raise HTTPException(404, "Learning the heat response isn't available yet")
    n = pipeline.set_heat_learning(cn, user.id, body.learn)
    return {**heat_response.describe(cn, user.id), "recomputed": n}


@app.put("/api/users/{user_id}/profile", dependencies=[Depends(local_network_only)])
def set_profile(user_id: str, body: ProfileOverride, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    """Your own max/resting HR (null = use the data source again). Zones, load and the reference HR of
    the whole history are worked out again right away from what is already downloaded."""
    from ..config import set_overrides
    user = _user_or_404(c, user_id)
    set_overrides(user.id, {"max_hr": body.max_hr, "rest_hr": body.rest_hr})
    if body.max_hr is not None:  # you saw the source's value when you typed yours: only a newer one is offered
        profile.dismiss(cn, user, "max_hr")
    reset_config()
    db.set_state(cn, f"analysis_version:{user.id}", "")  # → the next ingest reprocesses everything
    user = load_config().user(user.id)
    # re-analyse what's downloaded; no new download, so this asks Garmin/Intervals.icu nothing
    job = accounts.active_for(user.id) or (accounts.start_reprocess(user, c.db_path) if user.source else None)
    return {"profile": profile.describe(cn, user), "job": job.public() if job else None}


class Dismiss(BaseModel):
    model_config = {"extra": "forbid"}
    field: Literal["max_hr"]


@app.post("/api/users/{user_id}/profile/dismiss", dependencies=[Depends(local_network_only)])
def dismiss_suggestion(user_id: str, body: Dismiss, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    """"Keep mine": your own value stays, and the data source's current value isn't offered again."""
    user = _user_or_404(c, user_id)
    profile.dismiss(cn, user, body.field)
    return {"profile": profile.describe(cn, user)}


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


SYNC_COOLDOWN_S = 60  # protect the Garmin account from rapid repeated syncs (rate limiting / blocking)


def _cooldown_left(cn, user_id: str) -> float:
    row = cn.execute("SELECT last_attempt FROM sync_status WHERE user_id = ?", (user_id,)).fetchone()
    if not row or not row[0]:
        return 0.0
    return SYNC_COOLDOWN_S - (datetime.now() - datetime.fromisoformat(row[0])).total_seconds()


@app.post("/api/users/{user_id}/sync", dependencies=[Depends(local_network_only)])
def sync_now(user_id: str, full: bool = False, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    user = _user_or_404(c, user_id)
    if (running := accounts.active_for(user.id)):
        return running.public()
    if (wait := _cooldown_left(cn, user.id)) > 0:
        raise HTTPException(429, f"just synced — try again in {int(wait) + 1} s")
    return accounts.start_sync(user, c.db_path, full=full).public()


MORNING_FROM_HOUR = 4    # a tap before this is still "last night"
MORNING_MAX_TRIES = 3    # per person and day, e.g. when the watch stayed on the charger


@app.post("/api/wall/morning", dependencies=[Depends(local_network_only)])
def morning_sync(c: AppConfig = Depends(cfg), cn=Depends(conn)):
    """The first tap on the wall in the morning: fetch last night (sleep, HRV, resting HR, Body Battery)
    right away instead of waiting for the hourly sync. Asks Garmin nothing itself; a quick sync starts
    only for people whose sleep from last night is still missing — at most a few times a day.
    `pending` tells the wall whether a later tap could still start one (otherwise it stops asking today)."""
    now = datetime.now()
    if now.hour < MORNING_FROM_HOUR:
        return {"started": [], "pending": True}
    today = now.date().isoformat()
    selected = db.get_state(cn, "selected_user", "")
    started, pending = [], False
    for user in sorted(c.users, key=lambda u: u.id != selected):  # the person on the wall first
        if not user.garmindb_config_dir:
            continue
        if cn.execute("SELECT 1 FROM health_days WHERE user_id = ? AND day = ? AND sleep_total_min IS NOT NULL",
                      (user.id, today)).fetchone():
            continue
        key = f"morning.{user.id}"
        day, _, tries = (db.get_state(cn, key) or "").partition(":")
        tries = int(tries) if day == today and tries.isdigit() else 0
        if tries >= MORNING_MAX_TRIES:
            continue
        pending = True  # this person's night is still missing: worth asking again on a later tap
        if accounts.active_for(user.id) or _cooldown_left(cn, user.id) > 0:
            continue
        db.set_state(cn, key, f"{today}:{tries + 1}")
        started.append(accounts.start_sync(user, c.db_path, quick=True).public())
    return {"started": started, "pending": pending}


class BaselineChoice(BaseModel):
    model_config = {"extra": "forbid"}
    excluded: bool = Field(strict=True)


@app.put("/api/sessions/{session_id}/baseline", dependencies=[Depends(local_network_only)])
def set_baseline(session_id: str, body: BaselineChoice, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    """Leave a badly recorded session out of every comparison (or bring it back). Recomputes the verdicts
    it reaches, so it answers with the session as it now is."""
    row = cn.execute("SELECT user_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if not row:
        raise HTTPException(404, "session not found")
    _user_or_404(c, row["user_id"])
    pipeline.set_excluded(cn, row["user_id"], session_id, body.excluded)
    return wall.session_detail(cn, session_id)


class ActivityCheck(BaseModel):
    model_config = {"extra": "forbid"}
    enabled: bool = Field(strict=True)


@app.get("/api/settings/activity-check")
def get_activity_check(c: AppConfig = Depends(cfg), cn=Depends(conn)):
    return activity_watch.status(cn, c)


@app.post("/api/settings/activity-check", dependencies=[Depends(local_network_only)])
def set_activity_check(body: ActivityCheck, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    """The kill switch for the auto-sync check (the separate `fitvio watch` process reads it each round)."""
    activity_watch.set_enabled(cn, body.enabled)
    if body.enabled:  # switching it back on also ends a rate-limit pause
        db.set_state(cn, activity_watch.K_BACKOFF, "")
        db.set_state(cn, activity_watch.K_ERROR, "")
    return activity_watch.status(cn, c)


class BuddyChoice(BaseModel):
    model_config = {"extra": "forbid"}
    user_id: str = Field(max_length=64)
    animal: str = Field(max_length=32)


@app.get("/api/settings/buddy")
def get_buddy(c: AppConfig = Depends(cfg), cn=Depends(conn)):
    """Each person's training-buddy animal, plus the choices."""
    return {"animals": list(buddy.ANIMALS), "food": buddy.FOOD,
            "users": {u.id: buddy.get_animal(cn, u.id) for u in c.users}}


@app.post("/api/settings/buddy", dependencies=[Depends(local_network_only)])
def set_buddy(body: BuddyChoice, c: AppConfig = Depends(cfg), cn=Depends(conn)):
    if body.user_id not in {u.id for u in c.users}:
        raise HTTPException(400, "unknown person")
    try:
        buddy.set_animal(cn, body.user_id, body.animal)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    return get_buddy(c, cn)


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

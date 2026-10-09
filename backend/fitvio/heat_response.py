"""A person's learned heat response, kept in db state and written into the sessions' features.

The adjusted values (ef_adj, speed/power_at_ref_hr_adj, decoupling_adj, heat_adj_pct) are stored with
each session, so everything that reads features sees them. When the response is relearned and moved, or
the person switches learning off or on, they are rewritten from the stored raw values and the verdicts of
that sport are worked out again; no activity file is read again.
"""
from __future__ import annotations

import json
import logging
import sqlite3

from . import db
from .analytics import heat

log = logging.getLogger(__name__)

# Learning ships switched off until a person's own numbers (fitvio heat-report) look right: then the
# factors stay at the priors (runs: the table, rides: half of it, no drift correction).
LEARN_HEAT_RESPONSE = True
SETTING = "heat_learn:{user_id}"           # "off" = the priors only
STATE = "heat_response:{user_id}:{sport}"  # the learned response in use (JSON)
MIN_MOVE = 0.1                             # relearned values closer than this keep the old ones


def enabled(conn: sqlite3.Connection, user_id: str) -> bool:
    return LEARN_HEAT_RESPONSE and db.get_state(conn, SETTING.format(user_id=user_id)) != "off"


def set_enabled(conn: sqlite3.Connection, user_id: str, on: bool) -> None:
    db.set_state(conn, SETTING.format(user_id=user_id), "on" if on else "off")


def _learned(conn: sqlite3.Connection, user_id: str, sport: str) -> dict | None:
    raw = db.get_state(conn, STATE.format(user_id=user_id, sport=sport))
    return json.loads(raw) if raw else None


def learned_yet(conn: sqlite3.Connection, user_id: str) -> bool:
    """Whether every sport has been learned once (a sync with nothing new then skips relearning)."""
    return all(_learned(conn, user_id, sport) for sport in heat.SPORTS)


def current(conn: sqlite3.Connection, user_id: str) -> dict[str, dict]:
    """{sport: {k, d, ...}} in use for this person: learned when on, else the priors."""
    out = heat.priors()
    if enabled(conn, user_id):
        for sport in heat.SPORTS:
            out[sport] = _learned(conn, user_id, sport) or out[sport]
    return out


def describe(conn: sqlite3.Connection, user_id: str) -> dict:
    """For the Me screen: per sport the factor in use and what it was learned from."""
    learn = enabled(conn, user_id)
    resp = current(conn, user_id)
    return {"available": LEARN_HEAT_RESPONSE, "learn": learn,
            "sports": {sport: {"k": r["k"], "d": r["d"], "warm": r.get("warm") or 0, "n": r.get("n") or 0,
                               "prior_k": heat.PRIOR[sport]["k"], "learned": learn and "n" in r}
                       for sport, r in resp.items()}}


def refresh(conn: sqlite3.Connection, user_id: str, sessions: list[dict]) -> list[str]:
    """Relearn each sport from the stored sessions; returns the sports whose response moved (by MIN_MOVE
    or more) and was saved. No commit."""
    if not enabled(conn, user_id):
        return []
    moved = []
    for sport in heat.SPORTS:
        fit = heat.fit_response(sessions, sport)
        old = _learned(conn, user_id, sport) or heat.PRIOR[sport]
        stats = {k: fit[k] for k in ("n", "warm", "k_hat", "k_se", "d_hat", "d_se")}
        if abs(fit["k"] - old["k"]) >= MIN_MOVE or abs(fit["d"] - old["d"]) >= MIN_MOVE:
            moved.append(sport)
            new = {"k": fit["k"], "d": fit["d"], **stats}
        else:  # too small a change to redo the history for: the factors in use stay, every session alike
            new = {"k": old["k"], "d": old["d"], **stats}
        if new != old:
            db.set_state(conn, STATE.format(user_id=user_id, sport=sport), json.dumps(new))
    return moved


def rewrite(conn: sqlite3.Connection, user_id: str, sessions: list[dict], sports: list[str]) -> list[str]:
    """Store the adjusted values of these sports' sessions with the response now in use. Returns the
    ids of the sessions whose verdicts can change. No commit."""
    resp = current(conn, user_id)
    touched = [s for s in sessions if s["sport"] in sports and s.get("features") is not None]
    heat.adjust(touched, resp)
    for s in touched:
        conn.execute("UPDATE sessions SET features = ? WHERE id = ?", (json.dumps(s["features"]), s["id"]))
    return [s["id"] for s in touched]

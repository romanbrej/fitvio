"""Leaving a badly recorded session out of comparisons (#19): verdicts, headlines and the API."""
import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from fitvio import db, improvements, pipeline, wall
from fitvio.analytics import load as load_model
from fitvio.api import main
from fitvio.config import AppConfig, WallConfig, load_config
from fitvio.demo import generate

from .test_verdicts import USER, add_run

BASE = datetime(2026, 8, 1, 7)


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "app.db")


@pytest.fixture
def runs(conn):
    """Six easy runs, a GPS glitch that makes the 7th look far too fast, then today's run."""
    good = [add_run(conn, BASE + timedelta(days=i * 2), 3.0 + 0.01 * i) for i in range(6)]
    glitch = add_run(conn, BASE + timedelta(days=12), 4.5)
    last = add_run(conn, BASE + timedelta(days=14), 3.05)
    pipeline.evaluate_all(conn, "u")
    return good, glitch, last


def verdict(conn, sid):
    return db.row_to_dict(conn.execute("SELECT * FROM verdicts WHERE session_id = ?", (sid,)).fetchone())


def test_excluded_session_leaves_later_baselines_and_comes_back(conn, runs):
    _, glitch, last = runs
    before = verdict(conn, last)
    assert glitch in before["baseline_ids"]

    assert pipeline.set_excluded(conn, "u", glitch, True) == 2  # itself and the one later run
    after = verdict(conn, last)
    assert glitch not in after["baseline_ids"] and len(after["baseline_ids"]) == len(before["baseline_ids"]) - 1
    own = verdict(conn, glitch)
    assert own["verdict"] == "excluded" and own["deltas"] == [] and own["baseline_ids"] == []
    assert own["trend"]["form_after"] is not None  # still counts for load and form

    pipeline.set_excluded(conn, "u", glitch, False)
    restored = verdict(conn, last)
    assert (restored["verdict"], restored["score"], restored["baseline_ids"]) == \
        (before["verdict"], before["score"], before["baseline_ids"])
    assert verdict(conn, glitch)["verdict"] != "excluded"


def test_excluding_twice_or_restoring_twice_is_harmless(conn, runs):
    _, glitch, _ = runs
    pipeline.set_excluded(conn, "u", glitch, True)
    pipeline.set_excluded(conn, "u", glitch, True)
    assert conn.execute("SELECT COUNT(*) FROM baseline_exclusions").fetchone()[0] == 1
    pipeline.set_excluded(conn, "u", glitch, False)
    pipeline.set_excluded(conn, "u", glitch, False)
    assert conn.execute("SELECT COUNT(*) FROM baseline_exclusions").fetchone()[0] == 0


def test_exclusion_survives_a_re_ingest_of_the_activity(conn, runs):
    _, glitch, last = runs
    pipeline.set_excluded(conn, "u", glitch, True)
    add_run(conn, BASE + timedelta(days=12), 4.5)  # store_activity replaces the sessions row
    pipeline.evaluate_all(conn, "u")
    assert verdict(conn, glitch)["verdict"] == "excluded"
    assert glitch not in verdict(conn, last)["baseline_ids"]


def test_a_stale_session_list_cannot_bring_an_exclusion_back(conn, runs):
    _, glitch, last = runs
    stale = pipeline.user_sessions(conn, "u")  # loaded by a sync before the exclusion
    pipeline.set_excluded(conn, "u", glitch, True)
    pipeline.evaluate_session(conn, "u", last, stale)
    assert glitch not in verdict(conn, last)["baseline_ids"]


def test_load_and_form_are_unchanged(conn, runs):
    _, glitch, _ = runs

    def pmc():
        return load_model.pmc(load_model.daily_loads(pipeline.user_sessions(conn, "u")), None, date(2026, 8, 20))

    before = pmc()
    pipeline.set_excluded(conn, "u", glitch, True)
    assert pmc() == before


def test_reevaluation_keeps_first_shown(conn, runs):
    _, glitch, last = runs
    conn.execute("UPDATE verdicts SET first_shown_at = '2026-08-15T08:00:00' WHERE session_id = ?", (last,))
    pipeline.set_excluded(conn, "u", glitch, True)
    assert verdict(conn, last)["first_shown_at"] == "2026-08-15T08:00:00"  # never re-triggers the wall


def test_excluded_session_never_takes_over_the_wall(conn, runs, tmp_path):
    _, glitch, last = runs
    # the later run was shown long ago, so the glitch is the one that would take over
    conn.execute("UPDATE verdicts SET first_shown_at = '2000-01-01T00:00:00' WHERE session_id = ?", (last,))
    cfg = AppConfig(users=[USER], wall=WallConfig(), db_path=tmp_path / "app.db")
    now = BASE + timedelta(days=12, hours=2)
    assert wall.fresh_verdict(conn, cfg, now=now)["session_id"] == glitch
    pipeline.set_excluded(conn, "u", glitch, True)
    assert wall.fresh_verdict(conn, cfg, now=now) is None

    card = wall.session_card(conn, glitch)
    assert card["improvements"] == []  # no gains or bests from bad data
    assert wall.session_detail(conn, glitch)["excluded_from_baseline"] is True


@pytest.fixture
def client(tmp_path):
    cfg_path = tmp_path / "users.json"
    cfg_path.write_text(json.dumps({"users": [{"id": "a", "name": "Alex", "max_hr": 190, "rest_hr": 48}]}))
    cfg = load_config(cfg_path)
    cfg.db_path = tmp_path / "app.db"
    generate(db.connect(cfg.db_path), cfg, days=60)
    main._cfg = cfg
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
    main._cfg = None


def test_api_round_trip(client):
    runs = client.get("/api/users/a/sessions?sport=running&limit=20").json()
    detail = next(d for d in (client.get(f"/api/sessions/{r['id']}").json() for r in runs) if d["baseline_sessions"])
    bad = detail["baseline_sessions"][0]["id"]
    url = f"/api/sessions/{bad}/baseline"

    assert client.put(url, json={"excluded": True}).status_code == 403  # only from the home network
    main.app.dependency_overrides[main.local_network_only] = lambda: None
    assert client.put("/api/sessions/a:nope/baseline", json={"excluded": True}).status_code == 404
    assert client.put(url, json={"excluded": "yes"}).status_code == 422

    d = client.put(url, json={"excluded": True}).json()
    assert d["excluded_from_baseline"] is True and d["verdict"]["verdict"] == "excluded"
    assert bad not in [b["id"] for b in client.get(f"/api/sessions/{detail['id']}").json()["baseline_sessions"]]
    listed = {r["id"]: r for r in client.get("/api/users/a/sessions?sport=running&limit=60").json()}
    assert listed[bad]["excluded"] and listed[bad]["verdict"] == "excluded"

    d = client.put(url, json={"excluded": False}).json()
    assert d["excluded_from_baseline"] is False and d["verdict"]["verdict"] != "excluded"


def test_sport_headline_skips_excluded_runs_but_strength_still_counts_them():
    def run(day, pace, excluded=False):
        v = 1000 / pace
        return {"sport": "running", "session_type": "easy", "indoor": 0, "start_time": f"2026-09-{day:02d}T07:00:00",
                "excluded": excluded,
                "features": {"speed_at_ref_hr": v, "speed_at_ref_hr_adj": v, "ref_hr_secs": 900, "ref_hr": 151}}

    weights, today = improvements.Weights([], 85), date(2026, 10, 2)
    runs = [run(1, 400), run(8, 400), run(15, 400), run(22, 250, excluded=True)]  # a GPS glitch, left out
    assert wall.sport_status(runs, "running", None, weights, today)["pace_s_per_km"] == pytest.approx(400)

    def gym(day, e1rm, excluded=False):
        return {"sport": "strength", "start_time": f"2026-09-{day:02d}T18:00:00", "duration_s": 3600,
                "excluded": excluded, "features": {"exercises": {"squat": {"e1rm": e1rm}}}}

    clean = [gym(10, 100), gym(17, 101), gym(24, 102)]
    st = wall.sport_status([*clean, gym(30, 300, excluded=True)], "strength", None, weights, today)
    assert st["sessions_6w"] == 4  # it was still trained
    # but the misread 300 kg doesn't make a trend
    assert st["e1rm_change_pct"] == wall.sport_status(clean, "strength", None, weights, today)["e1rm_change_pct"]

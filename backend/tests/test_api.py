import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from fitvio import db
from fitvio.api import main
from fitvio.config import load_config
from fitvio.demo import generate


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("api")
    cfg_path = tmp / "users.json"
    cfg_path.write_text(json.dumps({"users": [
        {"id": "a", "name": "Alex Runner", "max_hr": 190, "rest_hr": 48},
        {"id": "b", "name": "Bo", "max_hr": 185, "rest_hr": 55},
    ]}))
    cfg = load_config(cfg_path)
    cfg.db_path = tmp / "app.db"
    generate(db.connect(cfg.db_path), cfg, days=60)
    main._cfg = cfg
    yield TestClient(main.app)
    main._cfg = None


def test_config(client):
    r = client.get("/api/config").json()
    assert [u["initials"] for u in r["users"]] == ["AR", "B"]


def test_wall_verdict_survives_avatar_tap_until_dismissed(client):
    w = client.get("/api/wall").json()
    assert w["mode"] == "verdict"
    assert w["user_id"] == "a"  # demo: user a's run finished most recently
    assert w["session"]["verdict"]["headline"]
    sid = w["session"]["id"]
    # another person tapping their avatar must not end the takeover (the screen only pauses it)
    client.post("/api/wall/select", json={"user_id": "b"})
    w = client.get("/api/wall").json()
    assert w["mode"] == "verdict" and w["session"]["id"] == sid
    # "Overview" ends it for good
    client.post("/api/wall/dismiss", json={"session_id": sid})
    w = client.get("/api/wall").json()
    assert w["mode"] == "ambient" or w["session"]["id"] != sid
    if w["mode"] == "ambient":
        assert w["user_id"] == "b"


def test_verdict_shows_what_improved_and_wall_shows_fitness_curve(client):
    sessions = client.get("/api/users/a/sessions?limit=1").json()
    d = client.get(f"/api/sessions/{sessions[0]['id']}").json()
    assert "fitness" in [i["kind"] for i in d["improvements"]]
    a = client.get("/api/users/a/ambient").json()
    assert len(a["pmc"]) > 42 and "fitness_change_6w" in a
    # today's change = all of today's training: last pmc row minus the one before
    today, prev = a["pmc"][-1], a["pmc"][-2]
    for k in ("fitness", "fatigue", "form"):
        assert a["today_change"][k] == pytest.approx(today[k] - prev[k], abs=0.11)
    assert a["form"]["form"] == pytest.approx(a["form"]["fitness"] - a["form"]["fatigue"], abs=0.11)
    lw = a["last_workout"]  # the wall's first card on the day of a workout: what it improved
    if sessions[0]["start_time"][:10] == datetime.now().date().isoformat():
        assert lw["id"] == sessions[0]["id"] and lw["improvements"] and lw["verdict"]
    else:
        assert lw is None


def test_last_workout_card_resets_at_midnight():
    from fitvio.wall import _is_today
    assert _is_today("2026-09-29T19:30:00", datetime(2026, 9, 29, 23, 59))
    assert not _is_today("2026-09-29T19:30:00", datetime(2026, 9, 30, 0, 0))


def test_session_detail_and_lists(client):
    sessions = client.get("/api/users/a/sessions?limit=5").json()
    assert len(sessions) == 5
    d = client.get(f"/api/sessions/{sessions[0]['id']}").json()
    assert d["streams"]["t"]
    assert "baseline_sessions" in d
    assert client.get("/api/users/a/pmc?days=30").json()[-1]["fitness"] > 0
    assert client.get("/api/users/a/health?days=14").json()
    assert "agreement_pct" in client.get("/api/users/a/validation").json()


def test_session_history_pages_and_filters(client):
    everything = client.get("/api/users/a/sessions?limit=500").json()
    first = client.get("/api/users/a/sessions?limit=10").json()
    second = client.get("/api/users/a/sessions?limit=10&offset=10").json()
    # pages follow each other without gaps or overlap, newest first
    assert [s["id"] for s in first + second] == [s["id"] for s in everything[:20]]
    assert [s["start_time"] for s in everything] == sorted((s["start_time"] for s in everything), reverse=True)

    types = client.get("/api/users/a/session-types?sport=running").json()
    runs = client.get("/api/users/a/sessions?sport=running&limit=500").json()
    assert sum(t["count"] for t in types) == len(runs)
    t = types[0]["type"]
    only = client.get(f"/api/users/a/sessions?sport=running&type={t}&limit=500").json()
    assert len(only) == types[0]["count"] and {s["session_type"] for s in only} == {t}
    assert client.get("/api/users/nope/session-types").status_code == 404


def test_unknown_user_404(client):
    assert client.get("/api/users/nope/ambient").status_code == 404


def test_sport_status_running_pace_and_cycling_wkg():
    from datetime import date as d
    from fitvio import improvements, wall
    today = d(2026, 10, 2)

    def run(day, pace, typ="easy", secs=900, heat_pct=0.0, indoor=0):
        v = 1000 / pace
        return {"sport": "running", "session_type": typ, "indoor": indoor, "start_time": f"2026-09-{day:02d}T07:00:00",
                "features": {"speed_at_ref_hr": v, "speed_at_ref_hr_adj": v * (1 + heat_pct / 100),
                             "ref_hr_secs": secs, "ref_hr": 151}}

    # every outdoor run counts for its steady time at 151 bpm, tempo and intervals included
    runs = [run(1, 420), run(8, 415, "long", secs=3000), run(15, 410, "tempo", secs=200), run(22, 405),
            run(29, 400, "intervals", secs=120), run(30, 300, indoor=1),     # treadmill: out
            {"sport": "running", "session_type": "easy", "indoor": 0, "start_time": "2026-09-25T07:00:00",
             "features": {"speed_at_ref_hr": None, "ref_hr_secs": None, "ref_hr": 151}}]  # never at 151
    st = wall.sport_status(runs, "running", None, improvements.Weights([], 85), today)
    assert (st["runs"], st["runs_total"]) == (5, 6) and st["ref_hr"] == 151
    # the newest runs, weighted by seconds (long run capped at 20 min) and faded by position: newest 6/6 … 2/6
    assert st["headline_runs"] == 5
    w = [(400, 120, 6), (405, 900, 5), (410, 200, 4), (415, 1200, 3), (420, 900, 2)]
    assert st["pace_s_per_km"] == pytest.approx(sum(p * s * k for p, s, k in w) / sum(s * k for _, s, k in w), abs=0.1)
    assert st["change_s_per_km"] > 15 and st["change_s_per_km_raw"] == st["change_s_per_km"]

    # a long run counts at most 20 min: it can't outvote the others
    st = wall.sport_status([run(20, 400, secs=600), run(22, 400, secs=600), run(24, 440, "long", secs=7200)],
                           "running", None, improvements.Weights([], 85), today)
    assert st["pace_s_per_km"] == pytest.approx(                                   # 2 h counted as 20 min
        (440 * 1200 * 6 + 400 * 600 * 5 + 400 * 600 * 4) / (1200 * 6 + 600 * 5 + 600 * 4), abs=0.1)

    # cooler weeks: faster as run, but the heat-adjusted trend stays steady
    hot = [run(1 + 7 * i, 420 - 3 * i, heat_pct=3.0 - 0.75 * i) for i in range(5)]
    st = wall.sport_status(hot, "running", None, improvements.Weights([], 85), today)
    assert st["change_s_per_km_raw"] > 10 and abs(st["change_s_per_km"]) < 4

    ride = {"sport": "cycling", "session_type": "easy", "has_power": 1, "start_time": "2026-09-20T07:00:00",
            "features": {"ef": 1.14, "power_at_ref_hr": 170.0, "ref_hr": 151}}
    st = wall.sport_status([ride], "cycling", 230, improvements.Weights([], 85), today)
    assert (st["w_per_beat"], st["ftp_wkg"], st["hr_wkg"]) == (1.14, 2.71, 2.0)
    # no rides with power: FTP W/kg still shows
    st = wall.sport_status([], "cycling", 230, improvements.Weights([], 85), today)
    assert st["w_per_beat"] is None and st["ftp_wkg"] == 2.71



def test_running_headline_moves_only_when_a_run_comes_in():
    """Waking up to a different pace with no new run was confusing: the numbers are counted from the
    newest run, so days passing change nothing, and a new run replaces exactly the oldest one."""
    from datetime import date as d, timedelta
    from fitvio import improvements, wall
    w = improvements.Weights([], 85)

    def run(day, pace, secs=900):
        v = 1000 / pace
        return {"sport": "running", "session_type": "easy", "indoor": 0,
                "start_time": (d(2026, 9, 1) + timedelta(days=day)).isoformat() + "T07:00:00",
                "features": {"speed_at_ref_hr": v, "speed_at_ref_hr_adj": v, "ref_hr_secs": secs, "ref_hr": 151}}

    runs = [run(3 * i, 420 - 2 * i) for i in range(8)]       # one every 3 days, getting faster
    keys = ("pace_s_per_km", "change_s_per_km", "points", "headline_runs")
    base = wall.sport_status(runs, "running", None, w, d(2026, 9, 22))
    for later in (1, 10, 30, 60):
        st = wall.sport_status(runs, "running", None, w, d(2026, 9, 22) + timedelta(days=later))
        assert {k: st[k] for k in keys} == {k: base[k] for k in keys}

    # 6 runs make the headline; a new one pushes out only the oldest of them
    assert base["headline_runs"] == 6
    newer = wall.sport_status(runs + [run(24, 404)], "running", None, w, d(2026, 9, 25))
    assert newer["headline_runs"] == 6
    without_oldest = wall.sport_status(runs[3:] + [run(24, 404)], "running", None, w, d(2026, 9, 25))
    assert newer["pace_s_per_km"] == without_oldest["pace_s_per_km"]

    # too little time at the reference HR in the newest 6 → older runs are added until 10 min
    short = [run(i, 400, secs=60) for i in range(12)]
    st = wall.sport_status(short, "running", None, w, d(2026, 9, 20))
    assert st["headline_runs"] == 10

def test_sport_status_strength_consistency_and_e1rm():
    from datetime import date as d, timedelta
    from fitvio import improvements, wall
    today = d(2026, 10, 2)

    def gym(days_ago, e1rm=None):
        ex = {"squat": {"e1rm": e1rm}} if e1rm else {"10.30": {"e1rm": None, "sets": 3}}
        return {"sport": "strength", "start_time": f"{(today - timedelta(days=days_ago)).isoformat()}T18:00:00",
                "duration_s": 1200, "features": {"exercises": ex}}

    # circuits without weights: only how often — 4 in the last 6 weeks, 1 in the 6 before
    st = wall.sport_status([gym(3), gym(10), gym(20), gym(30), gym(60)], "strength", None,
                           improvements.Weights([], 85), today)
    assert (st["sessions_6w"], st["sessions_prev_6w"], st["minutes_6w"]) == (4, 1, 80)
    assert st["e1rm_change_pct"] is None
    assert len(st["points"]) == 12 and sum(p["value"] for p in st["points"]) == 5

    # squats logged with weight, going up 100 → 110 kg in 6 weeks
    st = wall.sport_status([gym(35, 100), gym(21, 105), gym(7, 110)], "strength", None,
                           improvements.Weights([], 85), today)
    assert st["e1rm_change_pct"] > 5

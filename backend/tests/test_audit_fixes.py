"""Regressions for the security audit of 2026-10: bad provider data, size limits, the home-network gate."""
import gzip
import json
import struct
import threading
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from fitvio import config, db, pipeline
from fitvio.activity import ParsedActivity
from fitvio.api import main
from fitvio.config import load_config
from fitvio.demo import generate
from fitvio.ingest import intervals_reader as icu
from fitvio.ingest.fit_parser import parse_fit
from fitvio.sync import garmin_coach, garmin_extras

INF = float("inf")


# --- non-finite numbers (a crafted FIT file used to take the shared wall down with HTTP 500) ----

def _crc16(data: bytes, crc: int = 0) -> int:
    t = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
         0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]
    for b in data:
        x = t[crc & 0xF]; crc = (crc >> 4) & 0x0FFF; crc ^= x ^ t[b & 0xF]
        x = t[crc & 0xF]; crc = (crc >> 4) & 0x0FFF; crc ^= x ^ t[(b >> 4) & 0xF]
    return crc


def fit_with_infinite_speed(start: datetime, n: int = 1800) -> bytes:
    """Records whose enhanced_speed field is declared float32 by the file; one of them holds +inf."""
    ts0 = int((start - datetime(1989, 12, 31)).total_seconds())
    fields = [(253, 4, 0x86), (3, 1, 0x02), (5, 4, 0x86), (73, 4, 0x88)]
    body = bytes([0x40, 0, 0]) + struct.pack("<HB", 20, len(fields)) + b"".join(bytes(f) for f in fields)
    for i in range(n):
        body += b"\x00" + struct.pack("<IBIf", ts0 + i, 150, int(i * 300), INF if i == n // 2 else 3.0)
    header = struct.pack("<BBHI4s", 14, 0x20, 2100, len(body), b".FIT")
    data = header + struct.pack("<H", _crc16(header)) + body
    return data + struct.pack("<H", _crc16(data))


@pytest.fixture
def wall(tmp_path):
    path = tmp_path / "users.json"
    path.write_text(json.dumps({"users": [{"id": "a", "name": "A", "max_hr": 190, "rest_hr": 48},
                                          {"id": "b", "name": "B", "max_hr": 185, "rest_hr": 55}]}))
    cfg = load_config(path)
    cfg.db_path = tmp_path / "app.db"
    conn = db.connect(cfg.db_path)
    generate(conn, cfg, days=60)
    conn.execute("UPDATE verdicts SET first_shown_at = '2000-01-01T00:00:00'")
    conn.commit()
    main._cfg = cfg
    yield cfg, conn, TestClient(main.app)
    main._cfg = None


def test_infinite_fit_value_is_dropped_and_the_wall_still_renders(wall, tmp_path):
    cfg, conn, client = wall
    start = datetime.now().replace(microsecond=0) - timedelta(hours=1)
    (tmp_path / "bad.fit").write_bytes(fit_with_infinite_speed(start))
    parsed = parse_fit(tmp_path / "bad.fit")
    assert [r.speed for r in parsed["records"]].count(None) == 1  # the inf sample, nothing else
    act = ParsedActivity(activity_id="999", start_time=start, sport="running", raw_sport="running", name="Run",
                         duration_s=1800.0, distance_m=5400.0, avg_hr=150.0, max_hr=160.0,
                         records=parsed["records"], laps=parsed["laps"], lengths=parsed["lengths"],
                         sets=parsed["sets"], exercise_labels=parsed["exercise_labels"])
    sid = pipeline.store_activity(conn, cfg.user("a"), act)
    pipeline.evaluate_session(conn, "a", sid)
    conn.commit()
    assert "Infinity" not in conn.execute("SELECT features FROM sessions WHERE id = ?", (sid,)).fetchone()[0]
    for path in ("/api/wall", "/api/users/a/sessions", f"/api/sessions/{sid}", "/api/users/a/ambient"):
        assert client.get(path).status_code == 200, path


def test_stored_non_finite_values_become_null_not_500(wall):
    """Whatever the source: upsert stores no inf/NaN, and the API turns any left over into null."""
    cfg, conn, client = wall
    day = datetime.now().date().isoformat()
    db.upsert(conn, "health_days", {"user_id": "a", "day": day, "steps": INF, "weight_kg": float("nan")})
    conn.commit()
    row = conn.execute("SELECT steps, weight_kg FROM health_days WHERE user_id = 'a' AND day = ?", (day,)).fetchone()
    assert tuple(row) == (None, None)
    assert main.SafeJSONResponse({"x": [1.5, INF, {"y": float("nan")}]}).body == b'{"x":[1.5,null,{"y":null}]}'
    assert client.get("/api/users/a/health").status_code == 200


def test_intervals_numbers_must_be_finite():
    assert icu._num(json.loads("1e999")) is None
    assert icu._num(10**400) is None and icu._num(True) is None and icu._num("12") is None
    assert icu._num(61) == 61.0


def test_intervals_gzip_and_size_limits(monkeypatch):
    monkeypatch.setattr(icu, "MAX_BYTES", 1000)
    assert icu._gunzip(gzip.compress(b"x" * 1000)) == b"x" * 1000
    with pytest.raises(icu.IntervalsError):
        icu._gunzip(gzip.compress(b"x" * 1001))  # would unpack beyond the limit
    with pytest.raises(icu.IntervalsError):
        icu._gunzip(b"\x1f\x8b" + b"broken")


# --- Garmin workouts: nested repeats used to multiply without limit ------------------------------

def _repeat(n, inner):
    return {"type": "RepeatGroupDTO", "stepOrder": 1, "numberOfIterations": n, "workoutSteps": inner}


def test_workout_repeats_are_bounded():
    step = {"type": "ExecutableStepDTO", "stepOrder": 1, "stepType": {"stepTypeKey": "interval"},
            "endCondition": {"conditionTypeKey": "time"}, "endConditionValue": 60}
    six = garmin_coach.parse_workout({"workoutSegments": [{"workoutSteps": [_repeat(6, [step])]}]})
    assert len(six["steps"]) == 6  # ordinary workouts are unchanged
    bomb = {"workoutSegments": [{"workoutSteps": [_repeat(99, [_repeat(99, [_repeat(99, [step])])])]}] * 3}
    assert len(garmin_coach.parse_workout(bomb)["steps"]) == garmin_coach.MAX_STEPS
    assert len(garmin_coach._steps([_repeat(10**9, [step])])) == garmin_coach.MAX_REPEATS
    assert len(garmin_coach._steps([_repeat(float("inf"), [step])])) == garmin_coach.MAX_REPEATS


def test_acclimation_day_must_be_a_date(tmp_path):
    calls = []
    garmin_extras.fetch_extras(lambda p: calls.append(p) or {}, tmp_path, "123", "../../x/y")
    assert not any("acclimation" in c or "x/y" in c for c in calls)
    assert garmin_extras.missing(tmp_path, "123", "../../x/y")[1] is False
    assert garmin_extras.missing(tmp_path, "123", "2026-10-07")[1] is True


# --- home-network gate ------------------------------------------------------------------------

class _Req:
    def __init__(self, host):
        self.client = type("C", (), {"host": host})()


@pytest.mark.parametrize("host", ["192.168.178.20", "10.0.0.5", "172.17.0.1", "127.0.0.1", "::1",
                                  "fd00::5", "fe80::1", "::ffff:192.168.1.2"])
def test_home_network_addresses_pass(host):
    main.local_network_only(_Req(host))


@pytest.mark.parametrize("host", ["8.8.8.8", "2a00:1450:4001::7", "2001:0:53aa:64c::1",  # public, Teredo
                                  "2002:c0a8:101::1", "198.18.0.1", "192.0.0.8", "0.0.0.0",  # 6to4, special
                                  "100.64.0.1", "::ffff:8.8.8.8", "testclient"])
def test_tunnels_and_special_ranges_are_refused(host):
    with pytest.raises(HTTPException):
        main.local_network_only(_Req(host))


# --- users.json ------------------------------------------------------------------------------

def test_users_json_survives_a_failed_write_and_concurrent_writers(tmp_path, monkeypatch):
    path = tmp_path / "users.json"
    monkeypatch.setenv("FITVIO_CONFIG", str(path))
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    config.add_user("alice", intervals_dir="data/intervals/alice")
    assert path.stat().st_mode & 0o777 == 0o600

    def broken_dumps(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(config.json, "dumps", broken_dumps)
    with pytest.raises(OSError):
        config.set_overrides("alice", {"max_hr": 190})
    monkeypatch.undo()
    monkeypatch.setenv("FITVIO_CONFIG", str(path))
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    assert [u.id for u in load_config(path).users] == ["alice"]  # the old file is intact
    assert not list(tmp_path.glob(".users-*"))                   # and no temp file is left

    threads = [threading.Thread(target=config.add_user, args=(f"p{i}",), kwargs={"intervals_dir": f"data/intervals/p{i}"})
               for i in range(8)]
    threads += [threading.Thread(target=config.set_overrides, args=("alice", {"max_hr": 180 + i})) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert {u.id for u in load_config(path).users} == {"alice", *(f"p{i}" for i in range(8))}

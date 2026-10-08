"""Strength sets: exercise names from the FIT profile, whether the file holds numbers or names (issue #8)."""
import struct
from datetime import datetime, timedelta

from fitvio import db, pipeline
from fitvio.activity import ParsedActivity
from fitvio.config import UserConfig
from fitvio.ingest.fit_parser import exercise_key, parse_fit

from .test_audit_fixes import _crc16

USER = UserConfig(id="u", name="Test User", max_hr=190, rest_hr=50)
PLANK, SQUAT = 19, 28  # FIT exercise_category codes


def test_numbers_and_names_give_the_same_key():
    assert exercise_key((PLANK,), (43,)) == exercise_key("plank", 43) == ("plank.43", "Plank")
    assert exercise_key((SQUAT, SQUAT), (4, 4)) == ("squat.4", "Balancing squat")
    assert exercise_key(10, 34) == ("hip_raise.34", "Single leg hip raise with foot on bosu ball")


def test_unknown_category_reads_exercise():
    assert exercise_key((65534,), (0,)) == ("unknown", "Exercise")
    assert exercise_key(None, None) == ("unknown", "Exercise")
    assert exercise_key("unknown", 3) == ("unknown", "Exercise")
    assert exercise_key((9999,), None) == ("unknown", "Exercise")  # newer than our FIT profile


def test_unknown_or_missing_subtype_falls_back_to_the_category():
    assert exercise_key((PLANK,), (60000,)) == ("plank.60000", "Plank")
    assert exercise_key((PLANK,), None) == ("plank", "Plank")
    assert exercise_key((), ()) == ("unknown", "Exercise")


def strength_fit(start: datetime, sets: list[tuple]) -> bytes:
    """`set` messages as Garmin writes them: category and subtype as uint16 arrays.
    Each set is (category, subtype, reps, weight_kg or None, duration_s, active)."""
    ts0 = int((start - datetime(1989, 12, 31)).total_seconds())
    # (field number, size in bytes, base type): timestamp, duration, repetitions, weight, set_type, category, subtype
    fields = [(254, 4, 0x86), (0, 4, 0x86), (3, 2, 0x84), (4, 2, 0x84), (5, 1, 0x02), (7, 4, 0x84), (8, 4, 0x84)]
    body = bytes([0x40, 0, 0]) + struct.pack("<HB", 225, len(fields)) + b"".join(bytes(f) for f in fields)
    for i, (cat, sub, reps, kg, secs, active) in enumerate(sets):
        body += b"\x00" + struct.pack("<IIHHBHHHH", ts0 + i * 90, int(secs * 1000), reps, 0xFFFF if kg is None else int(kg * 16),
                                      1 if active else 0, cat, cat, sub, sub)
    header = struct.pack("<BBHI4s", 14, 0x20, 2100, len(body), b".FIT")
    data = header + struct.pack("<H", _crc16(header)) + body
    return data + struct.pack("<H", _crc16(data))


def test_fit_with_numeric_categories_gives_names_and_set_times(tmp_path):
    path = tmp_path / "gym.fit"
    path.write_bytes(strength_fit(datetime(2026, 9, 10, 18), [
        (PLANK, 43, 0, None, 45, True), (PLANK, 43, 0, None, 30, False),  # the rest is dropped
        (SQUAT, 4, 10, 40, 50, True)]))
    parsed = parse_fit(path)
    assert parsed["exercise_labels"] == {"plank.43": "Plank", "squat.4": "Balancing squat"}
    assert [(s.exercise, s.reps, s.weight_kg, s.duration_s) for s in parsed["sets"]] == [
        ("plank.43", 0, None, 45.0), ("squat.4", 10, 40.0, 50.0)]


def test_timed_sets_are_stored_and_strength_still_compares_across_sessions(tmp_path):
    conn = db.connect(tmp_path / "app.db")
    base = datetime(2026, 8, 1, 18)
    for i, kg in enumerate([80, 80, 82.5, 90]):
        path = tmp_path / f"g{i}.fit"
        path.write_bytes(strength_fit(base + timedelta(days=i * 3), [(PLANK, 43, 0, None, 45, True)]
                                      + [(SQUAT, 4, 5, kg, 40, True)] * 3))
        parsed = parse_fit(path)
        sid = pipeline.store_activity(conn, USER, ParsedActivity(
            activity_id=f"g{i}", start_time=base + timedelta(days=i * 3), sport="strength", duration_s=3600,
            records=[], sets=parsed["sets"], exercise_labels=parsed["exercise_labels"]))
    v = pipeline.evaluate_session(conn, "u", sid)
    assert v["verdict"] == "better"  # squat.4 matched in all four sessions
    sets = conn.execute("SELECT exercise, reps, duration_s FROM exercise_sets WHERE session_id = ? ORDER BY set_index",
                        (sid,)).fetchall()
    assert tuple(sets[0]) == ("plank.43", 0, 45.0)
    feats = db.row_to_dict(conn.execute("SELECT features FROM sessions WHERE id = ?", (sid,)).fetchone())["features"]
    assert feats["exercises"]["plank.43"]["e1rm"] is None  # a timed set has no 1-rep max
    assert feats["exercises"]["squat.4"]["label"] == "Balancing squat"


def test_an_existing_database_gets_the_set_duration_column(tmp_path):
    import sqlite3
    old = sqlite3.connect(tmp_path / "app.db")
    old.execute("CREATE TABLE exercise_sets (session_id TEXT NOT NULL, set_index INTEGER NOT NULL, exercise TEXT NOT NULL,"
                " reps INTEGER, weight_kg REAL, PRIMARY KEY (session_id, set_index))")
    old.execute("PRAGMA user_version = 1")
    old.commit(); old.close()
    conn = db.connect(tmp_path / "app.db")
    assert "duration_s" in {r[1] for r in conn.execute("PRAGMA table_info(exercise_sets)")}

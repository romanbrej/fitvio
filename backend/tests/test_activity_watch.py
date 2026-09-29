"""Auto-sync on new activity: the webhook-like check (sync/activity_watch.py)."""
from datetime import datetime

import pytest

from healthdash import db
from healthdash.config import AppConfig, UserConfig
from healthdash.sync import activity_watch as w
from healthdash.sync.garmindb_runner import SyncBusy

NOON = datetime(2026, 9, 29, 12, 0)


@pytest.fixture
def env(tmp_path):
    conn = db.connect(tmp_path / "app.db")
    users = [UserConfig(id=u, garmindb_config_dir=str(tmp_path / "garmindb" / u / "config")) for u in ("roman", "sam")]
    return conn, AppConfig(users=users, db_path=tmp_path / "app.db")


def add_session(conn, uid, aid):
    conn.execute("INSERT INTO sessions (id, user_id, activity_id, sport, start_time) VALUES (?, ?, ?, 'running', ?)",
                 (f"{uid}:{aid}", uid, aid, "2026-09-29T11:00:00"))
    conn.commit()


class Garmin:
    """Fake Garmin: newest id per person, and a sync that imports it (or not)."""

    def __init__(self, conn, newest, lands=True):
        self.conn, self.newest_ids, self.lands, self.synced = conn, newest, lands, []

    def newest(self, user):
        v = self.newest_ids[user.id]
        if isinstance(v, Exception):
            raise v
        return v

    def sync(self, conn, user, full=False):
        self.synced.append(user.id)
        if self.lands:
            add_session(conn, user.id, self.newest_ids[user.id])
        return True, {}


def run(env, g, now=NOON):
    conn, cfg = env
    return w.check_once(conn, cfg, now, newest=g.newest, sync=g.sync)


def test_new_activity_triggers_exactly_one_sync(env):
    conn, _ = env
    add_session(conn, "sam", "100")
    g = Garmin(conn, {"roman": "200", "sam": "100"})
    assert run(env, g) == {"roman": "synced", "sam": "none"}
    assert g.synced == ["roman"]
    assert run(env, g) == {"roman": "none", "sam": "none"}  # already imported: no second sync
    assert g.synced == ["roman"]


def test_multisport_legs_count_as_known(env):
    conn, _ = env
    add_session(conn, "roman", "300_1")
    add_session(conn, "sam", "30012")  # a different activity that merely starts with the same digits
    g = Garmin(conn, {"roman": "300", "sam": "300"})
    assert run(env, g) == {"roman": "none", "sam": "synced"}


def test_nothing_at_night_or_when_switched_off(env):
    conn, _ = env
    g = Garmin(conn, {"roman": "1", "sam": "2"})
    assert set(run(env, g, datetime(2026, 9, 30, 4, 59)).values()) == {"night"}
    assert run(env, g, datetime(2026, 9, 30, 5, 0))["roman"] == "synced"  # 05:00 is on
    w.set_enabled(conn, False)
    assert set(run(env, g).values()) == {"disabled"}
    assert g.synced == ["roman", "sam"]


def test_expired_login_pauses_only_that_person_and_never_logs_in(env):
    conn, _ = env
    g = Garmin(conn, {"roman": w.AuthExpired("Garmin rejected the cached login"), "sam": "5"})
    assert run(env, g) == {"roman": "auth", "sam": "synced"}
    assert w.paused_for_login(conn, "roman") and not w.paused_for_login(conn, "sam")
    g.newest_ids["roman"] = "9"  # even if Garmin would answer again: stay paused until a real sync works
    assert run(env, g)["roman"] == "paused"
    db.upsert(conn, "sync_status", {"user_id": "roman", "last_attempt": "2026-09-29T12:30:00",
                                    "last_success": "2026-09-29T12:30:00", "last_error": None})
    conn.commit()
    assert not w.paused_for_login(conn, "roman")  # a successful sync (e.g. "Sync now") ends the pause
    assert run(env, g, datetime(2026, 9, 29, 12, 32))["roman"] == "synced"


def test_rate_limit_pauses_everyone_for_six_hours(env):
    conn, _ = env
    g = Garmin(conn, {"roman": w.RateLimited("429"), "sam": "5"})
    assert run(env, g) == {"roman": "rate_limited"}  # stops right away, sam isn't asked either
    assert set(run(env, g, datetime(2026, 9, 29, 17, 59)).values()) == {"backoff"}
    g.newest_ids["roman"] = "4"
    assert run(env, g, datetime(2026, 9, 29, 18, 1)) == {"roman": "synced", "sam": "synced"}


def test_activity_that_never_lands_is_synced_at_most_three_times(env):
    conn, _ = env
    g = Garmin(conn, {"roman": "77", "sam": None}, lands=False)
    outcomes = [run(env, g)["roman"] for _ in range(5)]
    assert outcomes == ["retry", "retry", "retry", "none", "none"]
    assert g.synced.count("roman") == 3


def test_busy_and_network_errors_are_retried_quietly(env):
    conn, _ = env

    def busy_sync(conn, user, full=False):
        raise SyncBusy("manual sync running")

    g = Garmin(conn, {"roman": "8", "sam": w.CheckFailed("timeout")})
    assert w.check_once(conn, env[1], NOON, newest=g.newest, sync=busy_sync) == {"roman": "busy", "sam": "failed"}
    assert run(env, g)["roman"] == "synced"  # next round picks it up


def test_check_never_touches_the_password(env, monkeypatch):
    """No cached tokens → paused, without ever constructing a password login."""
    import healthdash.sync.garmindb_runner as runner
    monkeypatch.setattr(runner, "garmin_client", lambda *a, **k: pytest.fail("password login attempted"))
    conn, cfg = env
    with pytest.raises(w.AuthExpired):
        w.newest_activity_id(cfg.users[0])


def test_hourly_full_sync_covers_everyone_and_survives_errors(env):
    conn, cfg = env
    seen = []

    def sync(conn, user, full=False):
        seen.append(user.id)
        if user.id == "roman":
            raise SyncBusy("busy")

    w.full_sync_all(conn, cfg, sync=sync)
    assert seen == ["roman", "sam"]

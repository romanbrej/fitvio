"""`fitvio mqtt`: shares the people who opted in with Home Assistant through an MQTT broker.

Runs as its own process (the `mqtt` service in docker-compose.yml), so a slow or missing broker can
never hold up a sync: it only reads the database, every few seconds, and tells Home Assistant what
changed. While the broker is down it does nothing; paho reconnects on its own, and once it's back
everything is published again (events of workouts that came in meanwhile too, if still fresh).
"Sync now" from Home Assistant goes to the dashboard's own sync endpoint, with its cooldown.
"""
from __future__ import annotations

import json
import logging
import queue
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

from . import db, wall
from . import home_assistant as ha
from .config import AppConfig, MqttConfig, env, load_config
from .sync.activity_watch import paused_for_login

log = logging.getLogger(__name__)

TICK_S = 5              # how often the database is checked for changes
REFRESH_S = 15 * 60     # sensors are republished at least this often (today's workout changes at midnight)
NEW_WORKOUTS_MAX = 5    # events per person and round, oldest first


def _announced_key(user_id: str) -> str:
    return f"ha.{user_id}.announced"


class Bridge:
    """What to publish, given the database and a connected client. `client` needs publish(topic,
    payload, retain) and subscribe(topic); `post_sync(user_id)` starts a sync (see api_sync)."""

    def __init__(self, client, post_sync):
        self.client = client
        self.post_sync = post_sync
        self.requests: queue.Queue[str] = queue.Queue()  # sync-now presses, filled by the MQTT thread
        self.lock = threading.Lock()
        self.seen_devices: set[str] = set()              # Fitvio discovery topics on the broker (MQTT thread too)
        self.sync_seen: dict[str, tuple] = {}            # user id → (last failed attempt, login expired)
        self.reset_published()

    def reset_published(self) -> None:
        """A new broker connection: send every device and its sensors again."""
        self.published: dict[str, tuple] = {}            # user id → fingerprint of the last state sent
        self.published_at: dict[str, float] = {}

    def on_message(self, m: MqttConfig, topic: str, payload: bytes) -> None:
        if topic.startswith(f"{m.discovery_prefix}/device/fitvio_"):
            if payload:  # a device we (or an earlier run) announced; dropped in tick() if no longer shared
                with self.lock:
                    self.seen_devices.add(topic)
            return
        prefix, _, rest = topic.partition("/")
        if prefix == m.topic_prefix and rest.endswith("/sync") and payload == b"PRESS":
            self.requests.put(rest.removesuffix("/sync"))

    def subscriptions(self, m: MqttConfig) -> list[str]:
        return [f"{m.topic_prefix}/+/sync", f"{m.discovery_prefix}/device/+/config"]

    def tick(self, conn: sqlite3.Connection, cfg: AppConfig, now: datetime | None = None) -> None:
        m = cfg.mqtt
        now = now or datetime.now()
        shared = [u for u in cfg.users if ha.is_shared(conn, u.id)]
        topics = {ha.discovery_topic(m, u.id): u for u in shared}
        with self.lock:
            gone = sorted(self.seen_devices - topics.keys())
            self.seen_devices -= set(gone)
        for topic in gone:  # opted out or removed: their device disappears from Home Assistant
            slug = topic.rsplit("/", 2)[-2].removeprefix("fitvio_")
            self.client.publish(topic, "", retain=True)
            self.client.publish(f"{m.topic_prefix}/{slug}/state", "", retain=True)
            for uid in [uid for uid in self.published if ha.slug(uid) == slug]:
                del self.published[uid]
            log.info("home assistant: removed %s", slug)
        for user in shared:
            if user.id not in self.published:
                self.client.publish(ha.discovery_topic(m, user.id), json.dumps(ha.discovery(m, user)), retain=True)
                with self.lock:
                    self.seen_devices.add(ha.discovery_topic(m, user.id))
            self.publish_state(conn, cfg, user.id)
            self.new_workouts(conn, cfg, user.id, now)
            self.sync_events(conn, cfg, user.id)
        while not self.requests.empty():
            slug = self.requests.get_nowait()
            user = next((u for u in shared if ha.slug(u.id) == slug), None)
            if user:  # only for people who share; anybody else's button doesn't exist
                self.post_sync(user.id)

    def publish_state(self, conn: sqlite3.Connection, cfg: AppConfig, user_id: str) -> None:
        r = conn.execute("SELECT last_attempt, last_success, last_error FROM sync_status WHERE user_id = ?",
                         (user_id,)).fetchone()
        v = conn.execute("SELECT max(created_at) FROM verdicts WHERE user_id = ?", (user_id,)).fetchone()
        fingerprint = (tuple(r) if r else None, v[0], paused_for_login(conn, user_id), date.today().isoformat())
        fresh = time.monotonic() - self.published_at.get(user_id, -REFRESH_S) < REFRESH_S
        if self.published.get(user_id) == fingerprint and fresh:
            return
        payload = ha.state(wall.ambient(conn, cfg, user_id))
        self.client.publish(ha.state_topic(cfg.mqtt, user_id), json.dumps(db.finite(payload)), retain=True)
        self.published[user_id], self.published_at[user_id] = fingerprint, time.monotonic()

    def new_workouts(self, conn: sqlite3.Connection, cfg: AppConfig, user_id: str, now: datetime) -> None:
        """An event per workout with a verdict that's newer than the last one announced. The first time
        (just opted in) nothing is announced, and old activities (a backfill) never are."""
        last = db.get_state(conn, _announced_key(user_id))
        rows = conn.execute(
            """SELECT s.id, s.name, s.sport, s.start_time, v.verdict, v.headline FROM sessions s
               JOIN verdicts v ON v.session_id = s.id WHERE s.user_id = ? AND v.verdict != 'excluded'
               AND s.start_time > ? ORDER BY s.start_time DESC LIMIT ?""",
            (user_id, last or "", 1 if last is None else NEW_WORKOUTS_MAX)).fetchall()
        if not rows:
            return
        oldest_fresh = now - timedelta(hours=cfg.wall.fresh_activity_hours)
        for row in reversed(rows) if last is not None else []:
            if datetime.fromisoformat(row["start_time"]) >= oldest_fresh:
                self.client.publish(ha.event_topic(cfg.mqtt, user_id, "new_workout"),
                                    json.dumps(ha.new_workout_event(dict(row))))
        db.set_state(conn, _announced_key(user_id), rows[0]["start_time"])

    def sync_events(self, conn: sqlite3.Connection, cfg: AppConfig, user_id: str) -> None:
        """A failed sync and an expired Garmin login, once each. What was already so when this process
        started (or the person opted in) isn't announced."""
        r = conn.execute("SELECT last_attempt, last_error FROM sync_status WHERE user_id = ?", (user_id,)).fetchone()
        failed = r["last_attempt"] if r and r["last_error"] else None
        expired = paused_for_login(conn, user_id)
        before = self.sync_seen.get(user_id)
        self.sync_seen[user_id] = (failed, expired)
        if before is None:
            return
        if failed and failed != before[0]:
            self.client.publish(ha.event_topic(cfg.mqtt, user_id, "sync_failed"),
                                json.dumps({"event_type": "sync_failed", "error": r["last_error"]}))
        if expired and not before[1]:
            self.client.publish(ha.event_topic(cfg.mqtt, user_id, "login_expired"),
                                json.dumps({"event_type": "login_expired"}))


def api_sync(user_id: str) -> None:
    """Start a sync through the dashboard (same cooldown and "already running" rules as its button)."""
    url = f"{env('API_URL', 'http://127.0.0.1:8765').rstrip('/')}/api/users/{user_id}/sync"
    try:
        urllib.request.urlopen(urllib.request.Request(url, method="POST"), timeout=10).close()
        log.info("home assistant: sync started for %s", user_id)
    except urllib.error.HTTPError as e:
        log.info("home assistant: sync for %s not started: %s", user_id, e.code)
    except OSError as e:
        log.warning("home assistant: dashboard not reachable at %s: %s", url, e)


def run(conn: sqlite3.Connection) -> None:
    """Forever (restart: unless-stopped). Without an `mqtt` block in the config it only waits for one."""
    import paho.mqtt.client as mqtt

    cfg = load_config()
    while cfg.mqtt is None:
        log.info("home assistant: no \"mqtt\" block in the config, nothing to do")
        time.sleep(300)
        cfg = load_config()
    m = cfg.mqtt
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="fitvio")
    if m.username:
        client.username_pw_set(m.username, m.password)
    client.will_set(ha.availability_topic(m), "offline", retain=True)
    client.reconnect_delay_set(1, 120)

    class Client:  # what Bridge needs: publish only while connected (otherwise skipped, see run's loop)
        def publish(self, topic, payload, retain=False):
            client.publish(topic, payload, qos=1, retain=retain)

    bridge = Bridge(Client(), api_sync)
    connected = {"now": False, "new": False}

    def on_connect(c, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.warning("home assistant: broker refused the connection: %s", reason_code)
            return
        log.info("home assistant: connected to %s:%d", m.host, m.port)
        c.publish(ha.availability_topic(m), "online", qos=1, retain=True)
        for t in bridge.subscriptions(m):
            c.subscribe(t, qos=1)
        connected.update(now=True, new=True)

    def on_disconnect(c, userdata, flags, reason_code, properties):
        if connected["now"]:
            log.warning("home assistant: lost the broker (%s), retrying", reason_code)
        connected["now"] = False

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = lambda c, userdata, msg: bridge.on_message(m, msg.topic, msg.payload)
    client.connect_async(m.host, m.port, keepalive=60)
    client.loop_start()
    log.info("home assistant: sharing through %s:%d (topics %s/…)", m.host, m.port, m.topic_prefix)
    while True:
        time.sleep(TICK_S)
        step(bridge, conn, connected)


def step(bridge: Bridge, conn: sqlite3.Connection, connected: dict, settle_s: float = 1) -> bool:
    """One round of `run`. Returns whether anything was published."""
    if not connected["now"]:
        return False  # broker down: skip, paho keeps reconnecting and the next round tries again
    if connected["new"]:
        connected["new"] = False
        time.sleep(settle_s)  # let the retained discovery topics arrive first, so opted-out people get removed
        bridge.reset_published()
    try:
        cfg = load_config()  # people and opt-ins changed in the UI meanwhile
        if cfg.mqtt:
            bridge.tick(conn, cfg)
        return True
    except Exception:  # one bad round (e.g. a locked database) mustn't end the bridge
        log.exception("home assistant: publishing failed, retrying")
        return False

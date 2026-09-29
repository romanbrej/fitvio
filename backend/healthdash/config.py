"""App configuration: users, paths and wall behaviour.

Loaded from config/users.json (see config/users.example.json). The path can be
overridden with the HEALTHDASH_CONFIG env var, the app database with HEALTHDASH_DB.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class UserConfig:
    """One person. Only `id` and `garmindb_config_dir` are needed: name, sex, max/resting HR and
    FTP are read from Garmin automatically (see profile.py). Values set here override Garmin."""
    id: str
    name: str | None = None
    color: str = "#3B82F6"
    garmindb_config_dir: str | None = None
    max_hr: float | None = None
    rest_hr: float | None = None
    sex: str | None = None  # used for the TRIMP weighting factor
    ftp: float | None = None  # cycling; estimated from 20-min power if unknown
    lthr: float | None = None  # lactate threshold HR
    weight_kg: float | None = None  # W/kg when no weigh-in exists

    @property
    def display_name(self) -> str:
        return self.name or self.id.replace("_", " ").title()

    @property
    def initials(self) -> str:
        parts = self.display_name.split()
        return "".join(p[0] for p in parts[:2]).upper() or self.id[:2].upper()

    @property
    def garmindb_dir(self) -> Path | None:
        if not self.garmindb_config_dir:
            return None
        p = Path(self.garmindb_config_dir).expanduser()
        return p if p.is_absolute() else PROJECT_ROOT / p


@dataclass
class WallConfig:
    verdict_minutes: int = 60  # how long a fresh verdict stays on the wall
    fresh_activity_hours: int = 12  # older activities (e.g. backfill) never take over the wall
    idle_return_seconds: int = 120
    stale_sync_hours: int = 24
    night_start: str = "22:00"
    night_end: str = "06:30"


@dataclass
class AppConfig:
    users: list[UserConfig]
    wall: WallConfig = field(default_factory=WallConfig)
    db_path: Path = PROJECT_ROOT / "data" / "app.db"

    def user(self, user_id: str) -> UserConfig:
        for u in self.users:
            if u.id == user_id:
                return u
        raise KeyError(user_id)


def load_config(path: str | Path | None = None) -> AppConfig:
    path = Path(path or config_path())
    raw = json.loads(path.read_text()) if path.exists() else {"users": []}
    users = [UserConfig(**u) for u in raw.get("users", [])]
    wall = WallConfig(**raw.get("wall", {}))
    db_path = Path(os.environ.get("HEALTHDASH_DB") or raw.get("db_path") or PROJECT_ROOT / "data" / "app.db")
    return AppConfig(users=users, wall=wall, db_path=db_path.expanduser())


COLORS = ["#3B82F6", "#F97316", "#22C55E", "#EC4899", "#A78BFA", "#FACC15"]


def config_path() -> Path:
    return Path(os.environ.get("HEALTHDASH_CONFIG") or PROJECT_ROOT / "config" / "users.json")


def add_user(user_id: str, garmindb_config_dir: str) -> UserConfig:
    """Append a person to config/users.json (created if missing). Only id, colour and the GarminDB
    dir are stored; everything else comes from Garmin."""
    path = config_path()
    if path.name.endswith(".example.json"):
        # The example file is committed to git — a real account must never end up in it.
        raise ValueError(f"refusing to add a real account to {path.name}; run with your own config "
                         f"(default config/users.json) instead of the example/demo config")
    raw = json.loads(path.read_text()) if path.exists() else {"users": []}
    if any(u["id"] == user_id for u in raw["users"]):
        raise ValueError(f"user {user_id!r} already exists")
    entry = {"id": user_id, "color": COLORS[len(raw["users"]) % len(COLORS)], "garmindb_config_dir": garmindb_config_dir}
    raw["users"].append(entry)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2) + "\n")
    os.chmod(path, 0o600)
    return UserConfig(**entry)

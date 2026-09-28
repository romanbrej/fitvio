import json

import pytest

from healthdash import cli, config
from healthdash.sync import garmindb_runner


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HEALTHDASH_CONFIG", str(tmp_path / "users.json"))
    monkeypatch.setenv("HEALTHDASH_DB", str(tmp_path / "app.db"))
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    answers = iter(["alex.runner@example.com"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "secret")
    return tmp_path


def test_failed_login_leaves_nothing_behind(env, monkeypatch):
    def boom(user):
        raise RuntimeError("401 Unauthorized")
    monkeypatch.setattr(garmindb_runner, "login_interactive", boom)
    assert cli.main(["add-person", "--no-sync"]) == 1
    assert not (env / "users.json").exists()
    assert not (env / "data" / "garmindb" / "alex_runner").exists()


def test_successful_login_registers_person_with_only_credentials(env, monkeypatch):
    monkeypatch.setattr(garmindb_runner, "login_interactive", lambda user: "Alex Runner")
    assert cli.main(["add-person", "--no-sync"]) == 0
    users = json.loads((env / "users.json").read_text())["users"]
    assert users == [{"id": "alex_runner", "color": config.COLORS[0],
                      "garmindb_config_dir": "data/garmindb/alex_runner/config"}]
    cfg_dir = env / "data" / "garmindb" / "alex_runner" / "config"
    gc = json.loads((cfg_dir / "GarminConnectConfig.json").read_text())
    assert gc["credentials"]["user"] == "alex.runner@example.com"
    assert gc["data"]["download_all_activities"] >= 10000
    assert (cfg_dir / "password.txt").stat().st_mode & 0o077 == 0  # not readable by others

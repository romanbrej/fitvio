"""The GitHub Pages demo: made-up people only, every file the demo UI reads, and nothing personal in it."""
import json
import os
from pathlib import Path

import pytest

from fitvio.config import PROJECT_ROOT
from fitvio.demo_export import check_no_leaks, export, file_for


def test_file_names_match_the_frontend_mapping():
    assert file_for("/api/config") == "config.json"
    assert file_for("/api/users/alex/pmc?days=90") == "users/alex/pmc-90.json"
    assert file_for("/api/users/alex/health?days=7") == "users/alex/health-7.json"
    assert file_for("/api/sessions/alex%3Ademo-alex-202610080505") == "sessions/alex_demo-alex-202610080505.json"
    assert file_for("/api/sessions/alex:demo-alex-1") == "sessions/alex_demo-alex-1.json"


def test_export_uses_made_up_people_and_never_the_real_config(tmp_path, monkeypatch):
    real = [PROJECT_ROOT / "config", PROJECT_ROOT / "data"]
    read_text = Path.read_text

    def guarded(self, *a, **kw):
        assert not any(self.resolve().is_relative_to(r) for r in real), f"the demo read {self}"
        return read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", guarded)
    monkeypatch.setenv("FITVIO_CONFIG", str(tmp_path / "not-the-demo.json"))
    out = tmp_path / "demo-data"
    counts = export(out, days=60)  # enough history for the fresh run to be compared

    assert os.environ["FITVIO_CONFIG"] == str(tmp_path / "not-the-demo.json")  # put back afterwards
    config = json.loads((out / "config.json").read_text())
    assert [u["name"] for u in config["users"]] == ["Alex", "Sam"]
    wall = json.loads((out / "wall.json").read_text())
    assert (wall["mode"], wall["session"]["verdict"]["verdict"]) == ("verdict", "better")  # the demo opens on a good day
    sources = {a["id"]: a["source"] for a in json.loads((out / "accounts.json").read_text())}
    assert sources == {"alex": "garmin", "sam": "intervals"}
    for uid in ("alex", "sam"):
        for name in ("ambient", "profile", "validation", "sessions", "pmc-42", "pmc-365", "health-7", "health-365"):
            assert (out / "users" / uid / f"{name}.json").exists(), f"{uid}/{name}"
        sessions = json.loads((out / "users" / uid / "sessions.json").read_text())
        assert sessions and all((out / file_for(f"/api/sessions/{s['id']}")).exists() for s in sessions)
    assert counts["sessions"] == len(list((out / "sessions").iterdir()))
    # the units switch: the server-written text again in imperial, a session with only its verdict and gains
    for uid in ("alex", "sam"):
        assert (out / "users" / uid / "units.json").exists()
        assert json.loads((out / "imperial" / "users" / uid / "ambient.json").read_text())["units"] == "imperial"
    assert json.loads((out / "imperial" / "wall.json").read_text())["ambient"]["units"] == "imperial"
    texts = [f.read_text() for f in (out / "imperial" / "sessions").iterdir()]
    assert all(set(json.loads(x)) == {"verdict", "improvements"} for x in texts)
    assert any("/mi" in x for x in texts) and not any("/km" in x or "°C" in x for x in texts)
    assert json.loads((out / "config.json").read_text())["users"][0]["units"] == "metric"


def test_leak_check_refuses_names_addresses_and_paths(tmp_path):
    (tmp_path / "a.json").write_text('{"name": "Alex"}')
    check_no_leaks(tmp_path, ["Robin"])  # nothing denied in there
    for bad in ('"Robin"', '"192.168.178.20"', '"robin@example.com"', '"/Users/robin/data"'):
        (tmp_path / "b.json").write_text(bad)
        with pytest.raises(ValueError, match="not publishing"):
            check_no_leaks(tmp_path, ["Robin"])

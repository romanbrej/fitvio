import pytest

from fitvio.sync import open_meteo


@pytest.fixture(autouse=True)
def no_weather_network(monkeypatch):
    """Tests never call Open-Meteo: a lookup behaves as if the server were offline unless a test
    passes its own recorded answers."""
    def offline(url):
        raise open_meteo.WeatherUnavailable("offline in tests")
    monkeypatch.setattr(open_meteo, "_urlopen", offline)


@pytest.fixture(autouse=True)
def own_config(tmp_path, monkeypatch):
    """Tests never read or write the real config/users.json (code like the sync lock looks at it)."""
    monkeypatch.setenv("FITVIO_CONFIG", str(tmp_path / "config" / "users.json"))

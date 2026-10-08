import pytest

from fitvio.sync import open_meteo


@pytest.fixture(autouse=True)
def no_weather_network(monkeypatch):
    """Tests never call Open-Meteo: a lookup behaves as if the server were offline unless a test
    passes its own recorded answers."""
    def offline(url):
        raise open_meteo.WeatherUnavailable("offline in tests")
    monkeypatch.setattr(open_meteo, "_urlopen", offline)

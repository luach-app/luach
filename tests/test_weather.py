"""The forecast that rides along with a search about the weather."""

from __future__ import annotations

import pytest

from luach import weather
from luach.agent.tools import search_the_web

DAILY = {
    "time": ["2026-10-28", "2026-10-29"],
    "weather_code": [3, 61],
    "temperature_2m_max": [15.6, 18.8],
    "temperature_2m_min": [5.0, 5.0],
    "precipitation_probability_max": [1, 70],
    "precipitation_sum": [0.0, 4.2],
    "wind_speed_10m_max": [12.0, 15.2],
}
NEW_YORK = {"name": "New York", "admin1": "New York", "country": "United States",
            "latitude": 40.71, "longitude": -74.01, "timezone": "America/New_York",
            "population": 8804190}  # fmt: skip


class Answer:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        pass


@pytest.fixture
def services(monkeypatch):
    """Open-Meteo's geocoder knows a few places; its forecast is DAILY; the search
    engine returns one result. Records every place asked for."""
    import requests

    asked: list[str] = []
    places = {"New York": NEW_YORK, "Brooklyn": {**NEW_YORK, "name": "Brooklyn"},
              "Jacket": {**NEW_YORK, "name": "Jacket", "population": 40}}  # fmt: skip

    def get(url, params=None, **kw):
        if url == weather.GEOCODE:
            asked.append(params["name"])
            found = places.get(params["name"])
            return Answer({"results": [found]} if found else {})
        if url == weather.FORECAST:
            return Answer({"daily": DAILY})
        hit = {"title": "Weather", "url": "https://example.com/w", "content": "Tomorrow, on Monday"}
        return Answer({"results": [hit]})

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setenv("LUACH_SEARCH_URL", "http://searxng:8080")
    return asked


@pytest.mark.parametrize(
    "query, place",
    [
        ("New York weather forecast October 29 2026", "New York"),
        ("NWS New York NY weather forecast October 29", "New York NY"),
        ('site:forecast.weather.gov "New York NY" forecast', "New York NY"),
        ("¿va a llover mañana en Nueva York?", "Nueva York"),
        ("מזג אוויר מחר ניו יורק", "ניו יורק"),
        ("weather tomorrow", ""),
    ],
)
def test_the_place_is_what_is_left_of_a_weather_search(query, place):
    assert weather.is_about_weather(query)
    assert weather.place_in(query) == place


@pytest.mark.parametrize("query", ["Chelsea game this weekend", "tiempo de viaje a Boston"])
def test_a_search_that_is_not_about_the_weather_gets_no_forecast(query, services):
    assert weather.for_query(query, "America/New_York") is None
    assert services == []


def test_a_weather_search_brings_a_forecast_for_its_place(services):
    """The pages a search finds for "weather tomorrow" are monthly averages and old
    snippets: qwen once answered "between 60° and 73° Celsius" from one."""
    out = search_the_web.fn(query="NWS New York NY weather forecast October 29")
    assert out["results"]  # the search still runs
    forecast = out["forecast"]
    assert services == ["New York NY", "New York"]  # a longer name that is no place is cut
    assert forecast["place"] == "New York, New York, United States"
    tomorrow = forecast["days"][1]
    assert tomorrow == {
        "date": "2026-10-29", "sky": "light rain", "high": "19°C / 66°F", "low": "5°C / 41°F",
        "chance_of_rain": "70%", "rain_mm": 4.2, "wind_max_kmh": 15.2,
    }  # fmt: skip
    assert "Open-Meteo" in forecast["note"] and "household's city" not in forecast["note"]


def test_a_weather_search_that_names_no_place_is_for_home(services):
    out = weather.for_query("weather tomorrow", "America/New_York")
    assert services == ["New York"]
    assert "household's city, New York" in out["note"]


def test_a_place_no_map_knows_is_not_taken_for_home(services):
    """A search for "rain jacket brands" names a hamlet called Jacket, not a forecast."""
    assert weather.for_query("rain jacket brands", "America/New_York") is None


def test_a_weather_service_that_does_not_answer_leaves_the_search_alone(monkeypatch, services):
    import requests

    def down(url, params=None, **kw):
        if url in (weather.GEOCODE, weather.FORECAST):
            raise requests.ConnectionError("down")
        return Answer({"results": [{"title": "W", "url": "https://example.com/w", "content": ""}]})

    monkeypatch.setattr(requests, "get", down)
    out = search_the_web.fn(query="weather New York tomorrow")
    assert out["count"] == 1 and "forecast" not in out

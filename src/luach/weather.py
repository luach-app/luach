"""A forecast from a weather service, for the searches that ask for one.

"What's the weather tomorrow" is one of the questions a family asks most, and
the open web answers it badly: the pages a search finds are monthly averages,
yesterday's snippets and forecasts that need a browser. Asked for tomorrow in
New York on 28 October 2026, qwen once read world-weather.info's October page
and said "between 60° and 73° Celsius"; another time a snippet's "Tomorrow, on
Monday" stood for a Thursday. Open-Meteo answers a place and a day with numbers,
needs no key, and covers the world.

Nothing here is offered to the model as a tool of its own. search_the_web calls
:func:`for_query` when the words searched are about the weather, and puts the
forecast beside the results: the model already searches for the weather, and a
tool it does not reach for is a tool that does not help.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
TIMEOUT = 6
DAYS = 7

#: A search about the weather, in the household's three languages.
WEATHER = re.compile(
    r"\b(?:weather|forecast|temperature|rain|raining|snow|sunny|umbrella|"
    r"clima|pron[oó]stico|lluvia|llover|llueve|nieve|temperatura|paraguas)\b|"
    r"מזג[\s-]?(?:ה)?אוויר|תחזית|גשם|שלג|טמפרטורה",
    re.I,
)
#: A place too small to be what a family means by a name: "jacket" is a hamlet
#: somewhere, "rain jacket brands" is not a weather question about it.
MIN_POPULATION = 5000
#: Words in a weather search that are not the place.
_NOT_PLACE = re.compile(
    r"\b(?:weather|forecast|temperature|rain|raining|snow|sunny|umbrella|hourly|daily|"
    r"weekly|today|tonight|tomorrow|this|next|week|weekend|morning|afternoon|evening|"
    r"will|it|is|be|the|for|in|at|on|of|and|what|whats|how|nws|accuweather|site:\S+|"
    r"clima|tiempo|pron[oó]stico|lluvia|llover|llueve|nieve|temperatura|paraguas|hoy|"
    r"mañana|manana|esta|este|semana|fin|de|en|el|la|del|para|va|a|"
    r"jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|oct\w*|nov\w*|dec\w*|"
    r"ene\w*|abr\w*|ago\w*|dic\w*|mon\w*|tue\w*|wed\w*|thu\w*|fri\w*|sat\w*|sun\w*|"
    r"lunes|martes|miércoles|jueves|viernes|sábado|domingo|\d+(?:st|nd|rd|th)?)\b|"
    r"מזג[\s-]?(?:ה)?אוויר|תחזית|גשם|שלג|טמפרטורה|היום|מחר|השבוע|בסוף|"
    r"""[?¿!,.:;"'()]""",
    re.I,
)

#: WMO weather interpretation codes, as Open-Meteo returns them.
_SKY = {
    0: "clear", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog",
    48: "fog", 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "freezing drizzle", 57: "freezing drizzle", 61: "light rain", 63: "rain",
    65: "heavy rain", 66: "freezing rain", 67: "freezing rain", 71: "light snow",
    73: "snow", 75: "heavy snow", 77: "snow grains", 80: "rain showers",
    81: "rain showers", 82: "violent rain showers", 85: "snow showers",
    86: "heavy snow showers", 95: "thunderstorm", 96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}  # fmt: skip


def is_about_weather(query: str) -> bool:
    return bool(WEATHER.search(query))


def place_in(query: str) -> str:
    """What is left of a weather search once the weather and the dates are taken out."""
    return " ".join(_NOT_PLACE.sub(" ", query).split())


def _home(tz: str) -> str:
    """The household's city when the search names none: its timezone's
    ("America/New_York" is New York). A guess, said as one in the forecast."""
    return tz.rsplit("/", 1)[-1].replace("_", " ") if "/" in tz else ""


def _get(url: str, params: dict[str, Any]) -> Any:
    import requests

    r = requests.get(url, params=params, timeout=TIMEOUT, headers={"User-Agent": "luach/0.1"})
    r.raise_for_status()
    return r.json()


def geocode(place: str) -> dict[str, Any] | None:
    """The best-known place by that name, trying shorter names when the whole
    one is not a place ("New York NY" is not; "New York" is)."""
    words = place.split()
    for n in range(len(words), 0, -1):
        name = " ".join(words[:n])
        found = (_get(GEOCODE, {"name": name, "count": 1}) or {}).get("results") or []
        if found and int(found[0].get("population") or 0) >= MIN_POPULATION:
            return found[0]
    return None


def for_query(query: str, tz: str) -> dict[str, Any] | None:
    """The coming week's forecast for the place a weather search names (the
    household's own city when it names none), or None when the search is not
    about the weather or the service did not answer."""
    if not is_about_weather(query):
        return None
    named = place_in(query)
    try:
        # A place the search names and no map knows is not a weather question
        # about home; only a search that names no place at all is.
        where = geocode(named or _home(tz)) if (named or _home(tz)) else None
        if where is None:
            return None
        daily = _get(
            FORECAST,
            {
                "latitude": where["latitude"],
                "longitude": where["longitude"],
                "timezone": where.get("timezone") or tz or "auto",
                "forecast_days": DAYS,
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,precipitation_sum,wind_speed_10m_max",
            },
        )["daily"]
    except Exception:
        logger.warning("weather: no forecast for %r", query[:60], exc_info=True)
        return None
    label = ", ".join(
        str(x) for x in (where.get("name"), where.get("admin1"), where.get("country")) if x
    )
    days = []
    for i, day in enumerate(daily.get("time", [])):
        hi, lo = daily["temperature_2m_max"][i], daily["temperature_2m_min"][i]
        if hi is None or lo is None:
            continue
        days.append(
            {
                "date": day,
                "sky": _SKY.get(daily["weather_code"][i], "unknown"),
                "high": f"{hi:.0f}°C / {hi * 9 / 5 + 32:.0f}°F",
                "low": f"{lo:.0f}°C / {lo * 9 / 5 + 32:.0f}°F",
                "chance_of_rain": f"{daily['precipitation_probability_max'][i] or 0:.0f}%",
                "rain_mm": daily["precipitation_sum"][i],
                "wind_max_kmh": daily["wind_speed_10m_max"][i],
            }
        )
    if not days:
        return None
    note = (
        "A forecast from Open-Meteo, a weather service, by day in that place's own dates. "
        "Prefer it to the search results for the weather, and say it is a forecast."
    )
    if not named:
        note += f" The search named no place, so this is for the household's city, {label}."
    return {"place": label, "source": "Open-Meteo", "note": note, "days": days}

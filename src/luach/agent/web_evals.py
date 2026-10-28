"""Web questions a family really asks, scored on whether the answer was right.

The unit tests prove the plumbing of search_the_web and read_web_page with a
scripted model and canned pages; they say nothing about whether a real model,
on the household's real search engine, tells a parent the right time for the
Chelsea game. These cases put each question through ``runtime.run_turn`` on a
fake calendar and a throwaway database, with whatever ``LUACH_SEARCH_URL`` and
model the environment names, and score the reply three ways:

- **correct** — it holds the fact the case checks;
- **unsure** — it does not, and says it could not find or confirm it;
- **wrong** — it does not, and says something else as though it were so.

The web goes stale, so no case compares with a fixed string forever:

- facts that hold for years (an address, the day a museum closes) are fixed;
- facts that can be worked out today are fetched or computed when the case runs
  (tomorrow's weather from Open-Meteo, candle lighting and Chanukah from Hebcal,
  the next clock change from the timezone database);
- a fact about one week (this weekend's game) carries the date it is good until,
  and after that the case checks only the answer's shape: a day and a time, said
  without hedging. Re-pin those when you re-baseline.

There is no LLM judge on purpose: the judge is the model under test, and it has
failed answers that were right (see evals.py). Read the trajectories it prints.

Run it against a real search engine, the SearXNG your luach uses (a stand-in shapes the
answer it measures), and whichever model the environment points at::

    LUACH_SEARCH_URL=http://127.0.0.1:18890 LUACH_MODEL=… OPENAI_BASE_URL=… \\
        OPENAI_API_KEY=… python -m luach.agent.web_evals --repeat 2

``--only`` runs the cases whose name contains it, ``--json`` writes every
trajectory (queries, results, pages read, reply, seconds) for reading later.
"""

from __future__ import annotations

import argparse
import asyncio
import contextvars
import json
import logging
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

TZ = "America/New_York"
#: The household's city for the cases that name none ("the weather tomorrow").
LAT, LON = 40.71, -74.01

CORRECT, UNSURE, WRONG = "correct", "unsure", "wrong"


# --- What the household knows today ---------------------------------------------


@dataclass
class Today:
    """The facts a case may need, fetched once per run. Any of them can be None
    when its source did not answer; a case that needs it is then skipped."""

    day: date
    weather: dict[str, float] | None = None  # tomorrow: high/low in C and F, rain chance
    candles: datetime | None = None  # the coming Friday's candle lighting in New York
    chanukah: date | None = None  # the first candle, this year's or next
    clocks: date | None = None  # the next change of the clocks in TZ


def _get_json(url: str) -> Any:
    import requests

    r = requests.get(url, timeout=10, headers={"User-Agent": "luach-web-evals"})
    r.raise_for_status()
    return r.json()


def next_clock_change(now: datetime) -> date:
    """The next day the household's clocks change, from the timezone database."""
    tz = ZoneInfo(TZ)
    start = now.astimezone(tz)
    offset = start.utcoffset()
    for hours in range(1, 24 * 370):
        t = (start + timedelta(hours=hours)).astimezone(tz)
        if t.utcoffset() != offset:
            return t.date()
    return start.date()


def fetch_today(now: datetime | None = None) -> Today:
    now = now or datetime.now(ZoneInfo(TZ))
    today = Today(day=now.date(), clocks=next_clock_change(now))
    try:
        daily = _get_json(
            "https://api.open-meteo.com/v1/forecast?"
            f"latitude={LAT}&longitude={LON}&daily=temperature_2m_max,temperature_2m_min,"
            f"precipitation_probability_max&timezone={TZ}&forecast_days=3"
        )["daily"]
        hi, lo = daily["temperature_2m_max"][1], daily["temperature_2m_min"][1]
        today.weather = {
            "high_c": hi, "low_c": lo, "high_f": hi * 9 / 5 + 32, "low_f": lo * 9 / 5 + 32,
            "rain": float(daily["precipitation_probability_max"][1] or 0),
        }  # fmt: skip
    except Exception:
        logger.warning("web evals: no forecast", exc_info=True)
    try:
        friday = now.date() + timedelta(days=(4 - now.weekday()) % 7)
        items = _get_json(
            "https://www.hebcal.com/shabbat?cfg=json&geonameid=5128581"
            f"&gy={friday.year}&gm={friday.month}&gd={friday.day}"
        )["items"]
        lit = next(i["date"] for i in items if i.get("category") == "candles")
        today.candles = datetime.fromisoformat(lit)
    except Exception:
        logger.warning("web evals: no candle lighting", exc_info=True)
    try:
        for year in (now.year, now.year + 1):
            items = _get_json(
                f"https://www.hebcal.com/hebcal?v=1&cfg=json&maj=on&year={year}&month=12"
            )["items"]
            first = [date.fromisoformat(i["date"][:10]) for i in items if "1 Candle" in i["title"]]
            if first and first[0] >= now.date():
                today.chanukah = first[0]
                break
    except Exception:
        logger.warning("web evals: no Chanukah date", exc_info=True)
    return today


# --- Reading a reply -------------------------------------------------------------

#: Said when the answer was not found. Only consulted when the fact is missing:
#: "check their site before you go" is good advice in a right answer too.
HEDGES = re.compile(
    r"could(?:n'?t| not) (?:find|confirm|get|see|open|load)|did(?:n'?t| not) find|"
    r"not sure|unable to|don'?t know|was(?:n'?t| not) able|no (?:clear|firm|confirmed)|"
    r"isn'?t listed|not (?:yet )?(?:listed|announced|published|confirmed)|"
    r"can'?t (?:find|confirm|tell|see)|no (?:han|ha|está|están) (?:sido )?confirmad|aún no|"
    r"no (?:pude|encontr[ée]|logr[ée]|estoy segur)|no s[ée]\b|no (?:aparece|figura|está claro)|"
    r"לא מצאתי|לא הצלחתי|לא בטוח|אין לי|לא ברור|לא נמצא",
    re.I,
)
#: Says where the answer came from.
CITES = re.compile(
    r"\b(?:site|website|page|according|listing|listed|official|forecast|says|said)\b|"
    r"\b\w+\.(?:com|org|net|gov|co\.il|uk|es|ar)\b|según|sitio|página|pronóstico|indica|"
    r"לפי|באתר|אתר|תחזית",
    re.I,
)
_TIME = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\.?|p\.?m\.?|h\b|hs\b)?", re.I)
_TEMP = re.compile(
    r"(\d{1,3}(?:\.\d)?)\s*(?:°|º|degrees?|grados?|מעלות)\s*(c|f|celsius|fahrenheit)?", re.I
)


def _norm(text: str) -> str:
    # Hebrew writes a quotation mark inside abbreviations (כ"ה) with any of three marks.
    return " ".join(text.replace("״", '"').replace("׳", "'").split())


def clock_minutes(reply: str) -> list[int]:
    """Every clock time in the reply, as minutes after midnight (12-hour times
    read both ways, since "5:36" in Hebrew means the evening)."""
    out: list[int] = []
    for m in _TIME.finditer(reply):
        h, mins, half = int(m.group(1)), m.group(2), (m.group(3) or "").lower()
        if mins is None and not half:
            continue
        mm = int(mins or 0)
        if h > 23 or mm > 59:
            continue
        if half.startswith("p") and h < 12:
            h += 12
        elif half.startswith("a") and h == 12:
            h = 0
        out.append(h * 60 + mm)
        if not half and h < 12:
            out.append((h + 12) * 60 + mm)
    return out


def temperatures(reply: str) -> list[tuple[float, str]]:
    """(value, unit) for every temperature in the reply; unit is "c", "f" or ""
    when it did not say. A forecast in prose writes some without a degree
    ("בוקר 12 מעלות, אחר הצהריים 19"), so the bare numbers count too, all but
    those that are clock times, years, dates, percentages, speeds or distances."""
    found = [(float(v), (u or "")[:1].lower()) for v, u in _TEMP.findall(reply)]
    rest = _TEMP.sub(" ", reply)
    for pattern in _NOT_TEMPERATURES:
        rest = pattern.sub(" ", rest)
    found += [(float(v), "") for v in re.findall(r"(?<![\d.,])(\d{1,3})(?!\d|[.,]\d)", rest)]
    return found


_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|ene|abr|ago|dic)\w*|(?:ב)?(?:ינואר|פברואר|מרץ|אפריל|מאי|יוני|יולי|אוגוסט|ספטמבר|אוקטובר|נובמבר|דצמבר)"
_NOT_TEMPERATURES = (
    re.compile(r"\d{1,2}[:.]\d{2}|\b\d{4}\b"),
    re.compile(r"\d+\s*(?:-|–|to|a)?\s*\d*\s*(?:%|km|mph|m/s|kph|מטר|קמ)", re.I),
    re.compile(rf"(?:{_MONTHS})\.?\s*\d+|\d+\s*(?:de\s+)?(?:{_MONTHS})", re.I),
)


@dataclass(frozen=True)
class Question:
    name: str
    lang: str
    kind: str
    text: str
    #: What a right answer holds, for a person reading the report.
    expect: str
    #: Is the fact in the reply? None when the case cannot be judged today.
    check: Callable[[str, Today], bool | None]


def _all(*patterns: str, but_not: tuple[str, ...] = ()) -> Callable[[str, Today], bool]:
    """Every pattern is in the reply, and none of ``but_not``: a right fact said
    beside a wrong one ("12:30 UK time, 7:30 your time") is not a right answer."""
    wanted = [re.compile(p, re.I) for p in patterns]
    unwanted = [re.compile(p, re.I) for p in but_not]
    return lambda reply, _today: (
        all(r.search(_norm(reply)) for r in wanted)
        and not any(r.search(_norm(reply)) for r in unwanted)
    )


def _until(last: str, exact: Callable[[str, Today], bool]) -> Callable[[str, Today], bool]:
    """A fact about one week: checked exactly through ``last``, and after that only
    for its shape — a day or date and a time, said without hedging."""
    until = date.fromisoformat(last)

    def check(reply: str, today: Today) -> bool:
        if today.day <= until:
            return exact(reply, today)
        return bool(clock_minutes(reply) or re.search(r"\d", reply)) and not HEDGES.search(reply)

    return check


def _weather(reply: str, today: Today) -> bool | None:
    w = today.weather
    if w is None:
        return None
    # The high is the warmest number given in each scale; a low near the real high
    # ("highs around 75°F and lows near 61°F" for a 66°F day) is not a right high.
    highs: dict[str, float] = {}
    for value, unit in temperatures(reply):
        highs[unit] = max(value, highs.get(unit, value))
    return any(
        (unit in ("c", "") and abs(high - w["high_c"]) <= 3)
        or (unit in ("f", "") and abs(high - w["high_f"]) <= 5)
        for unit, high in highs.items()
    )


def _rain(reply: str, today: Today) -> bool | None:
    w = today.weather
    if w is None:
        return None
    text = _norm(reply).lower()
    says_no = re.search(r"\bno\b|sin lluvia|seco|despejad|soleado", text)
    if w["rain"] < 20:
        return bool(says_no)
    if w["rain"] > 60:
        return not re.search(r"\bno (?:va a|se espera|llover)", text)
    return not HEDGES.search(reply)


def _candles(reply: str, today: Today) -> bool | None:
    if today.candles is None:
        return None
    lit = today.candles.hour * 60 + today.candles.minute
    # Calendars differ by a few minutes (18 minutes before sunset, or 15, or 20).
    return any(abs(m - lit) <= 4 for m in clock_minutes(reply))


def _chanukah(reply: str, today: Today) -> bool | None:
    if today.chanukah is None:
        return None
    text = _norm(reply)
    day = today.chanukah.day
    # The first candle is lit the evening before the first day.
    days = {day, (today.chanukah + timedelta(days=1)).day}
    named = any(re.search(rf"(?<!\d){d}(?!\d)", text) for d in days)
    month = re.search(r"דצמבר|dec", text, re.I) and today.chanukah.month == 12
    return bool(named and month) or bool(re.search(r'כ"?ה (?:ב)?כסלו', text))


def _clocks(reply: str, today: Today) -> bool | None:
    if today.clocks is None:
        return None
    month = today.clocks.strftime("%B")
    text = _norm(reply)
    return bool(
        re.search(rf"(?<!\d){today.clocks.day}(?!\d)", text) and re.search(month[:3], text, re.I)
    )


def _asks_where(reply: str, _today: Today) -> bool:
    """A question with no place in it has two right answers: ask which one, or
    answer for a named one and say so."""
    return "?" in reply and bool(
        re.search(r"which|where|what (?:pharmacy|area|part)|near", reply, re.I)
    )


QUESTIONS: tuple[Question, ...] = (
    # English
    Question("chelsea_weekend", "en", "sport", "what time is the Chelsea game this weekend?",
             "Sat 31 Oct v Man United, 12:30 UK = 8:30 ET",
             # 12:30 in London is 8:30 in New York that week, not 7:30: the UK's
             # clocks went back on 25 Oct, New York's go back on 1 Nov. ESPN's
             # "8:30 AM" is Eastern, and was once passed on as UK time.
             _until("2026-10-31", _all(
                 r"8[:.]30|12[:.]30.{0,25}(?:UK|GMT|London|British)",
                 but_not=(r"\b[3679][:.]30", r"8[:.]30.{0,15}(?:UK|GMT|London|British)")))),
    Question("amnh_monday", "en", "hours", "is the natural history museum open on monday?",
             "yes, AMNH 10:00-17:30 daily", _all(r"\b10\b|10[:.]00|10 ?am", r"5[:.]30|17[:.]30")),
    Question("brooklyn_museum_monday", "en", "hours", "is the Brooklyn Museum open on Monday?",
             "no, closed Mon and Tue", _all(r"closed|not open|isn'?t open|is not open")),
    Question("met_wednesday", "en", "hours", "can we go to the Met on Wednesday?",
             "no, the Met is closed on Wednesdays", _all(r"closed|not open|isn'?t open|is not open")),
    Question("bronx_zoo_sunday", "en", "hours", "what time does the Bronx Zoo close on Sunday?",
             "4:30pm (winter hours from 1 Nov)", _until("2027-03-28", _all(r"4[:.]30|16[:.]30"))),
    Question("apple_fifth_sunday", "en", "hours",
             "what time does the Apple store on Fifth Avenue close on sunday?",
             "it never closes: open 24 hours",
             _all(r"24 ?hours|24/7|always open|never closes|around the clock|open all night")),
    Question("momi_address", "en", "address", "where is the Museum of the Moving Image?",
             "36-01 35th Ave, Astoria", _all(r"36-01|35(?:th)? Ave")),
    Question("knicks_home", "en", "sport", "when is the next Knicks home game?",
             "Mon 2 Nov v Nets, 7:30pm",
             _until("2026-11-02", _all(r"Nets|Brooklyn", r"Nov(?:ember)?\.? 2\b|2 Nov|Monday"))),
    Question("msg_weekend", "en", "events", "any concerts at Madison Square Garden this weekend?",
             "Harry Styles, Fri 30 and Sat 31 Oct", _until("2026-10-31", _all(r"Harry Styles"))),
    Question("marathon", "en", "events", "when is the NYC marathon this year?",
             "Sunday 1 November 2026",
             _until("2026-11-01", _all(r"Nov(?:ember)?\.? 1\b|1(?:st)? (?:of )?Nov|Sunday"))),
    Question("clocks_back", "en", "dates", "when do the clocks change?",
             "the next change in America/New_York (1 Nov 2026)", _clocks),
    Question("election_day_school", "en", "school",
             "do NYC public school kids have school on election day?",
             "yes, remotely: 3 Nov 2026 is a remote school day",
             _until("2026-11-03", _all(r"remote|online|virtual|from home"))),
    Question("weather_tomorrow_en", "en", "weather", "what's the weather tomorrow in New York?",
             "tomorrow's high from Open-Meteo, within 3°C / 5°F", _weather),
    Question("pharmacy_sunday", "en", "near me", "when does the pharmacy close on sunday?",
             "asks which pharmacy or where", _asks_where),
    # Spanish
    Question("real_madrid_weekend", "es", "sport", "¿a qué hora juega el Real Madrid este fin de semana?",
             "dom 1 nov en Racing, 16:15 España = 10:15 ET",
             # 16:15 in Spain on 1 Nov is 10:15 in New York (UTC-5 from 2am that day).
             _until("2026-11-01", _all(
                 r"Racing", r"16[:.]15|10[:.]15|4[:.]15",
                 but_not=(r"\b(?:9|11|15)[:.]15", r"10[:.]15.{0,25}(?:Espa|Spain|Madrid)")))),
    Question("moma_lunes", "es", "hours", "¿está abierto el MoMA el lunes?",
             "sí, 10:30 a 17:30", _all(r"10[:.]30", r"5[:.]30|17[:.]30")),
    Question("consulado_argentino", "es", "address",
             "¿cuál es la dirección del consulado argentino en Nueva York?",
             "12 West 56th Street", _all(r"\b56\b|56th|calle 56")),
    Question("seleccion_argentina", "es", "sport", "¿cuándo juega la selección argentina?",
             "vie 13 nov contra Uruguay",
             _until("2026-11-13", _all(r"Uruguay", r"\b13\b"))),
    Question("lluvia_manana", "es", "weather", "¿va a llover mañana en Nueva York?",
             "lo que diga Open-Meteo (hoy: no)", _rain),
    Question("desfile_halloween", "es", "events",
             "¿a qué hora empieza el desfile de Halloween del Village?",
             "sáb 31 oct, 19:00", _until("2026-10-31", _all(r"\b7\b|19[:.]00|19 ?h"))),
    Question("escuelas_noviembre", "es", "school",
             "¿qué días no hay clases en noviembre en las escuelas públicas de Nueva York?",
             "11 nov (Veterans Day), 26 y 27 nov (Thanksgiving)",
             _until("2026-11-27", _all(
                 r"\b11\b", r"\b26\b|\b27\b",
                 but_not=(r"\b[3-6] de noviembre\W+(?:Día de )?(?:Acci|las Elecc|Thanks)",
                          r"\b25\b[^.;]{0,40}Acci")))),
    # Hebrew
    Question("candles_friday", "he", "dates", "מתי כניסת שבת ביום שישי בניו יורק?",
             "candle lighting from Hebcal (30 Oct: 17:36), within 4 minutes", _candles),
    Question("chanukah", "he", "dates", "מתי חנוכה השנה?",
             "first candle from Hebcal (4 Dec 2026)", _chanukah),
    Question("consulate_il", "he", "address", "מה הכתובת של הקונסוליה הישראלית בניו יורק?",
             "800 Second Avenue", _all(r"\b800\b")),
    Question("weather_he", "he", "weather", "מה מזג האוויר מחר בניו יורק?",
             "tomorrow's high from Open-Meteo, within 3°C / 5°F", _weather),
    Question("amnh_sunday_he", "he", "hours", "האם מוזיאון הטבע בניו יורק פתוח ביום ראשון?",
             "כן, 10:00-17:30", _all(r"\b10\b|10[:.]00", r"5[:.]30|17[:.]30")),
)  # fmt: skip


def verdict(q: Question, reply: str, today: Today) -> str | None:
    found = q.check(reply, today)
    if found is None:
        return None
    if found:
        return CORRECT
    return UNSURE if HEDGES.search(reply) or not reply.strip() else WRONG


# --- Running a case --------------------------------------------------------------


@dataclass
class Trace:
    name: str
    lang: str
    kind: str
    question: str
    expect: str
    verdict: str | None = None
    cites: bool = False
    reply: str = ""
    seconds: float = 0.0
    tools: list[str] = field(default_factory=list)
    searches: list[dict[str, Any]] = field(default_factory=list)
    reads: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


_trace: contextvars.ContextVar[Trace | None] = contextvars.ContextVar("web_trace", default=None)


def _record() -> None:
    """Wrap the search and the reader so each case's trajectory is kept: what was
    searched, what came back, which pages were read and whether they opened."""
    from luach import websearch

    if getattr(websearch.search, "_recorded", False):
        return
    search, read_page = websearch.search, websearch.read_page

    def recorded_search(query: str, *a: Any, **kw: Any) -> Any:
        t = _trace.get()
        try:
            hits = search(query, *a, **kw)
        except Exception as exc:
            if t is not None:
                t.searches.append({"query": query, "error": str(exc)})
            raise
        if t is not None:
            t.searches.append({"query": query, "hits": [h.as_dict() for h in hits]})
        return hits

    def recorded_read(url: str, looking_for: str = "") -> Any:
        t = _trace.get()
        entry: dict[str, Any] = {"url": url, "looking_for": looking_for}
        try:
            page = read_page(url, looking_for)
        except Exception as exc:
            entry["error"] = str(exc)
            if t is not None:
                t.reads.append(entry)
            raise
        entry["chars"] = len(page.get("text", ""))
        entry["text"] = page.get("text", "")[:600]
        if t is not None:
            t.reads.append(entry)
        return page

    recorded_search._recorded = True  # type: ignore[attr-defined]
    websearch.search = recorded_search  # type: ignore[assignment]
    websearch.read_page = recorded_read  # type: ignore[assignment]


async def run_case(q: Question, user_id: int, today: Today) -> Trace:
    from luach.agent import runtime

    trace = Trace(q.name, q.lang, q.kind, q.text, q.expect)
    _trace.set(trace)
    started = time.monotonic()
    try:
        result = await runtime.run_turn(
            q.text, user_id=user_id, principal="robin", timezone=TZ, door="smoke"
        )
        trace.reply = result.reply
        trace.tools = [str(c.get("tool")) for c in result.tool_calls]
        trace.error = result.error or ""
    except Exception as exc:  # one case failing to run is that case's result
        logger.exception("web eval %s", q.name)
        trace.error = f"{type(exc).__name__}: {exc}"
    trace.seconds = round(time.monotonic() - started, 1)
    trace.verdict = verdict(q, trace.reply, today)
    trace.cites = bool(CITES.search(trace.reply))
    return trace


def report(traces: list[Trace]) -> str:
    out: list[str] = []
    for t in traces:
        mark = {CORRECT: "OK  ", UNSURE: "UNSURE", WRONG: "WRONG"}.get(t.verdict or "", "SKIP")
        queries = " | ".join(s["query"] for s in t.searches)
        out.append(f"{mark:6} {t.name} ({t.seconds}s) searched: {queries or '-'}")
        if t.verdict != CORRECT:
            out.append(f"       want: {t.expect}")
            out.append(f"       said: {' '.join(t.reply.split())[:240]}")
            for r in t.reads:
                out.append(f"       read: {r['url'][:90]} {r.get('error') or ''}")
            if t.error:
                out.append(f"       error: {t.error}")
    judged = [t for t in traces if t.verdict]
    counts = {v: sum(t.verdict == v for t in judged) for v in (CORRECT, UNSURE, WRONG)}
    secs = sorted(t.seconds for t in traces) or [0.0]
    out.append("")
    out.append(
        f"correct {counts[CORRECT]}/{len(judged)}  unsure {counts[UNSURE]}  wrong {counts[WRONG]}"
        f"  cites a source {sum(t.cites for t in judged)}/{len(judged)}"
        f"  median {secs[len(secs) // 2]}s  slowest {secs[-1]}s"
    )
    for lang in ("en", "es", "he"):
        some = [t for t in judged if t.lang == lang]
        if some:
            out.append(f"  {lang}: {sum(t.verdict == CORRECT for t in some)}/{len(some)}")
    return "\n".join(out)


async def run(only: str = "", repeat: int = 1, parallel: int = 1) -> list[Trace]:
    from luach.agent import mail_evals

    search_url = os.environ.get("LUACH_SEARCH_URL", "")
    user_id = mail_evals._isolate()
    # _isolate turns search off for the scan's evals; these are about search.
    os.environ["LUACH_SEARCH_URL"] = search_url
    if not search_url:
        raise SystemExit("LUACH_SEARCH_URL is not set: these cases are about web search")
    _record()
    today = fetch_today()
    picked = [q for q in QUESTIONS if only in q.name] * repeat
    gate = asyncio.Semaphore(max(1, parallel))

    async def one(q: Question) -> Trace:
        async with gate:
            return await run_case(q, user_id, today)

    traces = list(await asyncio.gather(*(one(q) for q in picked)))
    print(report(traces))
    return traces


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", default="", help="run the cases whose name contains this")
    parser.add_argument("--repeat", type=int, default=1, help="run each case this many times")
    parser.add_argument("--parallel", type=int, default=1, help="cases in flight at once")
    parser.add_argument("--json", default="", help="write every trajectory to this file")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    traces = asyncio.run(run(args.only, args.repeat, args.parallel))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump([asdict(t) for t in traces], f, ensure_ascii=False, indent=1)
    judged = [t for t in traces if t.verdict]
    return 0 if judged and all(t.verdict != WRONG for t in judged) else 1


if __name__ == "__main__":
    sys.exit(main())

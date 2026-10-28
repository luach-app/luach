"""The web eval's scorers: what counts as a right, an unsure and a wrong answer.

Every reply here is one a real model gave on 28 October 2026."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from luach.agent import web_evals as w

TODAY = w.Today(
    day=date(2026, 10, 28),
    weather={"high_c": 18.8, "low_c": 5.0, "high_f": 65.8, "low_f": 41.0, "rain": 2.0},
    candles=datetime(2026, 10, 30, 17, 36, tzinfo=ZoneInfo(w.TZ)),
    chanukah=date(2026, 12, 4),
    clocks=date(2026, 11, 1),
)
Q = {q.name: q for q in w.QUESTIONS}


@pytest.mark.parametrize(
    "name, reply, verdict",
    [
        ("chelsea_weekend", "Saturday, October 31 at 8:30 AM Eastern Time (12:30 PM UK time).",
         w.CORRECT),
        ("chelsea_weekend", "Saturday 31 Oct at 12:30 UK time (8:30 AM your time).", w.CORRECT),
        # The right kick-off and a wrong conversion is a wrong answer.
        ("chelsea_weekend", "Saturday 31 Oct at 12:30 UK time (7:30 AM your time).", w.WRONG),
        ("chelsea_weekend", "October 31, at 8:30 AM UK time (3:30 AM your time).", w.WRONG),
        ("chelsea_weekend", "Saturday, October 31 at 12:30 at Stamford Bridge.", w.WRONG),
        ("real_madrid_weekend", "domingo 1 de noviembre contra el Racing a las 16:15 hora de "
         "España (10:15 en tu hora local).", w.CORRECT),
        ("real_madrid_weekend", "contra el Racing a las 16:15 hora de España (11:15 en tu hora).",
         w.WRONG),
        ("real_madrid_weekend", "contra el Racing Santander, a las 10:15 AM hora de España.",
         w.WRONG),
        ("real_madrid_weekend", "contra el Racing el 31 de octubre o el 1 de noviembre. Aún no "
         "han confirmado la hora.", w.UNSURE),
        ("met_wednesday", "Your calendar is clear, but The Met is closed on Wednesdays.", w.CORRECT),
        ("met_wednesday", "Yes, you're free today. What time were you thinking?", w.WRONG),
        ("pharmacy_sunday", "Which pharmacy do you mean, and where is it?", w.CORRECT),
        ("pharmacy_sunday", "Most CVS and Walgreens close at 6:00pm on Sundays.", w.WRONG),
        ("candles_friday", "כניסת שבת ביום שישי 30 באוקטובר בניו יורק היא ב-5:36 בערב.", w.CORRECT),
        ("candles_friday", "כניסת שבת היא ב-17:58.", w.WRONG),
        ("chanukah", "חנוכה מתחיל בערב יום שישי, 4 בדצמבר, ומסתיים ב-12 בדצמבר.", w.CORRECT),
        ("weather_he", "אחר הצהריים 19, ערב 17 ולילה 15. לחות 64-80%.", w.CORRECT),
        ("weather_he", "בין 60° ל-73° מעלות צלזיוס ביום, ו-48° עד 57° בלילה.", w.WRONG),
        ("weather_tomorrow_en", "highs around 75°F and lows near 61°F.", w.WRONG),
        ("weather_tomorrow_en", "a high of 66°F (19°C) and a low of 41°F (5°C).", w.CORRECT),
        ("lluvia_manana", "No, no se espera lluvia mañana en Nueva York.", w.CORRECT),
        ("clocks_back", "Clocks fall back on Sunday, November 1, 2026, at 2:00 a.m.", w.CORRECT),
        ("escuelas_noviembre", "11 de noviembre: Veterans Day, sin clases - 26 y 27 de "
         "noviembre: Thanksgiving Recess", w.CORRECT),
        ("escuelas_noviembre", "Miércoles 4 de noviembre: Día de Acción de Gracias - 11 de "
         "noviembre: Veteranos - 26 de noviembre", w.WRONG),
        ("seleccion_argentina", "Según ESPN: Uruguay, viernes 13 de noviembre.", w.CORRECT),
        ("seleccion_argentina", "16 de junio: Argentina vs Argelia (Kansas City)", w.WRONG),
    ],
)  # fmt: skip
def test_a_reply_is_scored_by_the_fact_it_holds(name, reply, verdict):
    assert w.verdict(Q[name], reply, TODAY) == verdict


def test_a_fact_about_one_week_is_checked_for_shape_once_it_is_stale():
    """After the weekend it was about, any day-and-time answer said plainly passes,
    and a hedge does not."""
    later = w.Today(day=date(2026, 12, 1))
    q = Q["chelsea_weekend"]
    assert w.verdict(q, "Saturday 5 December at 3pm against Arsenal.", later) == w.CORRECT
    assert w.verdict(q, "I couldn't find their next fixture.", later) == w.UNSURE


def test_a_case_whose_source_did_not_answer_is_skipped():
    assert w.verdict(Q["weather_he"], "19 מעלות", w.Today(day=date(2026, 10, 28))) is None


def test_the_next_clock_change_comes_from_the_timezone_database():
    now = datetime(2026, 10, 28, 9, 0, tzinfo=ZoneInfo(w.TZ))
    assert w.next_clock_change(now) == date(2026, 11, 1)
    assert w.next_clock_change(datetime(2026, 11, 2, tzinfo=ZoneInfo(w.TZ))) == date(2027, 3, 14)


def test_clock_times_are_read_both_ways_when_the_reply_does_not_say():
    assert 17 * 60 + 36 in w.clock_minutes("ב-5:36 בערב")
    assert w.clock_minutes("at 8:30 PM") == [20 * 60 + 30]
    assert w.clock_minutes("November 1") == []

"""The work calendar luach cannot read, only see the shape of."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from luach import booking, busy, db
from luach.calendar import times

TZ = "America/New_York"

#: Hosts these tests treat as public without asking DNS.
_PUBLIC_HOSTS = ("example.com", "outlook.office365.com")


@pytest.fixture(autouse=True)
def _no_dns(monkeypatch):
    from urllib.parse import urlsplit

    real = busy._not_public

    def judged(url: str) -> str | None:
        host = urlsplit(url).hostname or ""
        return None if host.endswith(_PUBLIC_HOSTS) else real(url)

    monkeypatch.setattr(busy, "_not_public", judged)


def _ics(*events: str) -> bytes:
    body = "\r\n".join(
        ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//test//EN", *events, "END:VCALENDAR"]
    )
    return body.encode()


def _event(uid: str, start: datetime, end: datetime, extra: str = "") -> str:
    fmt = "%Y%m%dT%H%M%SZ"
    # A recurring event is anchored in its own zone, as every real calendar writes it: in UTC a
    # weekly 14:00 moves to 13:00 the week New York's clocks change, and the test failed that week.
    when = (
        [
            f"DTSTART;TZID={TZ}:{start.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND;TZID={TZ}:{end.strftime('%Y%m%dT%H%M%S')}",
        ]
        if "RRULE" in extra
        else [
            f"DTSTART:{start.astimezone(UTC).strftime(fmt)}",
            f"DTEND:{end.astimezone(UTC).strftime(fmt)}",
        ]
    )
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{datetime.now(UTC).strftime(fmt)}",
        *when,
        "SUMMARY:Quarterly planning review with Acme leadership",
    ]
    if extra:
        lines.append(extra)
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def _weekday_ahead(days: int = 3):
    day = times.now_in(TZ).date() + timedelta(days=days)
    while day.weekday() > 4:
        day += timedelta(days=1)
    return day


def _at(day, hour: int) -> datetime:
    return datetime.combine(day, datetime.min.time(), tzinfo=times.zone(TZ)).replace(hour=hour)


def test_a_feed_becomes_busy_spans_with_recurrence_expanded():
    day = _weekday_ahead(2)
    raw = _ics(
        _event("one", _at(day, 10), _at(day, 11)),
        _event("weekly", _at(day, 14), _at(day, 15), "RRULE:FREQ=WEEKLY;COUNT=3"),
        _event("cancelled", _at(day, 16), _at(day, 17), "STATUS:CANCELLED"),
        _event("free", _at(day, 8), _at(day, 9), "TRANSP:TRANSPARENT"),
        "\r\n".join(
            [
                "BEGIN:VEVENT",
                "UID:allday",
                "DTSTAMP:20260101T000000Z",
                f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
                f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}",
                "SUMMARY:Company holiday",
                "END:VEVENT",
            ]
        ),
    )
    blocks = busy.parse_blocks(raw)
    starts = {b.start.astimezone(times.zone(TZ)).strftime("%Y-%m-%d %H:%M") for b in blocks}
    assert f"{day} 10:00" in starts
    assert f"{day} 14:00" in starts  # the weekly one, this week
    assert len([b for b in blocks if b.start.astimezone(times.zone(TZ)).hour == 14]) == 3
    assert f"{day} 16:00" not in starts  # cancelled
    assert f"{day} 08:00" not in starts  # marked free by its owner
    assert not any(b.end - b.start > timedelta(hours=12) for b in blocks)  # no all-day


def test_the_booking_page_will_not_offer_a_slot_that_is_a_work_meeting(calendar, monkeypatch):
    from luach.auth import users

    users.update_profile(1, timezone=TZ)
    day = _weekday_ahead(4)
    raw = _ics(_event("mtg", _at(day, 10), _at(day, 11)))
    monkeypatch.setattr(busy, "fetch_feed", lambda url: raw)
    busy.add_source(1, "Acme", "https://outlook.office365.com/owa/calendar/x/reachcalendar.ics")

    booking.update(
        1,
        {
            "enabled": True,
            "slug": "robin",
            "slot_minutes": 30,
            "buffer_minutes": 0,
            "hours": {d: [["09:00", "12:00"]] for d in ("mon", "tue", "wed", "thu", "fri")},
        },
    )
    offered = [
        s["start"][11:16]
        for d in booking.slots_for(1)
        if d["day"] == day.isoformat()
        for s in d["slots"]
    ]
    assert "09:00" in offered and "09:30" in offered
    assert "10:00" not in offered and "10:30" not in offered  # the Acme meeting
    assert "11:00" in offered

    # And the page a stranger reads says the same.
    page = booking.public_view("robin")
    shown = [
        s["start"][11:16] for d in page["days"] if d["day"] == day.isoformat() for s in d["slots"]
    ]
    assert "10:00" not in shown


def test_the_agenda_shows_that_the_time_is_taken_but_not_by_what(monkeypatch):
    day = _weekday_ahead(3)
    raw = _ics(_event("mtg", _at(day, 10), _at(day, 11)))
    monkeypatch.setattr(busy, "fetch_feed", lambda url: raw)
    busy.add_source(1, "Acme", "https://example.com/work.ics")
    start, end = times.day_bounds(day.isoformat(), TZ)
    shown = busy.as_events(1, start, end, TZ)
    assert len(shown) == 1
    only = shown[0]
    assert only["title"] == "Busy" and only["read_only"] is True
    assert "Acme" not in str(only) and "Quarterly" not in str(only)
    assert only["start"][11:16] == "10:00" and only["end"][11:16] == "11:00"

    # Hidden from the agenda on request, still counted for bookings.
    source_id = busy.sources_for(1)[0]["id"]
    busy.update_source(1, source_id, show_in_agenda=False)
    assert busy.as_events(1, start, end, TZ) == []
    assert busy.busy_spans(1, day, TZ) != []


def test_a_feed_that_cannot_be_read_keeps_the_last_answer(monkeypatch):
    day = _weekday_ahead(5)
    raw = _ics(_event("mtg", _at(day, 10), _at(day, 11)))
    monkeypatch.setattr(busy, "fetch_feed", lambda url: raw)
    busy.add_source(1, "Acme", "https://example.com/work.ics")
    assert busy.sources_for(1)[0]["blocks"] == 1

    def broken(url):
        raise TimeoutError("their server is having a day")

    monkeypatch.setattr(busy, "fetch_feed", broken)
    assert busy.refresh_for(1) == 0
    source = busy.sources_for(1)[0]
    assert source["last_error"] == "the feed could not be read"
    assert busy.busy_spans(1, day, TZ) != []  # yesterday's answer still stands


def test_feeds_belong_to_the_member_who_added_them(monkeypatch):
    monkeypatch.setattr(busy, "fetch_feed", lambda url: _ics())
    busy.add_source(1, "Acme", "https://example.com/work.ics")
    source_id = busy.sources_for(1)[0]["id"]
    assert busy.sources_for(2) == []
    for call in (
        lambda: busy.update_source(2, source_id, enabled=False),
        lambda: busy.remove_source(2, source_id),
    ):
        with pytest.raises(ValueError, match="not yours"):
            call()
    with pytest.raises(ValueError, match="not a calendar feed"):
        busy.add_source(1, "x", "ftp://nope")
    for i in range(busy.MAX_SOURCES - 1):
        busy.add_source(1, f"n{i}", f"https://example.com/{i}.ics")
    with pytest.raises(ValueError, match="at most"):
        busy.add_source(1, "one too many", "https://example.com/z.ics")
    busy.remove_source(1, source_id)
    with db.session() as s:
        from sqlalchemy import select

        left = (
            s.execute(select(db.BusyBlock).where(db.BusyBlock.source_id == source_id))
            .scalars()
            .all()
        )
    assert left == []


async def test_the_routes_manage_the_feeds(monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from luach.app import create_app

    monkeypatch.setattr(busy, "fetch_feed", lambda url: _ics())
    app = create_app(static_dir="/nonexistent")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        assert (await c.get("/api/busy")).status_code == 401
        await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        r = await c.post("/api/busy", json={"name": "Acme", "url": "https://example.com/w.ics"})
        assert r.status_code == 200 and r.json()["sources"][0]["name"] == "Acme"
        sid = r.json()["sources"][0]["id"]
        assert (await c.post("/api/busy", json={"url": "nope"})).status_code == 400
        r = await c.patch(f"/api/busy/{sid}", json={"show_in_agenda": False})
        assert r.json()["sources"][0]["show_in_agenda"] is False
        assert (await c.post("/api/busy/refresh")).json()["read"] == 1
        assert (await c.delete(f"/api/busy/{sid}")).json()["sources"] == []
        assert (await c.delete(f"/api/busy/{sid}")).status_code == 404


# --- a feed is fetched from the public internet only (SSRF) ------------------------


@pytest.fixture
def local_server():
    """A web server on this machine: what luach's own network looks like from inside."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen: list[str] = []
    routes: dict[str, tuple[int, dict[str, str], bytes]] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append(self.path)
            status, headers, body = routes.get(self.path, (404, {}, b"no"))
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", routes, seen
    server.shutdown()


def _pretend_local_is_public(monkeypatch, base: str) -> None:
    """The address check passes this server's URL, and the connection check its socket:
    what a public feed would look like, so the rest of the fetch can be tested."""
    real = busy._not_public
    monkeypatch.setattr(
        busy, "_not_public", lambda url: None if url.startswith(base) else real(url)
    )
    monkeypatch.setattr(busy, "_public_peer", lambda sock: None)


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:5432/",
        "http://10.42.0.7/metrics",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]:8004/api/health",
        "https://localhost/feed.ics",
        "webcal://192.168.1.1/cal.ics",
    ],
)
def test_a_feed_at_an_internal_address_is_refused(url):
    with pytest.raises(ValueError, match="public"):
        busy.add_source(1, "Work", url)
    assert busy.sources_for(1) == []
    with pytest.raises(busy.FeedRefused, match="public internet"):
        busy.fetch_feed(busy._norm(url))


def test_a_redirect_to_an_internal_address_is_not_followed(local_server, monkeypatch):
    base, routes, seen = local_server
    _pretend_local_is_public(monkeypatch, base)
    routes["/feed.ics"] = (302, {"Location": "http://10.42.0.7/secret"}, b"")
    with pytest.raises(busy.FeedRefused, match="public internet"):
        busy.fetch_feed(f"{base}/feed.ics")
    # A public redirect is followed, checked like the first.
    day = _weekday_ahead(4)
    routes["/moved.ics"] = (301, {"Location": "/feed2.ics"}, b"")
    routes["/feed2.ics"] = (200, {}, _ics(_event("m", _at(day, 9), _at(day, 10))))
    assert b"BEGIN:VCALENDAR" in busy.fetch_feed(f"{base}/moved.ics")
    routes["/loop.ics"] = (302, {"Location": "/loop.ics"}, b"")
    with pytest.raises(busy.FeedRefused, match="redirecting"):
        busy.fetch_feed(f"{base}/loop.ics")


def test_a_name_that_resolves_inside_by_the_time_of_connecting_is_refused(
    local_server, monkeypatch
):
    """DNS rebinding: the name passed the check, then pointed inside. The address actually
    connected to is checked too, before a request is sent."""
    base, routes, seen = local_server
    routes["/feed.ics"] = (200, {}, _ics())
    monkeypatch.setattr(busy, "_not_public", lambda url: None)  # the check was fooled
    with pytest.raises(busy.FeedRefused, match="public internet"):
        busy.fetch_feed(f"{base}/feed.ics")
    assert seen == [], "nothing was asked of the internal server"


def test_what_a_feed_said_is_never_stored_or_shown(local_server, monkeypatch):
    base, routes, seen = local_server
    _pretend_local_is_public(monkeypatch, base)
    secret = b"internal-admin-token=abc123 do not share\nBEGIN:VCALENDAR"
    routes["/page"] = (200, {}, secret)
    routes["/down"] = (503, {}, b"internal-admin-token=abc123")
    with db.session() as s:
        s.add(db.BusySource(user_id=1, name="Work", url=f"{base}/page", enabled=True))
        s.add(db.BusySource(user_id=1, name="Other", url=f"{base}/down", enabled=True))
    assert busy.refresh_for(1) == 0
    errors = {src["name"]: src["last_error"] for src in busy.sources_for(1)}
    assert errors == {
        "Work": "that is not a calendar feed",
        "Other": "the feed answered HTTP 503",
    }
    assert "abc123" not in str(busy.sources_for(1))


def test_a_rule_that_repeats_every_second_is_not_expanded_for_six_months():
    import time

    start = datetime.now(UTC) + timedelta(hours=1)
    raw = _ics(
        "\r\n".join(
            [
                "BEGIN:VEVENT",
                "UID:flood",
                f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
                f"DTEND:{(start + timedelta(seconds=1)).strftime('%Y%m%dT%H%M%SZ')}",
                "RRULE:FREQ=SECONDLY",
                "END:VEVENT",
            ]
        )
    )
    began = time.monotonic()
    with pytest.raises(busy.FeedRefused, match="more events"):
        busy.parse_blocks(raw)
    assert time.monotonic() - began < 30

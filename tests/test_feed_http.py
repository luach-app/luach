"""The calendar feed over HTTP: the member's switch, and the open link's defences."""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from luach import app as app_module
from luach import db, feed
from luach.app import create_app
from luach.auth import throttle, users
from luach.calendar import client, times
from luach.calendar.client import Draft
from luach.routes import feed as feed_routes

KEY = "svc-0123456789abcdef0123456789abcdef"
FEED_URL = re.compile(r"https://luach\.test/feed/([A-Za-z0-9_-]{43})\.ics")


def _app(tmp_path) -> Any:
    static = tmp_path / "web"
    (static / "assets").mkdir(parents=True, exist_ok=True)
    # The single-page app is mounted, as in production: nothing under /feed/ may fall
    # through to it either.
    (static / "index.html").write_text("<!doctype html><title>luach</title>")
    return create_app(static_dir=static)


@pytest.fixture
def app(tmp_path) -> Any:
    return _app(tmp_path)


@pytest.fixture
async def http(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


@pytest.fixture
async def phone(app):
    """The phone's calendar app: no session, no cookies of its own."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


async def login(c: AsyncClient, username: str = "robin", password: str = "correct horse battery"):
    r = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


async def turned_on(http: AsyncClient, scope: str = "household") -> str:
    await login(http)
    r = await http.post("/api/feed", json={"scope": scope})
    assert r.status_code == 200, r.text
    m = FEED_URL.fullmatch(r.json()["url"])
    assert m is not None
    return m.group(1)


def _event(title: str = "Dentist", days: int = 2) -> None:
    tz = "America/New_York"
    day = (times.now_in(tz) + timedelta(days=days)).date().isoformat()
    client.get_calendar().insert(Draft(title=title, span=times.span(f"{day}T15:00", None, tz)), tz)


async def raw(app: Any, path: str, method: str = "GET", headers: list | None = None) -> tuple:
    """A request with its path exactly as given: no client tidies ``..`` away first."""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"luach.test"), *(headers or [])],
        "client": ("203.0.113.9", 5000),
        "server": ("luach.test", 80),
    }
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], body


class TestTheSwitch:
    async def test_off_until_the_member_turns_it_on(self, http):
        await login(http)
        assert (await http.get("/api/feed")).json() == {
            "enabled": False,
            "scope": "household",
            "created_at": None,
            "last_read": None,
        }

    async def test_turned_on_the_link_is_shown_once_and_only_its_hash_is_kept(self, http):
        await login(http)
        got = (await http.post("/api/feed", json={})).json()
        token = FEED_URL.fullmatch(got["url"]).group(1)  # type: ignore[union-attr]
        assert got["webcal"] == f"webcal://luach.test/feed/{token}.ics"
        assert got["enabled"] is True and got["scope"] == "household"
        with db.session() as s:
            row = s.execute(select(db.CalendarFeed)).scalar_one()
            assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
            assert token not in repr(vars(row))
        # Never again: the status says it is on, not what the link is.
        assert token not in (await http.get("/api/feed")).text

    async def test_the_token_is_32_random_bytes(self, http):
        token = await turned_on(http)
        assert len(token) == 43
        import base64

        assert len(base64.urlsafe_b64decode(token + "=")) == 32

    async def test_a_second_turn_on_does_not_quietly_break_the_first_link(self, http, phone):
        token = await turned_on(http)
        assert (await http.post("/api/feed", json={})).status_code == 409
        assert (await phone.get(f"/feed/{token}.ics")).status_code == 200

    async def test_reset_kills_the_old_link_and_keeps_what_it_holds(self, http, phone):
        old = await turned_on(http, "mine")
        r = await http.post("/api/feed/reset")
        assert r.status_code == 200 and r.json()["scope"] == "mine"
        new = FEED_URL.fullmatch(r.json()["url"]).group(1)  # type: ignore[union-attr]
        assert new != old
        assert (await phone.get(f"/feed/{old}.ics")).status_code == 404
        assert (await phone.get(f"/feed/{new}.ics")).status_code == 200

    async def test_turned_off_the_link_is_dead(self, http, phone):
        token = await turned_on(http)
        r = await http.delete("/api/feed")
        assert r.status_code == 200 and r.json()["enabled"] is False
        assert (await phone.get(f"/feed/{token}.ics")).status_code == 404
        assert (await http.post("/api/feed/reset")).status_code == 404

    async def test_what_it_holds_changes_on_the_same_link(self, http, phone):
        token = await turned_on(http)
        assert (await http.patch("/api/feed", json={"scope": "mine"})).json()["scope"] == "mine"
        assert (await http.patch("/api/feed", json={"scope": "all"})).status_code == 400
        assert (await http.post("/api/feed/reset")).status_code == 200
        assert (await phone.get(f"/feed/{token}.ics")).status_code == 404

    async def test_each_member_has_their_own(self, http, phone):
        robin = await turned_on(http)
        await login(http, "ana", "another good password")
        assert (await http.get("/api/feed")).json()["enabled"] is False
        await http.delete("/api/feed")  # ana's, which is off: robin's stays
        assert (await phone.get(f"/feed/{robin}.ics")).status_code == 200

    async def test_signed_out_it_is_closed(self, phone):
        assert (await phone.get("/api/feed")).status_code == 401
        assert (await phone.post("/api/feed", json={})).status_code == 401

    async def test_a_service_key_cannot_make_a_link(self, app, monkeypatch):
        monkeypatch.setenv("LUACH_API_KEY", KEY)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://luach.test"
        ) as svc:
            headers = {"x-luach-key": KEY}
            assert (await svc.get("/api/feed", headers=headers)).status_code == 200
            for method, path in (
                ("POST", "/api/feed"),
                ("POST", "/api/feed/reset"),
                ("PATCH", "/api/feed"),
                ("DELETE", "/api/feed"),
            ):
                r = await svc.request(method, path, headers=headers, json={"scope": "mine"})
                assert r.status_code == 403, (method, path)


class TestTheLink:
    async def test_it_serves_the_calendar(self, http, phone):
        _event("Dentist")
        token = await turned_on(http)
        r = await phone.get(f"/feed/{token}.ics")
        assert r.status_code == 200
        assert r.headers["content-type"] == "text/calendar; charset=utf-8"
        assert r.headers["cache-control"] == "private, max-age=600"
        assert r.text.startswith("BEGIN:VCALENDAR") and "SUMMARY:Dentist" in r.text
        assert "set-cookie" not in r.headers
        assert (await phone.head(f"/feed/{token}.ics")).status_code == 200

    async def test_a_cookie_sent_along_is_ignored_and_none_is_set(self, http):
        token = await turned_on(http)
        r = await http.get(f"/feed/{token}.ics")  # http carries robin's session
        assert r.status_code == 200 and "set-cookie" not in r.headers

    async def test_unchanged_it_answers_304(self, http, phone):
        _event()
        token = await turned_on(http)
        first = await phone.get(f"/feed/{token}.ics")
        tag = first.headers["etag"]
        again = await phone.get(f"/feed/{token}.ics", headers={"If-None-Match": tag})
        assert again.status_code == 304 and again.content == b""
        assert again.headers["etag"] == tag
        weak = await phone.get(f"/feed/{token}.ics", headers={"If-None-Match": f"W/{tag}"})
        assert weak.status_code == 304
        _event("Something new", days=3)
        changed = await phone.get(f"/feed/{token}.ics", headers={"If-None-Match": tag})
        assert changed.status_code == 200 and changed.headers["etag"] != tag

    async def test_reading_it_is_noted_for_the_member(self, http, phone):
        token = await turned_on(http)
        assert (await http.get("/api/feed")).json()["last_read"] is None
        await phone.get(f"/feed/{token}.ics")
        assert (await http.get("/api/feed")).json()["last_read"] is not None

    async def test_it_is_only_read(self, http, phone):
        token = await turned_on(http)
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            assert (await phone.request(method, f"/feed/{token}.ics")).status_code == 405

    async def test_a_calendar_that_cannot_be_read_is_a_503_not_a_stack(
        self, http, phone, monkeypatch
    ):
        token = await turned_on(http)

        def broken(*a: Any, **k: Any) -> Any:
            raise RuntimeError("google is down")

        monkeypatch.setattr(client.FakeCalendar, "list_events", broken)
        r = await phone.get(f"/feed/{token}.ics")
        assert r.status_code == 503 and r.headers["retry-after"] == "300"
        assert "google" not in r.text


class TestNoWayIn:
    async def test_a_wrong_token_opens_nothing(self, http, phone):
        token = await turned_on(http)
        near = token[:-1] + ("A" if token[-1] != "A" else "B")
        for path in (f"/feed/{near}.ics", f"/feed/{'x' * 43}.ics", "/feed/short.ics"):
            r = await phone.get(path)
            assert r.status_code == 404, path
            assert r.json() in (feed_routes.NOT_FOUND, {"error": "no such route"})

    async def test_revoked_wrong_and_gone_look_the_same(self, http, phone):
        """One answer whatever the reason: a guess learns nothing about which links were."""
        token = await turned_on(http)
        unknown = await phone.get(f"/feed/{'A' * 43}.ics")
        await http.delete("/api/feed")
        revoked = await phone.get(f"/feed/{token}.ics")
        assert (revoked.status_code, revoked.content) == (unknown.status_code, unknown.content)

    async def test_a_removed_member_s_link_is_dead(self, http, phone):
        await login(http, "ana", "another good password")
        token = FEED_URL.fullmatch(  # type: ignore[union-attr]
            (await http.post("/api/feed", json={})).json()["url"]
        ).group(1)
        assert (await phone.get(f"/feed/{token}.ics")).status_code == 200
        ana = users.member_by_username("ana")
        assert ana is not None and users.remove(ana.id)
        assert (await phone.get(f"/feed/{token}.ics")).status_code == 404
        with db.session() as s:
            assert s.execute(select(db.CalendarFeed)).first() is None

    def test_a_feed_whose_account_is_gone_is_refused_even_if_its_row_stayed(self, monkeypatch):
        """Belt and braces: the row goes with the account, and a lookup checks anyway."""
        token = feed.turn_on(users.member_by_username("ana").id)  # type: ignore[union-attr]
        real_get = db.Session.get

        def no_users(self: Any, entity: Any, ident: Any, **kw: Any) -> Any:
            return None if entity is db.User else real_get(self, entity, ident, **kw)

        monkeypatch.setattr(db.Session, "get", no_users)
        assert feed.lookup(token) is None

    def test_the_lookup_is_by_hash_and_compared_in_constant_time(self, monkeypatch):
        token = feed.turn_on(users.member_by_username("robin").id)  # type: ignore[union-attr]
        compared: list[tuple[bytes, bytes]] = []
        real = feed.hmac.compare_digest

        def spy(a: Any, b: Any) -> bool:
            compared.append((a, b))
            return real(a, b)

        monkeypatch.setattr(feed.hmac, "compare_digest", spy)
        assert feed.lookup(token) is not None
        digest = hashlib.sha256(token.encode()).hexdigest().encode()
        assert compared == [(digest, digest)]
        # The token itself is never what is compared or stored.
        assert all(token.encode() not in pair for pair in compared)
        assert feed.lookup(token[:-1] + ("A" if token[-1] != "A" else "B")) is None
        assert feed.lookup(token + "A") is None and feed.lookup("") is None

    @pytest.mark.parametrize(
        "path",
        [
            "/feed/{t}.ics/../api/members",
            "/feed/{t}.ics/../../api/family",
            "/feed/../api/members",
            "/feed/{t}.ics/",
            "/feed/{t}.icsx",
            "/feed/{t}.ics.ics",
            "/feed//{t}.ics",
            "/feed/{t}",
            "/feed/",
            "/feed/{t}.ics%2F..%2Fapi%2Fmembers",
            "/feed/{t}.ics\x00",
            "/feed/../index.html",
        ],
    )
    async def test_the_open_path_opens_nothing_else(self, app, http, path):
        token = await turned_on(http)
        status, body = await raw(app, path.format(t=token))
        assert status == 404, path
        assert b"robin" not in body and b"<!doctype" not in body.lower()

    async def test_nothing_under_api_is_opened_by_it(self, http, phone):
        token = await turned_on(http)
        assert (await phone.get(f"/api/feed/{token}.ics")).status_code == 401
        assert "/feed" not in " ".join(app_module.OPEN_PATHS)


class TestRateLimits:
    async def test_guessing_is_refused_after_a_few(self, http, phone):
        token = await turned_on(http)
        for _ in range(feed_routes.MAX_MISSES):
            assert (await phone.get(f"/feed/{'A' * 43}.ics")).status_code == 404
        r = await phone.get(f"/feed/{'B' * 43}.ics")
        assert r.status_code == 429 and int(r.headers["retry-after"]) > 0
        # From that address, even the right link waits: a guesser cannot tell a hit.
        assert (await phone.get(f"/feed/{token}.ics")).status_code == 429

    async def test_one_link_read_too_often_is_refused(self, http, phone, monkeypatch):
        monkeypatch.setattr(feed_routes, "MAX_PER_LINK", 3)
        token = await turned_on(http)
        for _ in range(3):
            assert (await phone.get(f"/feed/{token}.ics")).status_code == 200
        assert (await phone.get(f"/feed/{token}.ics")).status_code == 429
        # Another member's link is not held up by it.
        await login(http, "ana", "another good password")
        other = FEED_URL.fullmatch(  # type: ignore[union-attr]
            (await http.post("/api/feed", json={})).json()["url"]
        ).group(1)
        assert (await phone.get(f"/feed/{other}.ics")).status_code == 200

    async def test_one_address_reading_too_often_is_refused(self, http, phone, monkeypatch):
        monkeypatch.setattr(feed_routes, "MAX_PER_ADDRESS", 2)
        token = await turned_on(http)
        for _ in range(2):
            assert (await phone.get(f"/feed/{token}.ics")).status_code == 200
        assert (await phone.get(f"/feed/{token}.ics")).status_code == 429
        throttle.reset_all()
        assert (await phone.get(f"/feed/{token}.ics")).status_code == 200


class TestTheAccessLog:
    @pytest.mark.parametrize(
        "path",
        [
            "/feed/{t}.ics",
            "/feed/{t}.ics?x=1",
            "/feed/{t}.ics/../api/members",
        ],
    )
    def test_the_token_never_reaches_the_log(self, path):
        token = "Zx9" + "a" * 40
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            __file__,
            1,
            '%s - "%s %s HTTP/%s" %d',
            ("203.0.113.9:5000", "GET", path.format(t=token), "1.1", 200),
            None,
        )
        app_module._NoSecretsInTheAccessLog().filter(record)
        line = record.getMessage()
        assert token not in line and "/feed/…" in line

    async def test_nor_does_a_failed_read(self, http, phone, monkeypatch, caplog):
        token = await turned_on(http)
        monkeypatch.setattr(
            client.FakeCalendar,
            "list_events",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")),
        )
        with caplog.at_level(logging.DEBUG):
            await phone.get(f"/feed/{token}.ics")
        # luach's own lines, with their tracebacks (the client's request line is httpx's).
        ours = [logging.Formatter().format(r) for r in caplog.records if r.name.startswith("luach")]
        assert ours and all(token not in line for line in ours)

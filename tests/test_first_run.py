"""A new household's first run: the calendar it gets, who becomes the owner, the time
zone members start in, what mail can and cannot do, and the sign-in throttle behind a
proxy."""

from __future__ import annotations

import logging

import pytest

from luach import config
from luach.app import create_app, lifespan
from luach.calendar import client as cal

# --- the calendar ------------------------------------------------------------


@pytest.fixture
def no_google(monkeypatch):
    for name in (
        "LUACH_GOOGLE_SA_KEY",
        "LUACH_GOOGLE_OAUTH_CLIENT",
        "LUACH_GOOGLE_OAUTH_TOKENS",
        "LUACH_CALENDAR_AUTH",
        "CREDENTIALS_DIRECTORY",
    ):
        monkeypatch.delenv(name, raising=False)
    cal.set_calendar(None)
    yield
    cal.set_calendar(cal.FakeCalendar())


def test_an_unset_calendar_is_the_local_one(monkeypatch, no_google):
    """It was Google, which with no credential became an in-memory calendar that forgot
    every event at the next restart."""
    monkeypatch.delenv("LUACH_CALENDAR", raising=False)
    assert config.calendar_backend() == "local" and config.calendar_problem() == ""
    assert isinstance(cal.get_calendar(), cal.LocalCalendar)


def test_google_without_a_credential_refuses_to_start(monkeypatch, no_google, tmp_path):
    monkeypatch.setenv("LUACH_CALENDAR", "google")
    problem = config.calendar_problem()
    assert "no Google credential" in problem and "LUACH_CALENDAR=local" in problem
    with pytest.raises(RuntimeError, match="no Google credential"):
        cal.get_calendar()


async def test_the_server_does_not_start_on_google_without_a_credential(
    monkeypatch, no_google, tmp_path, caplog
):
    monkeypatch.setenv("LUACH_CALENDAR", "google")
    monkeypatch.setenv("LUACH_GMAIL_POLL_MIN", "0")
    with pytest.raises(RuntimeError), caplog.at_level(logging.ERROR, "luach.app"):
        async with lifespan(create_app(static_dir=tmp_path / "nope")):
            pass  # pragma: no cover - never reached
    assert "luach cannot start" in caplog.text and "no Google credential" in caplog.text


def test_the_credential_must_be_the_one_calendar_auth_picks(monkeypatch, no_google, tmp_path):
    monkeypatch.setenv("LUACH_CALENDAR", "google")
    monkeypatch.setenv("LUACH_GOOGLE_SA_KEY", str(tmp_path / "sa.json"))
    assert config.calendar_problem() == ""
    monkeypatch.setenv("LUACH_CALENDAR_AUTH", "oauth")
    assert "LUACH_GOOGLE_OAUTH_CLIENT and LUACH_GOOGLE_OAUTH_TOKENS" in config.calendar_problem()
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_CLIENT", str(tmp_path / "c.json"))
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_TOKENS", str(tmp_path / "t.json"))
    assert config.calendar_problem() == ""
    monkeypatch.setenv("LUACH_CALENDAR_AUTH", "sa")
    monkeypatch.delenv("LUACH_GOOGLE_SA_KEY")
    assert "set LUACH_GOOGLE_SA_KEY" in config.calendar_problem()


def test_a_calendar_luach_does_not_know_is_refused(monkeypatch, no_google):
    monkeypatch.setenv("LUACH_CALENDAR", "Gogle")
    assert "'gogle' is not a calendar luach knows" in config.calendar_problem()
    with pytest.raises(RuntimeError):
        cal.get_calendar()


def test_fake_is_asked_for_by_name_and_says_it_forgets(monkeypatch, no_google, caplog):
    monkeypatch.setenv("LUACH_CALENDAR", "fake")
    with caplog.at_level(logging.WARNING, "luach.calendar.client"):
        assert isinstance(cal.get_calendar(), cal.FakeCalendar)
    assert "LOST when luach restarts" in caplog.text


@pytest.mark.parametrize(
    ("backend", "line"),
    [
        ("local", "calendar=local (luach's own database)"),
        ("fake", "calendar=fake (in memory, lost on restart)"),
        ("google", "calendar=google (family@group.calendar.google.com, sa)"),
    ],
)
async def test_the_startup_line_names_the_real_calendar(
    monkeypatch, no_google, tmp_path, caplog, backend, line
):
    """It printed the Google calendar id or "fake", so a local household read "fake"."""
    monkeypatch.setenv("LUACH_CALENDAR", backend)
    monkeypatch.setenv("LUACH_GMAIL_POLL_MIN", "0")
    if backend == "google":
        monkeypatch.setenv("LUACH_GOOGLE_SA_KEY", str(tmp_path / "sa.json"))
        monkeypatch.setenv("LUACH_GOOGLE_CALENDAR_ID", "family@group.calendar.google.com")
    with caplog.at_level(logging.INFO, "luach.app"):
        async with lifespan(create_app(static_dir=tmp_path / "nope")):
            pass
    assert line in caplog.text
    assert ("LOST when luach restarts" in caplog.text) == (backend == "fake")


# --- the first account ---------------------------------------------------------


@pytest.fixture
def fresh_setup(monkeypatch):
    from luach.auth import setup

    monkeypatch.delenv("LUACH_SETUP_CODE", raising=False)
    setup.reset()
    yield setup
    setup.reset()


@pytest.fixture
async def http(tmp_path):
    from httpx import ASGITransport, AsyncClient

    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


OWNER = {"username": "robin", "email": "robin@example.com", "password": "correct horse battery"}


async def test_a_new_server_prints_a_one_time_setup_code(
    emptied, fresh_setup, monkeypatch, tmp_path, caplog
):
    import re
    import stat

    monkeypatch.setenv("LUACH_GMAIL_POLL_MIN", "0")
    with caplog.at_level(logging.WARNING, "luach.auth.setup"):
        async with lifespan(create_app(static_dir=tmp_path / "nope")):
            pass
    code = fresh_setup.path().read_text().strip()
    assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}", code)
    assert stat.S_IMODE(fresh_setup.path().stat().st_mode) == 0o600
    assert code in caplog.text and "Set up the household" in caplog.text
    # A restart before anyone used it keeps the same code, so an older log line still works.
    fresh_setup.reset()
    async with lifespan(create_app(static_dir=tmp_path / "nope")):
        pass
    assert fresh_setup.path().read_text().strip() == code


async def test_the_owner_needs_the_setup_code(emptied, fresh_setup, http):
    code = fresh_setup.ensure()
    r = await http.post("/api/auth/register", json=OWNER)
    assert r.status_code == 403 and "setup code is required" in r.json()["error"]
    assert "docker compose logs luach" in r.json()["error"]
    r = await http.post("/api/auth/register", json={**OWNER, "setup_code": "AAAA-BBBB-CCCC"})
    assert r.status_code == 403 and "setup code is wrong" in r.json()["error"]
    assert (await http.get("/api/auth/status")).json()["users_exist"] is False
    # As typed: lower case, spaces for dashes.
    typed = code.lower().replace("-", " ")
    r = await http.post("/api/auth/register", json={**OWNER, "setup_code": typed})
    assert r.status_code == 200 and r.json()["is_owner"] is True
    # Spent: gone from the disk, and no use a second time.
    assert not fresh_setup.path().exists() and fresh_setup.current() == ""
    again = {**OWNER, "username": "mallory", "email": "m@example.com", "setup_code": code}
    r = await http.post("/api/auth/register", json=again)
    assert r.status_code == 403 and "owner already exists" in r.json()["error"]


async def test_a_register_before_any_code_was_made_makes_one(emptied, fresh_setup, http, caplog):
    """The code is made at startup; a server whose startup did not make one makes it on the
    first attempt, logs it, and still refuses that attempt."""
    with caplog.at_level(logging.WARNING, "luach.auth.setup"):
        r = await http.post("/api/auth/register", json={**OWNER, "setup_code": "guess"})
    assert r.status_code == 403
    assert fresh_setup.current() and fresh_setup.current() in caplog.text


async def test_guessing_the_setup_code_is_throttled(emptied, fresh_setup, http):
    fresh_setup.ensure()
    for _ in range(8):
        r = await http.post("/api/auth/register", json={**OWNER, "setup_code": "nope"})
        assert r.status_code == 403
    r = await http.post("/api/auth/register", json={**OWNER, "setup_code": fresh_setup.current()})
    assert r.status_code == 429


async def test_the_setup_code_can_be_pinned_for_automation(
    emptied, fresh_setup, monkeypatch, http, caplog
):
    monkeypatch.setenv("LUACH_SETUP_CODE", "ci-setup-code-0123456789")
    with caplog.at_level(logging.WARNING, "luach.auth.setup"):
        fresh_setup.ensure()
    assert "LUACH_SETUP_CODE" in caplog.text and "ci-setup-code" not in caplog.text
    assert not fresh_setup.path().exists(), "a pinned code is not written anywhere"
    r = await http.post(
        "/api/auth/register", json={**OWNER, "setup_code": "ci-setup-code-0123456789"}
    )
    assert r.status_code == 200 and r.json()["is_owner"] is True


async def test_a_server_with_accounts_never_makes_a_setup_code(
    fresh_setup, monkeypatch, tmp_path, caplog, http
):
    """Every running household: registration is closed, and nothing asks for a code."""
    monkeypatch.setenv("LUACH_GMAIL_POLL_MIN", "0")
    fresh_setup.path().write_text("LEFT-OVER-CODE\n")
    with caplog.at_level(logging.WARNING, "luach.auth.setup"):
        async with lifespan(create_app(static_dir=tmp_path / "nope")):
            pass
    assert "setup code" not in caplog.text and not fresh_setup.path().exists()
    r = await http.post("/api/auth/register", json={**OWNER, "setup_code": "LEFT-OVER-CODE"})
    assert r.status_code == 403 and "owner already exists" in r.json()["error"]


def test_two_first_accounts_at_once_make_one_owner(emptied, monkeypatch):
    """The check that no account exists and the insert used to be separate transactions:
    two registrations arriving together both found none and both became the owner."""
    import threading
    import time

    from luach import db
    from luach.auth import users

    slow = users._member

    def held_open(user, owner_id):  # the insert is made, the transaction not yet committed
        time.sleep(0.3)
        return slow(user, owner_id)

    monkeypatch.setattr(users, "_member", held_open)
    start = threading.Barrier(2)
    made: list[str] = []
    refused: list[str] = []

    def register(name: str) -> None:
        start.wait()
        try:
            users.create_user(name, f"{name}@example.com", "correct horse battery", first=True)
            made.append(name)
        except users.OwnerExists:
            refused.append(name)

    threads = [threading.Thread(target=register, args=(n,)) for n in ("robin", "mallory")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(made) == 1 and len(refused) == 1
    with db.session() as s:
        assert s.query(db.User).count() == 1


# --- the time zone a member starts in ----------------------------------------------


async def test_the_owner_starts_in_the_zone_their_browser_sent(emptied, fresh_setup, http):
    code = fresh_setup.ensure()
    body = {**OWNER, "setup_code": code, "timezone": "Mars/Olympus"}
    r = await http.post("/api/auth/register", json=body)
    assert r.status_code == 400 and "unknown timezone" in r.json()["error"]
    assert fresh_setup.current() == code, "a refused form does not spend the code"
    r = await http.post("/api/auth/register", json={**body, "timezone": "Europe/Madrid"})
    assert r.status_code == 200 and r.json()["timezone"] == "Europe/Madrid"


async def test_an_invited_member_starts_in_the_zone_they_sent(http):
    """/accept took no zone, so every invited member started in America/New_York."""
    await http.post(
        "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
    )
    token = (
        (await http.post("/api/members/invite", json={"email": "noa@example.com"}))
        .json()["link"]
        .split("?invite=")[1]
    )
    await http.post("/api/auth/logout")
    join = {"token": token, "username": "noa", "password": "a fine password"}
    r = await http.post("/api/auth/accept", json={**join, "timezone": "Not/AZone"})
    assert r.status_code == 400 and "unknown timezone" in r.json()["error"]
    r = await http.post("/api/auth/accept", json={**join, "timezone": "Asia/Jerusalem"})
    assert r.status_code == 200 and r.json()["timezone"] == "Asia/Jerusalem"
    assert (await http.get("/api/auth/me")).json()["timezone"] == "Asia/Jerusalem"


# --- outgoing mail that is not set up ------------------------------------------------


async def _owner(http) -> None:
    r = await http.post(
        "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
    )
    assert r.status_code == 200


async def test_the_sign_in_screen_learns_that_mail_is_off_and_the_way_round_it(http):
    mail = (await http.get("/api/auth/status")).json()["mail"]
    assert mail["enabled"] is False
    assert "does not send email" in mail["limitation"]
    assert "docker compose exec luach python -m luach.passwd" in mail["limitation"]
    assert mail["offline_reset"] == "docker compose exec luach python -m luach.passwd <username>"


async def test_mail_that_works_has_nothing_to_confess(http, monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setenv("LUACH_MAIL_FROM", "luach <calendar@example.com>")
    mail = (await http.get("/api/auth/status")).json()["mail"]
    assert mail["enabled"] is True and mail["limitation"] == ""


async def test_an_invite_says_mail_is_off_differently_from_a_send_that_failed(http, monkeypatch):
    from luach import mailer

    await _owner(http)
    r = (await http.post("/api/members/invite", json={"email": "a@example.com"})).json()
    assert r["sent"] is False and r["mail"] == "not_configured" and "?invite=" in r["link"]
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setattr(mailer, "send_invitation", lambda to, inviter, token: False)
    r = (await http.post("/api/members/invite", json={"email": "b@example.com"})).json()
    assert r["sent"] is False and r["mail"] == "failed" and "?invite=" in r["link"]


@pytest.mark.parametrize("app_url", ["", "http://localhost:8004"])
async def test_an_invite_link_follows_the_address_in_use_when_luach_does_not_know_its_own(
    http, monkeypatch, app_url
):
    """.env.example leaves LUACH_APP_URL at localhost, and the link built from it opened
    nothing on the invitee's phone."""
    monkeypatch.setenv("LUACH_APP_URL", app_url)
    await _owner(http)
    r = await http.post(
        "/api/members/invite",
        json={"email": "a@example.com"},
        headers={"origin": "https://calendar.example.com", "host": "calendar.example.com"},
    )
    data = r.json()
    assert data["link"].startswith("https://calendar.example.com/?invite=")
    assert "LUACH_APP_URL=https://calendar.example.com" in data["warning"]


async def test_an_invite_link_keeps_a_real_app_url_and_says_when_it_differs(http, monkeypatch):
    monkeypatch.setenv("LUACH_APP_URL", "https://calendar.example.com")
    await _owner(http)
    same = await http.post(
        "/api/members/invite",
        json={"email": "a@example.com"},
        headers={"origin": "https://calendar.example.com", "host": "calendar.example.com"},
    )
    assert same.json()["link"].startswith("https://calendar.example.com/?invite=")
    assert "warning" not in same.json()
    other = await http.post(
        "/api/members/invite",
        json={"email": "b@example.com"},
        headers={"origin": "http://192.168.1.20:8004", "host": "192.168.1.20:8004"},
    )
    assert other.json()["link"].startswith("https://calendar.example.com/?invite=")
    assert "http://192.168.1.20:8004" in other.json()["warning"]


async def test_trying_it_out_on_localhost_needs_no_warning(http, monkeypatch):
    monkeypatch.setenv("LUACH_APP_URL", "http://localhost:8004")
    await _owner(http)
    r = await http.post(
        "/api/members/invite",
        json={"email": "a@example.com"},
        headers={"origin": "http://localhost:8004", "host": "localhost:8004"},
    )
    assert r.json()["link"].startswith("http://localhost:8004/?invite=")
    assert "warning" not in r.json()


# --- a proxy luach does not trust, and the sign-in throttle -------------------------------


@pytest.fixture
def note_again():
    from luach.routes import shared

    shared.reset_forwarding_note()
    yield
    shared.reset_forwarding_note()


@pytest.fixture
async def via(tmp_path):
    """Clients whose connection comes from a given peer address, as uvicorn reports it."""
    from contextlib import asynccontextmanager

    from httpx import ASGITransport, AsyncClient

    app = create_app(static_dir=tmp_path / "nope")

    @asynccontextmanager
    async def connect(peer: str):
        transport = ASGITransport(app=app, client=(peer, 40000))
        async with AsyncClient(transport=transport, base_url="http://luach.test") as c:
            yield c

    return connect


async def test_a_proxy_luach_does_not_trust_is_named_in_the_log_once(via, note_again, caplog):
    """Compose behind a host proxy: everyone arrives from the Docker gateway, X-Forwarded-For
    is ignored, and the household shares one throttle key. Nothing said so."""
    async with via("172.18.0.1") as c:
        with caplog.at_level(logging.WARNING, "luach.routes.shared"):
            await c.get("/api/auth/status", headers={"x-forwarded-for": "203.0.113.9"})
            await c.get("/api/auth/status", headers={"x-forwarded-for": "203.0.113.10"})
    warnings = [r for r in caplog.records if "X-Forwarded-For" in r.getMessage()]
    assert len(warnings) == 1
    assert "LUACH_TRUSTED_PROXIES=127.0.0.1/32,::1/128,172.18.0.1/32" in warnings[0].getMessage()


@pytest.mark.parametrize(
    ("peer", "forwarded", "trusted"),
    [
        ("172.18.0.1", "203.0.113.9", "172.18.0.0/16"),  # the proxy is trusted
        ("93.184.216.34", "10.0.0.1", ""),  # a client on the internet making a header up
        ("192.168.1.20", "", ""),  # someone on the home network, no proxy
        ("192.168.1.20", "192.168.1.20, 172.18.0.1", ""),  # uvicorn took it from the header
    ],
)
async def test_nothing_is_said_when_there_is_no_untrusted_proxy(
    via, note_again, caplog, monkeypatch, peer, forwarded, trusted
):
    if trusted:
        monkeypatch.setenv("LUACH_TRUSTED_PROXIES", trusted)
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    async with via(peer) as c:
        with caplog.at_level(logging.WARNING, "luach.routes.shared"):
            await c.get("/api/auth/status", headers=headers)
    assert "X-Forwarded-For" not in caplog.text


async def test_behind_a_trusted_proxy_one_guesser_does_not_lock_the_member_out(via, monkeypatch):
    monkeypatch.setenv("LUACH_TRUSTED_PROXIES", "172.18.0.0/16")
    wrong = {"username": "ana", "password": "not it"}
    async with via("172.18.0.1") as c:
        for _ in range(8):
            r = await c.post(
                "/api/auth/login", json=wrong, headers={"x-forwarded-for": "198.51.100.1"}
            )
            assert r.status_code == 401
        r = await c.post("/api/auth/login", json=wrong, headers={"x-forwarded-for": "198.51.100.1"})
        assert r.status_code == 429
        r = await c.post(
            "/api/auth/login",
            json={"username": "ana", "password": "another good password"},
            headers={"x-forwarded-for": "198.51.100.2"},
        )
        assert r.status_code == 200


async def test_an_account_has_a_cap_across_addresses(via, monkeypatch):
    """Eight tries per address let a guesser with many addresses go on for ever."""
    from luach.auth import throttle

    monkeypatch.setenv("LUACH_TRUSTED_PROXIES", "172.18.0.0/16")
    wrong = {"username": "ana", "password": "not it"}
    async with via("172.18.0.1") as c:
        for n in range(throttle.ACCOUNT_MAX_ATTEMPTS):
            r = await c.post(
                "/api/auth/login",
                json=wrong,
                headers={"x-forwarded-for": f"198.51.100.{n // 4 + 1}"},
            )
            assert r.status_code == 401
        r = await c.post(
            "/api/auth/login",
            json={"username": "ana", "password": "another good password"},
            headers={"x-forwarded-for": "203.0.113.200"},
        )
        assert r.status_code == 429 and r.json()["retry_after"] > 0
        # Only that account: the others sign in as before.
        r = await c.post(
            "/api/auth/login",
            json={"username": "robin", "password": "correct horse battery"},
            headers={"x-forwarded-for": "203.0.113.200"},
        )
        assert r.status_code == 200


def test_the_throttle_forgets_keys_whose_attempts_expired(monkeypatch):
    from luach.auth import throttle

    clock = [1000.0]
    monkeypatch.setattr(throttle.time, "monotonic", lambda: clock[0])
    throttle.reset_all()
    for n in range(500):
        throttle.failed(f"book:page{n}", f"198.51.100.{n % 250}")
    throttle.account_failed("ana")
    assert throttle.size() == 501
    clock[0] += throttle.LOCKOUT_SECS + throttle.PRUNE_EVERY_SECS
    throttle.failed("robin", "203.0.113.1")
    assert throttle.size() == 1
    assert throttle.locked("robin", "203.0.113.1") == 0

"""The service key: never a placeholder or a short one, guessing at it is throttled, and
it reaches the calendar and its gate but not the household's keys."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from luach import app as app_module
from luach import config
from luach.app import create_app
from luach.auth import api_key, throttle

KEY = "svc-0123456789abcdef0123456789abcdef"
SERVICE = {"x-luach-key": KEY}


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LUACH_API_KEY", KEY)
    monkeypatch.delenv("LUACH_TULIP_KEY", raising=False)
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


@pytest.mark.parametrize(
    "value",
    [
        "replace-with-a-long-random-string",
        "replace-with-another-long-random-string",
        "REPLACE-WITH-A-LONG-RANDOM-STRING",
        "sekret",
        "0123456789abcdef0123456789abcde",  # 31
        "a" * 40,
        "ñ" * 40,
    ],
)
@pytest.mark.parametrize("name", ["LUACH_API_KEY", "LUACH_TULIP_KEY"])
def test_a_placeholder_or_short_key_refuses_to_start(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(config.WeakKey) as refused:
        config.check_service_keys()
    message = str(refused.value)
    assert name in message and "openssl rand -hex 32" in message
    assert value not in message  # the log never carries the value


async def test_startup_itself_refuses_a_weak_key(monkeypatch, tmp_path):
    monkeypatch.setenv("LUACH_API_KEY", "replace-with-a-long-random-string")
    app = create_app(static_dir=tmp_path / "nope")
    with pytest.raises(config.WeakKey):
        async with app_module.lifespan(app):
            pass


def test_a_good_key_or_none_starts(monkeypatch):
    monkeypatch.setenv("LUACH_API_KEY", KEY)
    monkeypatch.setenv("LUACH_TULIP_KEY", "tulip-" + "fedcba9876543210" * 2)
    config.check_service_keys()
    monkeypatch.delenv("LUACH_API_KEY")
    monkeypatch.delenv("LUACH_TULIP_KEY")
    config.check_service_keys()


async def test_a_weak_key_opens_nothing_even_if_startup_was_skipped(client, monkeypatch):
    for weak in ("replace-with-a-long-random-string", "sekret"):
        monkeypatch.setenv("LUACH_API_KEY", weak)
        assert not api_key.matches(weak)
        r = await client.get("/api/auth/me", headers={"x-luach-key": weak})
        assert r.status_code == 401


async def test_a_non_ascii_key_is_a_401_not_a_500(client):
    for raw in ("clé-ñ".encode(), b"\xff\xfe\xfd"):
        r = await client.get("/api/auth/me", headers=[(b"x-luach-key", raw)])
        assert r.status_code == 401, r.text


async def test_wrong_keys_are_throttled_per_address(client):
    for _ in range(throttle.MAX_ATTEMPTS):
        r = await client.get("/api/auth/me", headers={"x-luach-key": "x" * 40})
        assert r.status_code == 401
    # Locked out: even the right key waits, so a guess that lands is not told so.
    r = await client.get("/api/auth/me", headers=SERVICE)
    assert r.status_code == 429 and r.json()["retry_after"] > 0
    throttle.reset_all()
    assert (await client.get("/api/auth/me", headers=SERVICE)).status_code == 200


async def test_the_right_key_does_not_count_against_the_throttle(client):
    for _ in range(throttle.MAX_ATTEMPTS + 2):
        assert (await client.get("/api/auth/me", headers=SERVICE)).status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/members/invite"),
        ("DELETE", "/api/members/invite/x@example.com"),
        ("DELETE", "/api/members/2"),
        ("PATCH", "/api/auth/me"),
        ("POST", "/api/auth/password"),
        ("POST", "/api/auth/emails"),
        ("POST", "/api/auth/emails/primary"),
        ("DELETE", "/api/auth/emails/robin@example.com"),
        ("POST", "/api/auth/passkeys/register/options"),
        ("DELETE", "/api/auth/passkeys/1"),
        ("GET", "/api/mail/connect"),
        ("POST", "/api/mail/connect/app"),
        ("PATCH", "/api/mail/scan"),
        ("DELETE", "/api/mail"),
        ("POST", "/api/push/subscribe"),
        ("POST", "/api/push/unsubscribe"),
        ("POST", "/api/boards"),
        ("PATCH", "/api/boards/1"),
        ("DELETE", "/api/boards/1"),
    ],
)
async def test_the_service_key_cannot_touch_the_households_keys(client, method, path):
    r = await client.request(method, path, json={}, headers=SERVICE)
    assert r.status_code == 403, f"{method} {path} answered {r.status_code}"
    assert "service key" in r.json()["error"]


async def test_the_service_key_still_does_what_the_chat_bot_does(client):
    """scripts/luach-cli.sh, which the owner's chat bot runs: ask, agenda, pending,
    approve, deny, health. Reads of the rest stay open too."""
    for path in (
        "/api/auth/me",
        "/api/calendar/events?start=2026-01-01&end=2026-01-02",
        "/api/control/pending",
        "/api/health/details",
        "/api/members",
        "/api/mail",
        "/api/boards",
    ):
        r = await client.get(path, headers=SERVICE)
        assert r.status_code == 200, f"{path} answered {r.status_code}: {r.text}"
    for verb in ("approve", "deny"):
        r = await client.post(f"/api/control/pending/999/{verb}", headers=SERVICE)
        assert r.status_code == 404, r.text  # reached the route: there is no such hold

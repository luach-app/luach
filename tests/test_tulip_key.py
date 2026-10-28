"""Tulip's own key: it reads and talks to the agent, and it never approves."""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from luach import config
from luach.agent import control, runtime
from luach.app import create_app
from luach.auth import api_key
from luach.calendar import times
from tests.doubles import ScriptedModel, call, say

SERVICE_SEKRET = "service-0123456789abcdef0123456789abcdef"
TULIP_SEKRET = "tulip-0123456789abcdef0123456789abcdef"
TULIP = {"x-luach-key": TULIP_SEKRET}


@pytest.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LUACH_API_KEY", SERVICE_SEKRET)
    monkeypatch.setenv("LUACH_TULIP_KEY", TULIP_SEKRET)
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


def _tomorrow(hour: int) -> str:
    return (
        (times.now_in("America/New_York") + timedelta(days=1))
        .replace(hour=hour, minute=0)
        .strftime("%Y-%m-%dT%H:%M")
    )


async def test_the_tulip_key_reads(client):
    me = await client.get("/api/auth/me", headers=TULIP)
    assert me.status_code == 200 and me.json()["username"] == "robin"
    for path in (
        "/api/calendar/events?start=2026-01-01&end=2026-01-02",
        "/api/family",
        "/api/tasks/all",
        "/api/control/pending",
        "/api/control/audit",
        "/api/threads",
    ):
        r = await client.get(path, headers=TULIP)
        assert r.status_code == 200, f"{path} answered {r.status_code}: {r.text}"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/calendar/events"),
        ("PATCH", "/api/calendar/events/abc"),
        ("DELETE", "/api/calendar/events/abc"),
        ("POST", "/api/control/pending/1/approve"),
        ("POST", "/api/control/pending/1/deny"),
        ("POST", "/api/control/approve/1"),
        ("POST", "/api/tasks"),
        ("POST", "/api/members/invite"),
        ("PATCH", "/api/household"),
        ("GET", "/api/mail/connect"),
        ("POST", "/api/memory"),
        ("DELETE", "/api/threads/abc"),
    ],
)
async def test_the_tulip_key_cannot_write_directly_or_approve(client, method, path):
    r = await client.request(method, path, headers=TULIP, json={})
    assert r.status_code == 403
    assert r.json() == {"error": "the tulip key may only read and talk to the agent"}


async def test_the_tulip_key_is_named_tulip_on_the_trail(client, calendar):
    runtime.set_model(
        ScriptedModel([[call("create_event", title="Futbol", start=_tomorrow(19))], [say("ok")]])
    )
    r = await client.post("/api/agent", json={"text": "futbol tomorrow 7pm"}, headers=TULIP)
    assert r.status_code == 200, r.text
    started = [x for x in control.trail().records() if x.event_type == "turn.start"]
    assert started[-1].payload["principal"] == "tulip"
    assert started[-1].payload["door"] == "tulip"


async def test_approved_from_the_tulip_key_is_ignored(client, monkeypatch):
    seen: dict = {}

    async def fake_run_turn(text, **kwargs):
        seen.update(kwargs)
        return runtime.TurnResult(reply="ok", thread_id="t")

    monkeypatch.setattr(runtime, "run_turn", fake_run_turn)
    r = await client.post("/api/agent", json={"text": "add it", "approved": True}, headers=TULIP)
    assert r.status_code == 200, r.text
    assert seen["approved"] is False and seen["consent_by_words"] is False


async def test_the_service_key_keeps_its_approval(client, monkeypatch):
    seen: dict = {}

    async def fake_run_turn(text, **kwargs):
        seen.update(kwargs)
        return runtime.TurnResult(reply="ok", thread_id="t")

    monkeypatch.setattr(runtime, "run_turn", fake_run_turn)
    r = await client.post(
        "/api/agent",
        json={"text": "add it", "approved": True},
        headers={"x-luach-key": SERVICE_SEKRET},
    )
    assert r.status_code == 200, r.text
    assert seen["approved"] is True and seen["consent_by_words"] is True


async def test_a_yes_from_the_tulip_key_is_not_consent(calendar):
    """Nor, from anyone, consent to a whole turn: a yes in words approves only the
    cards it was shown (test_gate_hardening), and the tulip key's not even those."""
    from luach.agent import context

    for consent, expected in ((False, False), (True, False)):
        turn = runtime.stream_turn(
            "yes",
            user_id=1,
            principal="tulip",
            timezone="America/New_York",
            door="tulip",
            consent_by_words=consent,
        )
        first = await anext(turn)
        await turn.aclose()
        assert first["type"] == "session"
        assert context.current().approved is expected


def test_the_tulip_key_is_off_when_unset_or_equal_to_the_service_key(monkeypatch):
    monkeypatch.delenv("LUACH_TULIP_KEY", raising=False)
    assert config.tulip_key() == "" and not api_key.matches_tulip("anything")
    monkeypatch.setenv("LUACH_API_KEY", SERVICE_SEKRET)
    monkeypatch.setenv("LUACH_TULIP_KEY", SERVICE_SEKRET)
    assert config.tulip_key() == "" and not api_key.matches_tulip(SERVICE_SEKRET)


async def test_without_the_tulip_key_its_value_opens_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("LUACH_API_KEY", SERVICE_SEKRET)
    monkeypatch.delenv("LUACH_TULIP_KEY", raising=False)
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        assert (await c.get("/api/family", headers=TULIP)).status_code == 401
        assert (await c.get("/api/health")).status_code == 200

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from luach import db
from luach.app import create_app
from luach.auth import users


@pytest.fixture
async def client(tmp_path):
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<html>luach</html>")
    (static / "assets" / "a.js").write_text("1")
    app = create_app(static_dir=static)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


async def login(c, username="robin", password="correct horse battery"):
    r = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


async def test_an_uptime_monitor_may_ask_head(client):
    """HEAD / was a 405, which a monitor reads as down."""
    r = await client.head("/")
    assert r.status_code == 200


async def test_spa_and_assets_are_served(client):
    assert (await client.get("/")).text == "<html>luach</html>"
    assert (await client.get("/some/deep/route")).text == "<html>luach</html>"
    assert (await client.get("/assets/a.js")).text == "1"
    assert (await client.get("/../etc/passwd")).status_code in (200, 404)


async def test_the_shell_is_asked_again_and_the_hashed_assets_are_kept(client, tmp_path):
    """A cached index.html after an upgrade named /assets files that were gone: a blank page."""
    (tmp_path / "dist" / "sw.js").write_text("// worker")
    (tmp_path / "dist" / "icon-192.png").write_bytes(b"png")
    for path in ("/", "/agenda/deep", "/index.html", "/sw.js"):
        r = await client.get(path)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-cache", path
    r = await client.get("/assets/a.js")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    # A miss is not kept for a year: the next deploy may bring it.
    r = await client.get("/assets/index-gone.js")
    assert r.status_code == 404 and "immutable" not in r.headers.get("cache-control", "")
    # Anything else is left to the browser's own heuristics.
    assert "cache-control" not in (await client.get("/icon-192.png")).headers


async def test_bootstrap_register_creates_the_owner(client, monkeypatch):
    monkeypatch.setenv("LUACH_SETUP_CODE", "test-setup-code-1234")
    with db.session() as s:
        for u in s.query(db.User).all():
            s.delete(u)
    assert (await client.get("/api/auth/status")).json()["users_exist"] is False
    r = await client.post(
        "/api/auth/register",
        json={
            "username": "first",
            "email": "f@x.y",
            "password": "long enough pw",
            "timezone": "Asia/Jerusalem",
            "setup_code": "test-setup-code-1234",
        },
    )
    assert (
        r.status_code == 200
        and r.json()["is_owner"] is True
        and r.json()["timezone"] == "Asia/Jerusalem"
    )
    r = await client.post(
        "/api/auth/register",
        json={"username": "bad name", "email": "f@x.y", "password": "long enough pw"},
    )
    assert r.status_code == 403


async def test_bad_bodies(client):
    await login(client)
    assert (
        await client.post(
            "/api/agent", content=b"nope", headers={"content-type": "application/json"}
        )
    ).status_code == 400
    assert (await client.post("/api/agent", json=[1])).status_code == 400
    assert (await client.post("/api/agent", json={"text": 5})).status_code == 400
    assert (await client.post("/api/agent", json={})).status_code == 400
    assert (await client.get("/api/calendar/events?start=x&end=y")).status_code == 400
    assert (
        await client.post(
            "/api/calendar/events",
            json={"title": "T", "start": "2026-09-16T15:00", "end": "2026-09-16T14:00"},
        )
    ).status_code == 400
    assert (await client.patch("/api/calendar/events/nope", json={"title": "x"})).status_code == 404
    assert (await client.patch("/api/calendar/events/nope", json={})).status_code == 400
    assert (await client.delete("/api/calendar/events/nope")).status_code == 404
    assert (await client.get("/api/calendar/identity")).json()["backend"] == "fake"


async def test_password_change_and_member_admin(client):
    await login(client)
    assert (
        await client.post(
            "/api/auth/password", json={"current": "wrong", "new": "another long one"}
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/auth/password", json={"current": "correct horse battery", "new": "short"}
        )
    ).status_code == 400
    assert (
        await client.post(
            "/api/auth/password",
            json={"current": "correct horse battery", "new": "another long one"},
        )
    ).status_code == 200
    assert (await client.delete("/api/members/1")).status_code == 400
    assert (await client.delete("/api/members/999")).status_code == 404
    assert (await client.post("/api/members/invite", json={"email": "z@z.zz"})).status_code == 200
    assert (await client.delete("/api/members/invite/z@z.zz")).json()["revoked"] == 1
    assert (await client.delete("/api/members/2")).status_code == 200
    assert len((await client.get("/api/members")).json()["members"]) == 1
    assert (await client.post("/api/members/invite", json={"email": "nope"})).status_code == 400


async def test_invite_mails_when_configured(client, monkeypatch):
    from luach import mailer

    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setattr(mailer, "send_invitation", lambda to, inviter, token: True)
    await login(client)
    r = await client.post("/api/members/invite", json={"email": "m@x.y"})
    assert r.json() == {"sent": True}


async def test_control_and_thread_edges(client):
    await login(client)
    assert (await client.post("/api/control/approve/nope")).status_code == 404
    assert (await client.post("/api/control/deny/nope")).status_code == 404
    assert (await client.get("/api/threads/nope")).status_code == 404
    assert (await client.delete("/api/threads/nope")).status_code == 404
    assert (await client.get("/api/control/audit?limit=5")).json()["chain_verified"] is True
    from luach.agent import runtime
    from tests.doubles import ScriptedModel, say

    runtime.set_model(ScriptedModel([[say("hi")]]))
    tid = (await client.post("/api/agent", json={"text": "hi"})).json()["thread_id"]
    assert (await client.delete(f"/api/threads/{tid}")).status_code == 200
    assert (await client.get("/api/threads")).json()["threads"] == []


async def test_push_routes(client, monkeypatch):
    assert (await client.get("/api/push/key")).json()["public_key"] == ""
    monkeypatch.setenv("LUACH_VAPID_PUBLIC", "pub")
    monkeypatch.setenv("LUACH_VAPID_PRIVATE", "priv")
    assert (await client.get("/api/push/key")).json()["public_key"] == "pub"
    await login(client)
    assert (await client.post("/api/push/subscribe", json={"subscription": "x"})).status_code == 400
    assert (await client.post("/api/push/subscribe", json={"subscription": {}})).status_code == 400
    sub = {"endpoint": "https://142.250.80.10/fcm/send/1", "keys": {"p256dh": "k", "auth": "a"}}
    assert (await client.post("/api/push/subscribe", json={"subscription": sub})).status_code == 200
    # The same device, another member: not theirs to take.
    await login(client, "ana", "another good password")
    r = await client.post("/api/push/subscribe", json={"subscription": sub})
    assert r.status_code == 409
    r = await client.post("/api/push/unsubscribe", json={"endpoint": sub["endpoint"]})
    assert r.status_code == 200
    with db.session() as s:
        assert s.query(db.PushSubscription).count() == 1, "Ana did not stop Robin's device"
    await login(client)
    assert (
        await client.post("/api/push/unsubscribe", json={"endpoint": sub["endpoint"]})
    ).status_code == 200
    with db.session() as s:
        assert s.query(db.PushSubscription).count() == 0


async def test_transcribe_failures_over_http(client, monkeypatch):
    await login(client)
    monkeypatch.setenv("LUACH_TRANSCRIBE_CMD", "/bin/false")
    r = await client.post("/api/transcribe", content=b"x", headers={"content-type": "audio/webm"})
    assert r.status_code == 503
    from luach import transcribe

    r = await client.post(
        "/api/transcribe",
        content=b"x" * (transcribe.MAX_BYTES + 1),
        headers={"content-type": "audio/webm"},
    )
    assert r.status_code == 413


async def test_forgot_is_throttled_and_silent(client, monkeypatch):
    from luach import mailer

    sent: list = []
    monkeypatch.setattr(mailer, "send_recovery", lambda *a: sent.append(a) or True)
    for _ in range(10):
        assert (
            await client.post("/api/auth/forgot", json={"email": "ana@example.com"})
        ).status_code == 200
    assert len(sent) == 8  # eighth attempt locks the pair
    assert (
        await client.post("/api/auth/forgot", json={"email": "nobody@example.com"})
    ).status_code == 200
    assert (
        await client.post("/api/auth/reset", json={"token": "bad", "password": "long enough pw"})
    ).status_code == 400


async def test_lifespan_boots_and_verifies_the_chain(tmp_path, monkeypatch):
    from luach.app import lifespan

    monkeypatch.setenv("LUACH_GMAIL_POLL_MIN", "0")
    app = create_app(static_dir=tmp_path / "nope")
    async with lifespan(app):
        pass
    monkeypatch.setenv("LUACH_GMAIL_POLL_MIN", "1")
    async with lifespan(app):
        pass


async def test_email_routes(client):
    await login(client)
    assert (await client.get("/api/auth/emails")).json()["primary"] == "robin@example.com"
    r = await client.post("/api/auth/emails", json={"email": "robin.alt@example.com"})
    assert r.status_code == 200 and len(r.json()["emails"]) == 2
    assert [e["verified"] for e in r.json()["emails"]] == [True, False]
    assert (
        await client.post("/api/auth/emails", json={"email": "ana@example.com"})
    ).status_code == 400
    # Unconfirmed, so it is not yet one of the member's addresses…
    assert (await client.get("/api/auth/me")).json()["emails"] == ["robin@example.com"]
    assert (
        await client.post("/api/auth/emails/primary", json={"email": "robin.alt@example.com"})
    ).status_code == 400
    # …until the link mailed to it is followed.
    token = users.start_verification(1, "robin.alt@example.com", "alias")
    assert (await client.post("/api/auth/verify", json={"token": token})).status_code == 200
    assert (await client.post("/api/auth/verify", json={"token": token})).status_code == 400
    assert (await client.get("/api/auth/me")).json()["emails"] == [
        "robin@example.com",
        "robin.alt@example.com",
    ]
    r = await client.post("/api/auth/emails/primary", json={"email": "robin.alt@example.com"})
    assert r.json()["primary"] == "robin.alt@example.com"
    assert (await client.delete("/api/auth/emails/robin.alt@example.com")).status_code == 400
    assert (await client.delete("/api/auth/emails/robin@example.com")).status_code == 200
    assert (await client.delete("/api/auth/emails/nope@example.com")).status_code == 404
    await client.post("/api/auth/logout")
    await login(client, "robin.alt@example.com")


async def test_calendar_range_is_capped_but_any_year_works(client, calendar):
    await login(client)
    assert (
        await client.get("/api/calendar/events?start=2020-01-01&end=2026-01-01")
    ).status_code == 400
    assert (
        await client.get("/api/calendar/events?start=2026-02-01&end=2026-01-01")
    ).status_code == 400
    r = await client.get("/api/calendar/events?start=1999-12-01&end=1999-12-31")
    assert r.status_code == 200 and r.json()["events"] == [] and r.json()["start"] == "1999-12-01"
    r = await client.post(
        "/api/calendar/events", json={"title": "Y2K party", "start": "1999-12-31T22:00"}
    )
    assert r.status_code == 200
    r = await client.get("/api/calendar/events?start=1999-12-01&end=1999-12-31")
    assert [e["title"] for e in r.json()["events"]] == ["Y2K party"]

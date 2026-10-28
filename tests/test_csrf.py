"""A change comes from luach's own pages, or from outside a browser: another page on the
same site (a sibling subdomain) cannot make a signed-in member's browser change things."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from luach.app import create_app
from luach.auth import csrf

KEY = "svc-0123456789abcdef0123456789abcdef"
EVIL = "https://evil.example.test"


@pytest.fixture
async def client(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        r = await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        assert r.status_code == 200
        yield c


async def _tasks(c: AsyncClient) -> list:
    return (await c.get("/api/tasks/all")).json()["tasks"]


@pytest.mark.parametrize(
    "headers",
    [
        {"origin": EVIL},
        {"origin": "null"},
        {"sec-fetch-site": "same-site"},
        {"sec-fetch-site": "cross-site"},
        {"origin": "https://luach.test.evil.example"},
    ],
)
async def test_a_change_from_another_page_is_refused(client, headers):
    before = await _tasks(client)
    r = await client.post("/api/tasks", json={"title": "Planted"}, headers=headers)
    assert r.status_code == 403 and r.json()["error"] == csrf.FOREIGN
    r = await client.delete("/api/mail", headers=headers)
    assert r.status_code == 403
    assert await _tasks(client) == before


@pytest.mark.parametrize(
    "kind", ["application/x-www-form-urlencoded", "multipart/form-data; boundary=x", "text/plain"]
)
async def test_a_body_a_form_could_send_is_refused(client, kind):
    r = await client.post(
        "/api/tasks", content=b'{"title": "Planted"}', headers={"content-type": kind}
    )
    assert r.status_code == 415 and r.json()["error"] == csrf.NOT_JSON
    # Not even signing in: a form cannot sign a member's browser in to someone's account.
    r = await client.post(
        "/api/auth/login",
        content=b'{"username": "ana", "password": "another good password"}',
        headers={"content-type": kind},
    )
    assert r.status_code == 415
    r = await client.post("/api/tasks", content=b'{"title": "Planted"}')
    assert r.status_code == 415, "a body with no type at all is not JSON either"
    assert await _tasks(client) == []


async def test_luachs_own_pages_and_programs_still_change_things(client):
    # The web app: same origin, as LUACH_APP_URL names it or as the host it was served from.
    for headers in (
        {"origin": "https://luach.test", "sec-fetch-site": "same-origin"},
        {"origin": "http://luach.test"},
        {},  # the iPhone app and other programs send no Origin
        {"content-type": "application/json; charset=utf-8"},
    ):
        r = await client.post("/api/tasks", json={"title": "Bins"}, headers=headers)
        assert r.status_code == 200, (headers, r.text)
    # A button that only acts sends no body and no type.
    r = await client.post(
        "/api/control/pending/nope/deny", headers={"origin": "https://luach.test"}
    )
    assert r.status_code == 404, r.text
    r = await client.delete("/api/mail")
    assert r.status_code == 404, "reached the route"


async def test_voice_takes_audio_but_only_from_here(client, monkeypatch):
    monkeypatch.setenv("LUACH_TRANSCRIBE_CMD", "/bin/cat")
    audio = {"content-type": "audio/webm"}
    r = await client.post("/api/transcribe", content=b"hello", headers=audio)
    assert r.status_code == 200 and r.json()["text"] == "hello"
    r = await client.post("/api/transcribe", content=b"hello", headers={**audio, "origin": EVIL})
    assert r.status_code == 403


async def test_a_service_key_is_not_a_browser_and_is_not_asked(client, monkeypatch):
    monkeypatch.setenv("LUACH_API_KEY", KEY)
    r = await client.post(
        "/api/tasks",
        json={"title": "From the bot"},
        headers={"x-luach-key": KEY, "origin": EVIL},
    )
    assert r.status_code == 200, r.text


def test_reads_are_not_asked():
    assert csrf.refusal("GET", "/api/tasks", {"origin": EVIL}) is None
    assert csrf.refusal("POST", "/", {"origin": EVIL}) is None


@pytest.mark.parametrize(("peer", "allowed"), [("127.0.0.1", True), ("203.0.113.9", False)])
async def test_a_proxy_that_rewrites_host_is_believed_only_when_trusted(tmp_path, peer, allowed):
    """A reverse proxy that sends luach its own upstream name as Host says the browser's
    in X-Forwarded-Host; only one of LUACH_TRUSTED_PROXIES (loopback by default) is heard."""
    app = create_app(static_dir=tmp_path / "nope")
    transport = ASGITransport(app=app, client=(peer, 1234))
    async with AsyncClient(transport=transport, base_url="http://luach:8004") as c:
        r = await c.post(
            "/api/auth/login",
            json={"username": "robin", "password": "correct horse battery"},
            headers={
                "origin": "https://calendar.example.com",
                "x-forwarded-host": "calendar.example.com",
            },
        )
    assert (r.status_code == 200) is allowed, r.text

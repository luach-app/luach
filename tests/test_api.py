from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from luach import config, db
from luach.agent import runtime
from luach.app import create_app
from luach.calendar import times
from tests.doubles import ScriptedModel, call, say

SVC_KEY = "svc-0123456789abcdef0123456789abcdef"
TULIP_KEY = "tulip-0123456789abcdef0123456789abcdef"


@pytest.fixture
async def client(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


async def login(c: AsyncClient, username="robin", password="correct horse battery"):
    r = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _tomorrow(hour: int) -> str:
    return (
        (times.now_in("America/New_York") + timedelta(days=1))
        .replace(hour=hour, minute=0)
        .strftime("%Y-%m-%dT%H:%M")
    )


async def test_wall_blocks_anonymous_but_status_and_health_are_open(client):
    assert (await client.get("/api/health")).status_code == 200
    s = (await client.get("/api/auth/status")).json()
    assert s["users_exist"] is True and s["authenticated"] is False
    assert (
        await client.get("/api/calendar/events?start=2026-01-01&end=2026-01-02")
    ).status_code == 401


async def test_public_health_says_only_up_version_and_build(client):
    """It is open to the internet: the readiness probe and the wall board read it.
    It used to name the calendar (a personal calendar's id is its owner's Gmail), the
    service account, the model's address and how many people live here."""
    body = (await client.get("/api/health")).json()
    assert set(body) == {"ok", "version", "build"} and body["ok"] is True


async def test_health_details_are_for_members(client):
    assert (await client.get("/api/health/details")).status_code == 401
    await login(client)
    body = (await client.get("/api/health/details")).json()
    assert body["ok"] is True and {"version", "build"} <= set(body)
    assert body["calendar"]["backend"] == "fake" and "base_url" in body["model"]
    assert body["memory"]["configured"] is False and body["members"] == 2


async def test_health_details_answer_the_service_key_not_the_tulip_key(monkeypatch, client):
    monkeypatch.setenv("LUACH_API_KEY", SVC_KEY)
    monkeypatch.setenv("LUACH_TULIP_KEY", TULIP_KEY)
    r = await client.get("/api/health/details", headers={"x-luach-key": SVC_KEY})
    assert r.status_code == 200 and r.json()["members"] == 2
    r = await client.get("/api/health/details", headers={"x-luach-key": TULIP_KEY})
    assert r.status_code == 403
    r = await client.get("/api/health", headers={"x-luach-key": TULIP_KEY})
    assert r.status_code == 200


async def test_register_is_closed_once_the_owner_exists(client):
    r = await client.post(
        "/api/auth/register",
        json={"username": "x", "email": "x@y.zz", "password": "long enough pw"},
    )
    assert r.status_code == 403


async def test_login_logout_and_throttle(client):
    me = await login(client)
    assert me["is_owner"] is True and me["username"] == "robin"
    assert (await client.get("/api/auth/me")).json()["username"] == "robin"
    assert (await client.post("/api/auth/logout")).status_code == 200
    assert (await client.get("/api/auth/me")).status_code == 401
    for _ in range(8):
        r = await client.post("/api/auth/login", json={"username": "robin", "password": "nope"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"username": "robin", "password": "nope"})
    assert r.status_code == 429 and r.json()["retry_after"] > 0


async def test_owner_invites_and_invitee_joins(client, monkeypatch):
    await login(client)
    r = await client.post("/api/members/invite", json={"email": "Mom@Example.com"})
    assert r.status_code == 200
    data = r.json()
    assert data["sent"] is False and "?invite=" in data["link"]
    token = data["link"].split("?invite=")[1]
    listing = (await client.get("/api/members")).json()
    assert listing["invites"][0]["email"] == "mom@example.com"
    await client.post("/api/auth/logout")
    peek = await client.get(f"/api/auth/invite/{token}")
    assert peek.status_code == 200 and peek.json()["inviter"] == "Robin"
    r = await client.post(
        "/api/auth/accept",
        json={
            "token": token,
            "username": "mom",
            "password": "a fine password",
            "display_name": "Mamá",
        },
    )
    assert r.status_code == 200 and r.json()["is_owner"] is False
    assert (await client.get("/api/auth/me")).json()["display_name"] == "Mamá"
    # the invite is burnt
    assert (await client.get(f"/api/auth/invite/{token}")).status_code == 404
    # a non-owner cannot invite
    assert (await client.post("/api/members/invite", json={"email": "z@z.zz"})).status_code == 403


async def test_invite_duplicate_member_is_refused(client):
    await login(client)
    r = await client.post("/api/members/invite", json={"email": "ana@example.com"})
    assert r.status_code == 400 and "already a member" in r.json()["error"]


async def test_calendar_crud_via_ui_is_audited(client, calendar):
    await login(client)
    r = await client.post(
        "/api/calendar/events", json={"title": "Piano", "start": _tomorrow(17), "location": "Casa"}
    )
    assert r.status_code == 200, r.text
    ev = r.json()
    assert ev["title"] == "Piano" and ev["location"] == "Casa"
    day = ev["start"][:10]
    listed = (await client.get(f"/api/calendar/events?start={day}&end={day}")).json()
    assert [e["id"] for e in listed["events"]] == [ev["id"]]
    r = await client.patch(f"/api/calendar/events/{ev['id']}", json={"title": "Piano lesson"})
    assert r.json()["title"] == "Piano lesson"
    assert (await client.delete(f"/api/calendar/events/{ev['id']}")).status_code == 200
    assert (await client.get(f"/api/calendar/events/{ev['id']}")).status_code == 404
    audit = (await client.get("/api/control/audit")).json()
    kinds = [e["event_type"] for e in audit["entries"]]
    assert (
        kinds == ["event.created", "event.updated", "event.deleted"]
        and audit["chain_verified"] is True
    )


async def test_agent_json_turn_and_held_approval_over_http(client, calendar):
    await login(client)
    runtime.set_model(
        ScriptedModel(
            [
                [call("create_event", title="Vet", start=_tomorrow(9), certainty="low")],
                [say("held")],
            ]
        )
    )
    r = await client.post("/api/agent", json={"text": "vet tomorrow morning"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["held"] and body["thread_id"]
    pending = (await client.get("/api/control/pending")).json()["pending"]
    assert len(pending) == 1 and pending[0]["principal"] == "robin"
    r = await client.post(f"/api/control/approve/{pending[0]['id']}")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert len(calendar.events) == 1
    assert (await client.post(f"/api/control/approve/{pending[0]['id']}")).status_code == 409
    threads = (await client.get("/api/threads")).json()["threads"]
    assert threads[0]["id"] == body["thread_id"]
    turns = (await client.get(f"/api/threads/{body['thread_id']}")).json()["turns"]
    assert [t["role"] for t in turns] == ["user", "assistant"]


async def test_agent_stream_frames(client, calendar):
    await login(client)
    runtime.set_model(ScriptedModel([[say("Hola "), say("Robin")]]))
    async with client.stream("POST", "/api/agent/stream", json={"text": "hola"}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        raw = "".join([chunk async for chunk in r.aiter_text()])
    types = [
        line.split('"type": "')[1].split('"')[0]
        for line in raw.splitlines()
        if line.startswith("data:")
    ]
    assert types[0] == "session" and "token" in types and types[-1] == "done"


async def test_a_tool_run_from_the_web_chat_knows_whose_turn_it_is(client, calendar):
    """The turn is set in the stream's first step and read by a tool several
    steps later; a step that ran in a fresh context lost it, and every calendar
    tool in the web chat failed with "no turn context"."""
    await login(client)
    runtime.set_model(
        ScriptedModel(
            [
                [call("create_event", title="Dinner at Savta's", start=_tomorrow(19))],
                [say("Added.")],
            ]
        )
    )
    async with client.stream("POST", "/api/agent/stream", json={"text": "dinner"}) as r:
        raw = "".join([chunk async for chunk in r.aiter_text()])
    assert "no turn context" not in raw, raw
    assert [e.title for e in calendar.events.values()] == ["Dinner at Savta's"]


async def test_a_quiet_stream_is_kept_warm_and_the_comments_are_not_frames():
    """A reverse proxy, a tunnel or a CDN closes a connection that has gone
    quiet, and a turn can think for longer than any of them will wait."""
    import asyncio

    from luach.routes import agent as agent_routes

    async def slow():
        yield {"type": "session", "thread_id": "t1"}
        await asyncio.sleep(0.05)
        yield {"type": "done", "reply": "hi", "thread_id": "t1"}

    monkeyed = agent_routes.KEEPALIVE_SECONDS
    agent_routes.KEEPALIVE_SECONDS = 0.01
    try:
        out = [chunk async for chunk in agent_routes._kept_alive(slow())]
    finally:
        agent_routes.KEEPALIVE_SECONDS = monkeyed

    assert out[0].startswith('data: {"type": "session"')
    assert out[-1].startswith('data: {"type": "done"')
    assert any(c == ": keepalive\n\n" for c in out), out
    # A comment carries no frame, so the client that skips it loses nothing.
    assert [c for c in out if c.startswith("data:")] == [out[0], out[-1]]


class TestConversationsAreKept:
    """A thread the member can come back to, rename and throw away."""

    async def test_it_is_listed_with_a_title_a_person_can_recognise(self, client, calendar):
        await login(client)
        runtime.set_model(ScriptedModel([[say("Two things.")]]))
        body = (
            await client.post("/api/agent", json={"text": "what is on\n\n   this  week?"})
        ).json()

        listing = (await client.get("/api/threads")).json()
        assert listing["retention_days"] == 60
        [row] = listing["threads"]
        # Flattened: the title is read in a narrow column, not as three lines.
        assert row["title"] == "what is on this week?"
        assert row["id"] == body["thread_id"] and row["turns"] == 2
        assert row["created_at"] and row["updated_at"]

    async def test_a_long_first_message_is_cut_rather_than_wrapped(self):
        title = runtime.thread_title("x" * 300)
        assert len(title) <= 118 and title.endswith("…")
        assert runtime.thread_title("   ") == "New conversation"

    async def test_it_can_be_renamed(self, client, calendar):
        await login(client)
        runtime.set_model(ScriptedModel([[say("ok")]]))
        tid = (await client.post("/api/agent", json={"text": "hola"})).json()["thread_id"]

        r = await client.patch(f"/api/threads/{tid}", json={"title": "  the  dentist  "})
        assert r.status_code == 200 and r.json()["title"] == "the dentist"
        assert (await client.get("/api/threads")).json()["threads"][0]["title"] == "the dentist"

    async def test_deleting_one_takes_the_model_side_state_with_it(self, client, calendar):
        """The transcript and the state the model resumes from are two places.
        Deleting only the first left a directory per thread on the volume for
        ever, and left a reused id resuming a deleted conversation."""
        await login(client)
        runtime.set_model(ScriptedModel([[say("ok")]]))
        tid = (await client.post("/api/agent", json={"text": "hola"})).json()["thread_id"]
        checkpoints = config.checkpoint_dir() / tid
        assert checkpoints.exists()

        assert (await client.delete(f"/api/threads/{tid}")).status_code == 200
        assert (await client.get("/api/threads")).json()["threads"] == []
        assert not checkpoints.exists()

    async def test_one_member_never_sees_or_touches_anothers(self, client, calendar):
        await login(client)
        runtime.set_model(ScriptedModel([[say("ok")]]))
        tid = (await client.post("/api/agent", json={"text": "mine"})).json()["thread_id"]

        await client.post("/api/auth/logout")
        await login(client, "ana", "another good password")
        assert (await client.get("/api/threads")).json()["threads"] == []
        assert (await client.get(f"/api/threads/{tid}")).status_code == 404
        assert (await client.patch(f"/api/threads/{tid}", json={"title": "x"})).status_code == 404
        assert (await client.delete(f"/api/threads/{tid}")).status_code == 404

    async def test_the_sweep_takes_the_ones_nobody_came_back_to(self, client, calendar):
        from datetime import timedelta

        from luach.app import _purge_old_threads

        await login(client)
        runtime.set_model(ScriptedModel([[say("ok")], [say("ok")]]))
        old = (await client.post("/api/agent", json={"text": "last spring"})).json()["thread_id"]
        recent = (await client.post("/api/agent", json={"text": "today"})).json()["thread_id"]
        with db.session() as s:
            s.get(db.Thread, old).updated_at = db.utcnow() - timedelta(days=61)

        await _purge_old_threads()
        assert [t["id"] for t in (await client.get("/api/threads")).json()["threads"]] == [recent]
        assert not (config.checkpoint_dir() / old).exists()

    async def test_the_sweep_can_be_turned_off(self, client, monkeypatch, calendar):
        from datetime import timedelta

        from luach.app import _purge_old_threads

        monkeypatch.setenv("LUACH_THREAD_RETENTION_DAYS", "0")
        await login(client)
        runtime.set_model(ScriptedModel([[say("ok")]]))
        tid = (await client.post("/api/agent", json={"text": "hola"})).json()["thread_id"]
        with db.session() as s:
            s.get(db.Thread, tid).updated_at = db.utcnow() - timedelta(days=9999)

        await _purge_old_threads()
        assert len((await client.get("/api/threads")).json()["threads"]) == 1


async def test_service_key_acts_as_owner_and_is_named_by_its_setting(client, monkeypatch, calendar):
    """The key's name is who it is on the audit trail and the door it came through."""
    monkeypatch.setenv("LUACH_API_KEY", SVC_KEY)
    monkeypatch.setenv("LUACH_API_KEY_NAME", "chat-bot")
    runtime.set_model(
        ScriptedModel([[call("create_event", title="Futbol", start=_tomorrow(19))], [say("ok")]])
    )
    r = await client.post(
        "/api/agent", json={"text": "futbol tomorrow 7pm"}, headers={"x-luach-key": SVC_KEY}
    )
    assert r.status_code == 200, r.text
    assert r.json()["created"][0]["title"] == "Futbol"
    assert (await client.get("/api/auth/me", headers={"x-luach-key": "wrong"})).status_code == 401
    me = (await client.get("/api/auth/me", headers={"x-luach-key": SVC_KEY})).json()
    assert me["username"] == "robin"
    from luach.agent import control

    created = [r for r in control.trail().records() if r.event_type == "event.created"]
    assert created[0].payload["by"] == "chat-bot" and created[0].payload["door"] == "chat-bot"


async def test_service_key_is_named_service_when_its_name_is_unset(client, monkeypatch, calendar):
    monkeypatch.setenv("LUACH_API_KEY", SVC_KEY)
    monkeypatch.delenv("LUACH_API_KEY_NAME", raising=False)
    runtime.set_model(
        ScriptedModel([[call("create_event", title="Futbol", start=_tomorrow(19))], [say("ok")]])
    )
    r = await client.post(
        "/api/agent", json={"text": "futbol tomorrow 7pm"}, headers={"x-luach-key": SVC_KEY}
    )
    assert r.status_code == 200, r.text
    from luach.agent import control

    created = [r for r in control.trail().records() if r.event_type == "event.created"]
    assert created[0].payload["by"] == "service" and created[0].payload["door"] == "service"


async def test_profile_update_validates_timezone(client):
    await login(client)
    r = await client.patch("/api/auth/me", json={"timezone": "Mars/Olympus"})
    assert r.status_code == 400
    r = await client.patch("/api/auth/me", json={"timezone": "Asia/Jerusalem", "language": "he"})
    assert r.status_code == 200 and r.json()["timezone"] == "Asia/Jerusalem"


async def test_forgot_and_reset_flow(client, monkeypatch):
    sent: dict = {}
    from luach import mailer

    monkeypatch.setattr(
        mailer, "send_recovery", lambda to, username, token: sent.update(to=to, token=token) or True
    )
    r = await client.post("/api/auth/forgot", json={"email": "ana@example.com"})
    assert r.status_code == 200 and sent["to"] == "ana@example.com"
    r = await client.post(
        "/api/auth/reset", json={"token": sent["token"], "password": "brand new password"}
    )
    assert r.status_code == 200 and r.json()["username"] == "ana"
    assert (
        await client.post(
            "/api/auth/reset", json={"token": sent["token"], "password": "again and again"}
        )
    ).status_code == 400
    await client.post("/api/auth/logout")
    await login(client, "ana", "brand new password")


async def test_transcribe_status_reflects_config(client, monkeypatch):
    monkeypatch.delenv("LUACH_TRANSCRIBE_CMD", raising=False)
    assert (await client.get("/api/transcribe/status")).json() == {"available": False}
    monkeypatch.setenv("LUACH_TRANSCRIBE_CMD", "/bin/cat")
    assert (await client.get("/api/transcribe/status")).json() == {"available": True}
    await login(client)
    r = await client.post(
        "/api/transcribe", content=b"hello from a file", headers={"content-type": "audio/webm"}
    )
    assert r.status_code == 200 and r.json()["text"] == "hello from a file"
    assert config.transcribe_cmd() == "/bin/cat"


async def test_a_mistyped_api_path_says_so_instead_of_serving_the_app(client, monkeypatch):
    """A machine caller asked for /api/pending (the route is
    /api/control/pending) and got 200 and a page of HTML, which reads as "that
    worked". A browser only ever asks for real pages; a caller deserves telling."""
    monkeypatch.setenv("LUACH_API_KEY", SVC_KEY)
    key = {"x-luach-key": SVC_KEY}

    for path in ("/api/pending", "/api/nope", "/api/control/nope"):
        r = await client.get(path, headers=key)
        assert r.status_code == 404, f"{path} answered {r.status_code}"
        assert r.json() == {"error": "no such route"}

    # The real route still answers.
    assert (await client.get("/api/control/pending", headers=key)).status_code == 200


async def test_a_page_is_still_a_page_when_the_app_is_built(tmp_path, monkeypatch):
    """The 404 is for /api only: every other path belongs to the single-page app,
    which owns its own routing and must keep getting index.html."""
    monkeypatch.setenv("LUACH_API_KEY", SVC_KEY)
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>luach</title>")

    app = create_app(static_dir=static)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        page = await c.get("/settings")
        assert page.status_code == 200 and page.text.startswith("<!doctype html")
        gone = await c.get("/api/pending", headers={"x-luach-key": SVC_KEY})
        assert gone.status_code == 404 and gone.json() == {"error": "no such route"}


async def test_about_and_privacy_are_public_pages(tmp_path):
    """Google checks a home page and a privacy policy, signed out, before members may
    connect Gmail; the app itself opens on the sign-in screen."""
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>luach app</title>")
    for name in ("about", "privacy"):
        (static / name).mkdir()
        (static / name / "index.html").write_text(f"<!doctype html><title>{name}</title>")

    app = create_app(static_dir=static)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        for name in ("about", "privacy"):
            for path in (f"/{name}", f"/{name}/"):
                page = await c.get(path)
                assert page.status_code == 200 and f"<title>{name}</title>" in page.text, path
        assert "luach app" in (await c.get("/settings")).text


def _public_page(name: str) -> str:
    from pathlib import Path

    from luach import public_pages

    web = Path(__file__).resolve().parents[1] / "web" / "public"
    return public_pages.render((web / name / "index.html").read_text())


OWNER = {
    "LUACH_HOUSEHOLD_NAME": "Rivera",
    "LUACH_OPERATOR_NAME": "Dana Rivera",
    "LUACH_CONTACT_EMAIL": "dana@rivera.example",
    "LUACH_APP_URL": "https://luach.rivera.example",
    "LUACH_PRIVACY_MODELS": "Our models run in the garage.",
}


def test_the_public_pages_say_what_google_asks():
    """The privacy policy carries the Limited Use statement and the scope; the home
    page says what luach is and links the policy."""
    privacy, about = _public_page("privacy"), _public_page("about")
    assert "Limited Use" in privacy and "gmail.readonly" in privacy
    assert "api-services-user-data-policy" in privacy
    assert "The iPhone app" in privacy
    assert 'href="/privacy"' in about and "household calendar" in about


def test_the_public_pages_name_who_runs_this_luach(monkeypatch):
    for key, value in OWNER.items():
        monkeypatch.setenv(key, value)
    about, privacy = _public_page("about"), _public_page("privacy")
    assert "<title>luach · the Rivera household calendar</title>" in about
    assert "<h1>The Rivera household calendar</h1>" in about
    assert "the Rivera family's private household calendar" in about
    assert "run by Dana Rivera for their household at luach.rivera.example" in about
    assert 'Contact: <a href="mailto:dana@rivera.example">dana@rivera.example</a>' in about
    assert "luach, the Rivera household calendar · luach.rivera.example · last" in privacy
    assert (
        'run by Dana Rivera (<a href="mailto:dana@rivera.example">dana@rivera.example</a>)'
        in privacy
    )
    assert 'Your whole account:</strong> email <a href="mailto:dana@rivera.example">' in privacy
    assert "<p>Our models run in the garage.</p>" in privacy
    for page in (about, privacy):
        assert "{{" not in page


def test_the_public_pages_name_nobody_by_default(monkeypatch):
    for key in OWNER:
        monkeypatch.delenv(key, raising=False)
    about, privacy = _public_page("about"), _public_page("privacy")
    for page in (about, privacy):
        assert "{{" not in page and "mailto:" not in page
        # Nobody's details stand in for unset ones: none of a household's values appear.
        for value in ("Rivera", "Dana", "rivera.example", "garage"):
            assert value not in page, value
    assert "<h1>The household calendar</h1>" in about
    assert "This luach is run for one household, and accounts" in about
    assert "Privacy policy</a>\n  </footer>" in about, "no contact line"
    assert "run by the person who runs this luach. It is not offered" in privacy
    assert "ask the person who runs this luach and it will be deleted" in privacy
    assert "Limited Use" in privacy and "The iPhone app" in privacy


def test_the_public_pages_escape_what_they_are_given(monkeypatch):
    monkeypatch.setenv("LUACH_HOUSEHOLD_NAME", '<script>"x"</script>')
    monkeypatch.setenv("LUACH_OPERATOR_NAME", "A <b>bold</b> name")
    monkeypatch.setenv("LUACH_CONTACT_EMAIL", 'a"><script>@x.y')
    monkeypatch.setenv("LUACH_PRIVACY_MODELS", "models <img src=x>")
    about, privacy = _public_page("about"), _public_page("privacy")
    for page in (about, privacy):
        assert '<script>"x"' not in page and "<b>bold" not in page
        assert "<img src=x>" not in page and "><script>@" not in page
    assert "&lt;script&gt;&quot;x&quot;&lt;/script&gt;" in about
    assert "A &lt;b&gt;bold&lt;/b&gt; name" in privacy
    assert 'href="mailto:a&quot;&gt;&lt;script&gt;@x.y"' in privacy


async def test_the_public_pages_are_filled_in_when_served(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setenv("LUACH_HOUSEHOLD_NAME", "Rivera")
    web = Path(__file__).resolve().parents[1] / "web" / "public"
    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>luach app</title>")
    for name in ("about", "privacy"):
        (static / name).mkdir()
        (static / name / "index.html").write_text((web / name / "index.html").read_text())

    app = create_app(static_dir=static)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        for path in ("/about", "/about/", "/about/index.html"):
            page = await c.get(path)
            assert page.status_code == 200, path
            assert "<h1>The Rivera household calendar</h1>" in page.text
            assert page.headers["content-type"].startswith("text/html")
        tag = page.headers["etag"]
        again = await c.get("/about", headers={"If-None-Match": tag})
        assert again.status_code == 304 and again.headers["etag"] == tag
        privacy = await c.get("/privacy")
        assert "{{" not in privacy.text and "Rivera household calendar" in privacy.text
        monkeypatch.setenv("LUACH_HOUSEHOLD_NAME", "Okafor")
        changed = await c.get("/about", headers={"If-None-Match": tag})
        assert changed.status_code == 200 and "Okafor" in changed.text


async def test_the_sign_in_screen_learns_the_household_before_sign_in(client, monkeypatch):
    monkeypatch.delenv("LUACH_HOUSEHOLD_NAME", raising=False)
    assert (await client.get("/api/auth/status")).json()["household"] == ""
    monkeypatch.setenv("LUACH_HOUSEHOLD_NAME", "Rivera")
    assert (await client.get("/api/auth/status")).json()["household"] == "Rivera"


async def test_an_anonymous_caller_is_refused_before_the_route_is_looked_up(client):
    """401 rather than 404: which routes exist is not an anonymous caller's business."""
    for path in ("/api/nope", "/api/threads"):
        r = await client.get(path)
        assert r.status_code == 401 and r.json() == {"error": "sign in first"}


def test_google_sign_in_codes_stay_out_of_the_access_log():
    import logging

    from luach.app import _NoSecretsInTheAccessLog

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        (
            "1.2.3.4:0",
            "GET",
            "/api/mail/callback?state=S3CRET&iss=https://accounts.google.com&code=4/0AXcode",
            "1.1",
            302,
        ),
        None,
    )
    assert _NoSecretsInTheAccessLog().filter(record)
    line = record.getMessage()
    assert "S3CRET" not in line and "4/0AXcode" not in line
    assert "state=…" in line and "code=…" in line and "iss=https://accounts.google.com" in line


@pytest.mark.parametrize(
    ("path", "kept"),
    [
        ("/?reset=R3SET-tok&lang=he", "/?reset=…&lang=he"),
        ("/?invite=INV1TE", "/?invite=…"),
        ("/?verify=V3RIFY", "/?verify=…"),
        ("/book/robin?manage=MAN4GE", "/book/robin?manage=…"),
        ("/api/auth/invite/INV1TE", "/api/auth/invite/…"),
        ("/api/auth/invite/INV1TE?x=1", "/api/auth/invite/…?x=1"),
        ("/api/book/robin/manage/MAN4GE", "/api/book/robin/manage/…"),
        ("/api/book/robin/manage/MAN4GE/cancel", "/api/book/robin/manage/…/cancel"),
        ("/api/board/pair/PA1R", "/api/board/pair/…"),
        ("/api/book/robin", "/api/book/robin"),
        ("/api/calendar/events?start=2026-01-01", "/api/calendar/events?start=2026-01-01"),
    ],
)
def test_tokens_in_links_stay_out_of_the_access_log(path, kept):
    import logging

    from luach.app import _NoSecretsInTheAccessLog

    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:0", "GET", path, "1.1", 200),
        None,
    )
    assert _NoSecretsInTheAccessLog().filter(record)
    assert record.args[2] == kept
    for secret in ("R3SET", "INV1TE", "V3RIFY", "MAN4GE", "PA1R"):
        assert secret not in record.getMessage()


def test_an_invitation_from_someone_else_is_read_only():
    from luach.calendar import client

    invite = {
        "id": "x",
        "summary": "Interview",
        "start": {"dateTime": "2026-10-02T10:00:00-04:00"},
        "end": {"dateTime": "2026-10-02T11:00:00-04:00"},
        "organizer": {"email": "recruiting@acme.example"},
    }
    ev = client._from_google(invite, "robin@example.com")
    assert ev.read_only and ev.organizer == "recruiting@acme.example"
    own = {**invite, "organizer": {"email": "robin@example.com", "self": True}}
    assert not client._from_google(own, "robin@example.com").read_only
    family = {**invite, "organizer": {"email": "family@group.calendar.google.com"}}
    assert not client._from_google(family, "family@group.calendar.google.com").read_only
    open_to_guests = {**invite, "guestsCanModify": True}
    assert not client._from_google(open_to_guests, "robin@example.com").read_only


def test_a_calendar_luach_only_reads_marks_its_events_read_only(monkeypatch):
    from datetime import UTC, datetime

    from luach.calendar import client

    cal = client.GoogleCalendar.__new__(client.GoogleCalendar)
    cal.calendar_id = "family"
    item = {
        "id": "e",
        "summary": "Lunch",
        "start": {"dateTime": "2026-10-02T12:00:00-04:00"},
        "end": {"dateTime": "2026-10-02T13:00:00-04:00"},
    }
    monkeypatch.setattr(cal, "_run", lambda make: {"items": [item]}, raising=False)
    monkeypatch.setattr(
        cal,
        "calendars",
        lambda: [
            client.CalendarInfo(id="family", name="F"),
            client.CalendarInfo(id="mine", name="M", writable=False),
        ],
        raising=False,
    )
    now = datetime.now(UTC)
    assert not cal._list_one("family", now, now, "")[0].read_only
    assert cal._list_one("mine", now, now, "")[0].read_only


async def test_changing_or_removing_an_invitation_is_a_clear_no(client, calendar):
    await login(client)
    from luach.calendar import times
    from luach.calendar.client import Draft

    ev = calendar.insert(
        Draft(title="Interview", span=times.span("2026-10-08T10:00", None, "America/New_York")),
        "America/New_York",
    )
    calendar.events[ev.id].read_only = True
    calendar.events[ev.id].organizer = "recruiting@acme.example"
    r = await client.patch(f"/api/calendar/events/{ev.id}", json={"title": "Mine now"})
    assert r.status_code == 409 and "only they can change it" in r.json()["error"]
    r = await client.delete(f"/api/calendar/events/{ev.id}")
    assert r.status_code == 409


async def test_google_refusing_a_change_is_a_409_not_a_500(client, calendar, monkeypatch):
    await login(client)
    import httplib2
    from googleapiclient.errors import HttpError

    from luach.calendar import times
    from luach.calendar.client import Draft

    ev = calendar.insert(
        Draft(title="Shared", span=times.span("2026-10-09T10:00", None, "America/New_York")),
        "America/New_York",
    )

    def refuse(*a, **k):
        raise HttpError(
            httplib2.Response({"status": "403"}),
            b'{"error": {"message": "forbiddenForNonOrganizer"}}',
        )

    monkeypatch.setattr(calendar, "patch", refuse)
    r = await client.patch(f"/api/calendar/events/{ev.id}", json={"title": "x"})
    assert r.status_code == 409 and "organizer" in r.json()["error"]


def test_moving_an_all_day_event_to_a_time_clears_its_date():
    """Picture Day, all day, moved to 09:00-12:00: Google refused date and dateTime
    side by side (400)."""
    from luach.calendar import client

    body = client._body_from_changes(
        {"start": "2026-10-16T09:00", "end": "2026-10-16T12:00"}, "America/New_York"
    )
    assert body["start"]["date"] is None and body["start"]["dateTime"].startswith(
        "2026-10-16T09:00"
    )
    body = client._body_from_changes(
        {"start": "2026-10-16", "end": "2026-10-17"}, "America/New_York"
    )
    assert body["start"]["date"] == "2026-10-16" and body["start"]["dateTime"] is None


async def test_a_held_change_reads_as_a_sentence(calendar):
    from luach.agent import context, control
    from luach.calendar.client import Draft

    ev = calendar.insert(
        Draft(title="Picture Day", span=times.span("2026-10-15", None, "America/New_York")),
        "America/New_York",
    )
    context.set_turn(
        context.Turn(calendar=calendar, user_id=1, principal="robin", timezone="America/New_York")
    )
    said = control.describe_call(
        "update_event",
        {
            "event_id": ev.id,
            "start": "2026-10-16T09:00",
            "end": "2026-10-16T12:00",
            "description": "x",
        },
        "America/New_York",
    )
    assert "{" not in said and ev.id not in said
    assert said.startswith("Change “Picture Day”: move it to") and "change its notes" in said
    assert control.describe_call(
        "delete_event", {"event_id": ev.id}, "America/New_York"
    ).startswith("Delete “Picture Day”")
    context.set_turn(None)


async def test_health_names_the_web_build_a_wall_board_compares_with_its_own(tmp_path):
    """The house board reloads itself after a deploy: it reads its own entry script
    from the page and compares it with the one the server now hands out."""
    from luach.routes.health import build_of

    static = tmp_path / "dist"
    (static / "assets").mkdir(parents=True)
    index = static / "index.html"
    index.write_text(
        '<!doctype html><script type="module" crossorigin src="/assets/index-AbC123.js"></script>'
    )
    app = create_app(static_dir=static)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        assert (await c.get("/api/health")).json()["build"] == "/assets/index-AbC123.js"
        index.write_text(
            '<!doctype html><script type="module" crossorigin src="/assets/index-Zz9.js"></script>'
        )
        assert (await c.get("/api/health")).json()["build"] == "/assets/index-Zz9.js"
    # No built app (dev, the tests): nothing to compare, and nothing reloads.
    assert build_of(tmp_path / "nope") == ""
    assert build_of(None) == ""


async def test_a_member_whose_actions_were_held_can_be_removed(client, calendar):
    """pending_actions.user_id had no ON DELETE: removing anyone who had ever had an
    action held was a foreign-key violation, a 500 on Members › Remove."""
    from luach import db
    from luach.agent import pending

    def held(pid: str, status: str, door: str = "web") -> db.PendingAction:
        return db.PendingAction(
            id=pid,
            user_id=2,
            principal="ana",
            door=door,
            tool="create_event",
            args_json="{}",
            summary=f"Add {pid}",
            status=status,
        )

    with db.session() as s:
        s.add_all(
            [held("p1", "pending"), held("p2", "approved"), held("p3", "pending", "email-scan")]
        )
    await login(client)
    r = await client.delete("/api/members/2")
    assert r.status_code == 200, r.text
    with db.session() as s:
        rows = {r.id: r.user_id for r in s.query(db.PendingAction)}
    assert rows == {"p1": None, "p2": None, "p3": None}, "kept, as nobody's"
    seen = {p["id"] for p in pending.list_pending(viewer_id=1, include_decided=True)}
    assert seen == {"p1", "p2"}, "a private proposal from their own mail is seen by nobody"


def _held(pid: str, tool: str = "create_event", args: str = "{}") -> None:
    from luach import db

    with db.session() as s:
        s.add(
            db.PendingAction(
                id=pid,
                user_id=1,
                principal="robin",
                door="web",
                tool=tool,
                args_json=args,
                summary=f"Do {pid}",
                status="pending",
            )
        )


def test_two_yeses_at_once_run_the_held_call_once(monkeypatch):
    """Two people (or two devices) tapping Approve both read "pending" and both ran
    the call: two events where one was proposed."""
    import threading
    import time
    from types import SimpleNamespace

    from luach.agent import pending

    runs: list[int] = []

    def slow(**kwargs):
        runs.append(1)
        time.sleep(0.3)
        return {"created": {"id": "e1"}}

    monkeypatch.setitem(pending.APPROVABLE, "create_event", SimpleNamespace(fn=slow))
    _held("p1")
    start = threading.Barrier(2)
    outcomes: list[str] = []

    def tap(who: str) -> None:
        start.wait()
        try:
            outcomes.append(pending.approve("p1", by=who, timezone="UTC")["status"])
        except pending.AlreadyDecided as exc:
            outcomes.append(str(exc))

    taps = [threading.Thread(target=tap, args=(who,)) for who in ("robin", "ana")]
    for t in taps:
        t.start()
    for t in taps:
        t.join(10)
    assert len(runs) == 1
    assert sorted(outcomes) == ["already decided: someone is approving it now", "approved"]
    with pytest.raises(pending.AlreadyDecided, match="already approved"):
        pending.deny("p1", by="ana")


async def test_a_second_decision_is_told_it_was_already_made(client, calendar):
    _held("p2", "create_event", '{"title": "Dentist", "start": "2026-11-02T15:00"}')
    await login(client)
    r = await client.post("/api/control/pending/p2/deny")
    assert r.status_code == 200 and r.json()["status"] == "denied"
    r = await client.post("/api/control/pending/p2/approve")
    assert r.status_code == 409 and r.json()["error"] == "already denied"
    assert calendar.events == {}


async def test_an_approval_the_tool_refused_is_failed_not_approved(client, calendar):
    """Tools answer {"error": …} rather than raise, and the row said "approved":
    the apps showed Approved for an event that was never changed."""
    _held("p3", "create_event", '{"title": "Dentist", "start": "someday soon"}')
    await login(client)
    r = await client.post("/api/control/pending/p3/approve")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed" and body["result"]["error"]
    r = await client.post("/api/control/pending/p3/approve")
    assert r.status_code == 409 and r.json()["error"] == "already failed"

"""A member deletes their own account: DELETE /api/auth/me with their password."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from tulip.memory.store import InMemoryStore

from luach import db, mail_accounts, memory
from luach.agent import runtime
from luach.app import create_app
from luach.auth import throttle


@pytest.fixture
async def client(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setenv("LUACH_MEMORY_DSN", "postgresql://luach@127.0.0.1/luach")
    s = InMemoryStore()
    memory.set_store(s)
    return s


@pytest.fixture
def revoked(monkeypatch) -> list[int]:
    """Whose Gmail grants were revoked, without asking Google."""
    seen: list[int] = []

    def disconnect(user_id: int) -> bool:
        seen.append(user_id)
        return True

    monkeypatch.setattr(mail_accounts, "disconnect", disconnect)
    return seen


@pytest.fixture
def forgotten(monkeypatch) -> list[str]:
    """Which conversations' model-side state was dropped."""
    seen: list[str] = []

    async def forget(thread_id: str) -> None:
        seen.append(thread_id)

    monkeypatch.setattr(runtime, "forget_thread", forget)
    return seen


async def login(c: AsyncClient, username: str, password: str) -> None:
    r = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


async def delete_me(c: AsyncClient, password: str | None):
    body = {} if password is None else {"password": password}
    return await c.request("DELETE", "/api/auth/me", json=body)


def user_ids() -> list[int]:
    with db.session() as s:
        return sorted(u.id for u in s.query(db.User))


async def test_a_member_deletes_their_own_account(client, store, revoked, forgotten):
    with db.session() as s:
        s.add(db.Thread(id="t-ana", user_id=2, title="Ana's", door="web"))
        s.add(db.Thread(id="t-robin", user_id=1, title="Robin's", door="web"))
    await memory.remember(2, "ana", "I take the early train", "commute")
    await memory.remember(1, "robin", "I only book mornings", "appointments")
    await login(client, "ana", "another good password")

    r = await delete_me(client, "another good password")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}
    # Signed out here, and the account is gone: no session, no sign-in.
    assert (await client.get("/api/auth/me")).status_code == 401
    r = await client.post(
        "/api/auth/login", json={"username": "ana", "password": "another good password"}
    )
    assert r.status_code == 401
    assert user_ids() == [1]
    # What went with it: the Gmail grant (revoked at Google first), the conversations and
    # their model-side state, and what luach remembered about them. Nobody else's.
    assert revoked == [2]
    assert forgotten == ["t-ana"]
    with db.session() as s:
        assert [t.id for t in s.query(db.Thread)] == ["t-robin"]
    assert (await memory.recall(2, "ana"))["count"] == 0
    assert (await memory.recall(1, "robin"))["count"] == 1

    # The household's record says an account was deleted, by its own member.
    await login(client, "robin", "correct horse battery")
    entries = (await client.get("/api/control/audit")).json()["entries"]
    gone = [e for e in entries if e["event_type"] == "member.deleted_own_account"]
    assert len(gone) == 1 and gone[0]["payload"] == {"user_id": 2}


async def test_their_settings_go_too(client, revoked):
    """Reminders, the booking page and the email scan are settings rows, not foreign keys:
    a deleted member's booking link name must not stay taken by nobody."""
    from luach import booking, reminders
    from luach.ingest import mail_scan

    reminders.update(2, {"lead_minutes": 30})
    reminders.update(1, {"lead_minutes": 15})
    booking.update(2, {"slug": "ana-books", "enabled": True})
    with db.session() as s:
        s.add(db.Setting(key=mail_scan.SETTING.format(user_id=2), value="{}"))
    await login(client, "ana", "another good password")
    assert (await delete_me(client, "another good password")).status_code == 200
    with db.session() as s:
        keys = sorted(r.key for r in s.query(db.Setting) if r.key.endswith("2"))
    assert keys == []
    assert booking.by_slug("ana-books") is None
    assert reminders.settings_for(1)["lead_minutes"] == 15


async def test_every_session_of_theirs_ends(tmp_path, revoked):
    app = create_app(static_dir=tmp_path / "nope")
    transport = ASGITransport(app=app)
    async with (
        AsyncClient(transport=transport, base_url="http://luach.test") as phone,
        AsyncClient(transport=transport, base_url="http://luach.test") as laptop,
    ):
        await login(phone, "ana", "another good password")
        await login(laptop, "ana", "another good password")
        assert (await delete_me(phone, "another good password")).status_code == 200
        assert (await laptop.get("/api/auth/me")).status_code == 401


async def test_the_password_is_asked_again(client, revoked):
    await login(client, "ana", "another good password")
    r = await delete_me(client, "not my password")
    assert r.status_code == 401
    assert r.json()["error"] == "the password is wrong"
    r = await delete_me(client, None)
    assert r.status_code == 400
    # Nothing happened: still signed in, still a member, Gmail untouched.
    assert (await client.get("/api/auth/me")).json()["username"] == "ana"
    assert user_ids() == [1, 2]
    assert revoked == []


async def test_a_stolen_session_cannot_guess_the_password(client, revoked):
    await login(client, "ana", "another good password")
    for _ in range(throttle.MAX_ATTEMPTS):
        assert (await delete_me(client, "guess")).status_code == 401
    r = await delete_me(client, "another good password")
    assert r.status_code == 429 and r.json()["retry_after"] > 0
    assert user_ids() == [1, 2]


async def test_wrong_passwords_here_count_against_the_account(client, monkeypatch, revoked):
    """Guesses through this door add to the account's own lockout, which sign-in checks too."""
    monkeypatch.setattr(throttle, "ACCOUNT_MAX_ATTEMPTS", 3)
    await login(client, "ana", "another good password")
    for _ in range(3):
        assert (await delete_me(client, "guess")).status_code == 401
    r = await client.post(
        "/api/auth/login", json={"username": "ana", "password": "another good password"}
    )
    assert r.status_code == 429


async def test_signed_out_it_is_refused(client, revoked):
    r = await delete_me(client, "correct horse battery")
    assert r.status_code == 401
    assert user_ids() == [1, 2]


async def test_the_owner_cannot_leave_while_others_belong(client, revoked):
    await login(client, "robin", "correct horse battery")
    r = await delete_me(client, "correct horse battery")
    assert r.status_code == 409
    assert "remove the other members first" in r.json()["error"]
    assert user_ids() == [1, 2]
    assert revoked == [], "a refused delete does not disconnect their Gmail"


async def test_the_owner_alone_may_leave(client, revoked):
    await login(client, "robin", "correct horse battery")
    assert (await client.delete("/api/members/2")).status_code == 200
    r = await delete_me(client, "correct horse battery")
    assert r.status_code == 200, r.text
    assert user_ids() == []
    # The server is back where a new one starts: no accounts, setup by its code.
    status = (await client.get("/api/auth/status")).json()
    assert status["users_exist"] is False and status["authenticated"] is False


def test_the_owner_check_holds_under_the_lock():
    """remove_self checks again inside its transaction, whatever the route saw."""
    from luach.auth import users

    with pytest.raises(users.OwnerHasMembers):
        users.remove_self(1)
    assert users.remove_self(99) is False
    assert users.remove_self(2) is True
    assert users.owner_has_members(1) is False
    assert users.remove_self(1) is True
    assert user_ids() == []


async def test_memory_that_does_not_answer_does_not_stop_it(client, monkeypatch, revoked):
    monkeypatch.setenv("LUACH_MEMORY_DSN", "postgresql://luach@127.0.0.1/luach")

    class Broken(InMemoryStore):
        async def search(self, namespace, query=None, limit=10):
            raise RuntimeError("the memory database is down")

    memory.set_store(Broken())
    await login(client, "ana", "another good password")
    assert (await delete_me(client, "another good password")).status_code == 200
    assert user_ids() == [1]


async def test_forgetting_a_member_without_memory_is_nothing(monkeypatch):
    monkeypatch.delenv("LUACH_MEMORY_DSN", raising=False)
    memory.reset()
    assert await memory.forget_member(2) == 0


async def test_forgetting_a_member_takes_every_page(store, monkeypatch):
    monkeypatch.setattr(memory, "LISTED_LIMIT", 2)
    for i in range(5):
        await memory.remember(2, "ana", f"fact number {i}", f"topic {i}")
    assert await memory.forget_member(2) == 5
    assert (await memory.recall(2, "ana", limit=50))["count"] == 0

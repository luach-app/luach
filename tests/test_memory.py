"""What luach remembers about a member, and the two ways it can fail."""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from tulip.memory.store import InMemoryStore

from luach import memory, memory_health
from luach.agent import context, runtime
from luach.agent.tools import remember, toolset
from luach.app import create_app
from luach.calendar import client


@pytest.fixture
async def api(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


async def _login(c: AsyncClient) -> None:
    r = await c.post(
        "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
    )
    assert r.status_code == 200, r.text


@pytest.fixture
def store(monkeypatch):
    """A real tulip store, in memory. PgMemory needs a Postgres; everything
    above it is the same code path either way, because both are BaseStore."""
    monkeypatch.setenv("LUACH_MEMORY_DSN", "postgresql://luach@127.0.0.1/luach")
    s = InMemoryStore()
    memory.set_store(s)
    return s


def _turn(user_id: int | None = 1, principal: str = "robin"):
    return context.Turn(
        calendar=client.FakeCalendar(),
        user_id=user_id,
        principal=principal,
        timezone="America/New_York",
    )


async def test_a_fact_outlives_the_thread_it_was_said_in(store):
    await memory.remember(1, "robin", "I only book appointments in the morning", "appointments")
    out = await memory.recall(1, "robin", "appointments")
    assert out["count"] == 1
    assert out["facts"][0]["fact"] == "I only book appointments in the morning"
    assert out["facts"][0]["topic"] == "appointments"
    # And it is fenced on the way back, like anything luach did not write.
    assert "context" in out and out["facts"][0]["fact"] in out["context"]


async def test_restating_a_preference_replaces_it_rather_than_contradicting_it(store):
    await memory.remember(1, "robin", "I prefer mornings", "appointments")
    await memory.remember(1, "robin", "actually afternoons are better now", "appointments")
    out = await memory.recall(1, "robin")
    assert out["count"] == 1 and "afternoons" in out["facts"][0]["fact"]


async def test_one_member_never_reads_another_members_facts(store):
    """A household shares a calendar. It does not share what each person has
    told luach about themselves, so the member is the tenant — namespace[0],
    which is PgMemory's hard boundary."""
    await memory.remember(1, "robin", "I only book mornings")
    await memory.remember(2, "ana", "I work nights")

    assert memory.namespace(1, "robin")[0] == "member-1"
    assert memory.namespace(2, "ana")[0] == "member-2"

    mine = await memory.recall(1, "robin")
    assert [f["fact"] for f in mine["facts"]] == ["I only book mornings"]
    theirs = await memory.recall(2, "ana")
    assert [f["fact"] for f in theirs["facts"]] == ["I work nights"]


async def test_a_caller_with_no_member_gets_its_own_tenant(store):
    """The service key and the mail door act for nobody in particular, and
    must not land in the owner's drawer."""
    assert memory.namespace(None, "service")[0] == "principal-service"


async def test_the_tool_saves_when_given_a_fact_and_recalls_when_not(store):
    context.set_turn(_turn())
    try:
        saved = await remember.fn(fact="Theo finishes school at 3:30", topic="school")
        assert saved["saved"] is True and saved["key"] == "school"

        found = await remember.fn(topic="school")
        assert found["saved"] is False and found["found"] is True
        assert "3:30" in found["facts"][0]["fact"]
    finally:
        context.set_turn(None)


async def test_a_household_with_no_memory_database_is_told_so_not_left_guessing(monkeypatch):
    monkeypatch.delenv("LUACH_MEMORY_DSN", raising=False)
    memory.reset()
    assert memory.configured() is False
    # The model is not offered a tool that cannot work, the same way it is not
    # offered search without a search engine.
    names = [getattr(t, "name", getattr(t, "__name__", "")) for t in toolset("robin")]
    assert "remember" not in names

    context.set_turn(_turn())
    try:
        out = await remember.fn(fact="anything")
        assert "no memory" in out["error"]
    finally:
        context.set_turn(None)


async def test_a_store_that_did_not_answer_is_not_a_person_with_nothing_saved(store):
    """The difference a quiet recall failure loses: a tool that raises still
    produces a friendly reply, and "I don't have that saved" is indistinguishable
    from "I could not look"."""

    class Broken(InMemoryStore):
        async def search(self, *a, **kw):
            raise RuntimeError("connection refused")

    memory.set_store(Broken())
    with pytest.raises(memory.MemoryUnavailable):
        await memory.recall(1, "robin")

    context.set_turn(_turn())
    try:
        out = await remember.fn(topic="anything")
        assert "did not answer" in out["error"] and "could not check" in out["error"]
        assert "facts" not in out
    finally:
        context.set_turn(None)


async def test_the_memory_tool_joins_the_toolset_once_there_is_a_database(store):
    names = [getattr(t, "name", getattr(t, "__name__", "")) for t in toolset("robin")]
    assert "remember" in names


async def test_an_empty_fact_is_not_a_saved_one(store):
    context.set_turn(_turn())
    try:
        out = await remember.fn(fact="   ")
        # Whitespace is not a fact; it is also not a recall, because the model
        # asked to save. Either way nothing silently lands in the store.
        assert out.get("saved") is not True
    finally:
        context.set_turn(None)


class TestTheProbe:
    """Memory that has died says so without needing a model round trip."""

    async def test_it_writes_and_reads_back_by_meaning(self, store):
        out = await memory_health.check(force=True)
        assert out["ok"] is True and out["configured"] is True
        assert out["backend"] == "InMemoryStore"

    async def test_a_store_that_cannot_be_read_back_fails_the_probe(self, monkeypatch, store):
        class WriteOnly(InMemoryStore):
            async def search(self, *a, **kw):
                return []

        memory.set_store(WriteOnly())
        out = await memory_health.check(force=True)
        assert out["ok"] is False and "did not come back" in out["error"]

    async def test_no_database_is_reported_as_unconfigured_not_as_broken(self, monkeypatch):
        monkeypatch.delenv("LUACH_MEMORY_DSN", raising=False)
        memory.reset()
        out = await memory_health.check(force=True)
        assert out["configured"] is False and out["ok"] is None

    async def test_startup_never_raises_so_a_dead_memory_still_serves_a_calendar(self, store):
        class Broken(InMemoryStore):
            async def put(self, *a, **kw):
                raise RuntimeError("no such table")

        memory.set_store(Broken())
        await memory_health.probe_at_startup()  # must not raise
        out = await memory_health.check()
        assert out["ok"] is False

    async def test_it_is_on_the_health_details_for_members(self, api, store):
        await memory_health.refresh()
        assert (await api.get("/api/health")).json().get("memory") is None, "not public"
        await _login(api)
        body = (await api.get("/api/health/details")).json()
        assert body["ok"] is True
        assert body["memory"]["configured"] is True and body["memory"]["ok"] is True

    async def test_the_readiness_probe_keeps_the_verdict_fresh(self, api, store):
        """The probe used to be refreshed by the readiness probe's calls; it still is,
        though the public answer no longer carries it."""
        memory_health._status.update({"ok": None, "error": "", "checked_at": 0.0})
        await api.get("/api/health")
        await asyncio.sleep(0)
        for _ in range(50):
            if memory_health._status["ok"] is not None:
                break
            await asyncio.sleep(0.01)
        assert memory_health._status["ok"] is True

    async def test_health_never_waits_on_a_probe(self, api, store):
        """The readiness probe has a three second timeout and the first probe of
        a pod's life loads an ONNX model. A slow memory must not look like an
        unready luach."""

        class Slow(InMemoryStore):
            async def put(self, *a, **kw):
                await asyncio.sleep(5)

        memory.set_store(Slow())
        memory_health._status.update({"ok": None, "error": "", "checked_at": 0.0})
        body = await asyncio.wait_for(api.get("/api/health"), timeout=2)
        assert body.json()["ok"] is True
        await _login(api)
        body = await asyncio.wait_for(api.get("/api/health/details"), timeout=2)
        assert body.json()["memory"]["configured"] is True


class TestItIsTulipUnderneath:
    """The store, the fence and the agent are tulip's, not luach's own.

    Asserted rather than assumed: every one of these is a small, plausible
    thing to hand-roll in a hurry, and the point of building on tulip is lost
    the first time one of them quietly becomes a local copy.
    """

    def test_the_store_is_tulips_pgmemory(self, monkeypatch):
        from tulip.memory.store import BaseStore
        from tulip.memory.store_backends.postgresql import PgMemory

        monkeypatch.setenv("LUACH_MEMORY_DSN", "postgresql://luach@127.0.0.1/luach")
        memory.reset()
        # Built lazily, so this constructs the real thing without connecting.
        store = memory.get_store()
        assert isinstance(store, PgMemory)
        assert isinstance(store, BaseStore)

    def test_the_fence_around_a_recalled_fact_is_tulips(self):
        import inspect

        from tulip.memory import scrubber

        src = inspect.getsource(memory)
        assert "from tulip.memory.scrubber import sanitize_context" in src
        assert "from tulip.memory.scrubber import build_memory_context_block" in src
        assert callable(scrubber.build_memory_context_block)

    def test_the_embedder_speaks_tulips_embedding_protocol(self):
        from tulip.rag.embeddings.base import EmbeddingResult

        from luach import embeddings

        assert EmbeddingResult.__module__.startswith("tulip.")
        for name in ("embed", "embed_query", "embed_documents", "embed_batch"):
            assert hasattr(embeddings.LocalEmbeddings, name)

    def test_the_agent_and_its_thread_state_are_tulips(self):
        from tulip.agent import Agent
        from tulip.memory.backends.file import FileCheckpointer

        runtime.set_model(object())
        agent = runtime.build_agent("robin")
        assert isinstance(agent, Agent)
        assert isinstance(runtime.get_checkpointer(), FileCheckpointer)

    def test_every_tool_is_declared_with_tulips_decorator(self):
        from luach.agent import tools

        for t in tools.READ_TOOLS + list(tools.WRITE_TOOLS.values()) + [remember]:
            # tulip's @tool wraps the function and keeps the original at .fn.
            assert hasattr(t, "fn"), t
            assert type(t).__module__.startswith("tulip.")


# -- managing it -----------------------------------------------------------------


async def test_every_turn_starts_knowing_what_was_said(store):
    """Recall waited for the model to think of it; the facts now ride with the turn."""
    from tests.doubles import ScriptedModel, call, say

    await memory.remember(1, "robin", "I only book appointments in the morning", "appointments")
    model = ScriptedModel([[call("just_talking", about="hi")], [say("Morning it is.")]])
    runtime.set_model(model)
    await runtime.run_turn("hi", user_id=1, principal="robin", timezone="America/New_York")
    first = "".join(str(m.content or "") for m in model.calls[0]["messages"])
    assert "I only book appointments in the morning" in first


async def test_a_turn_goes_on_when_memory_is_down(store, monkeypatch):
    from tests.doubles import ScriptedModel, call, say

    async def broken(*_a, **_k):
        raise memory.MemoryUnavailable("the database is gone")

    monkeypatch.setattr(memory, "recall", broken)
    runtime.set_model(ScriptedModel([[call("just_talking", about="hi")], [say("Hi.")]]))
    r = await runtime.run_turn("hi", user_id=1, principal="robin", timezone="America/New_York")
    assert r.reply == "Hi." and not r.error


async def test_forget_by_chat(store):
    await memory.remember(1, "robin", "I can never do Tuesdays", "tuesdays")
    await memory.remember(1, "robin", "Ruby finishes school at 3:30", "school")
    context.set_turn(_turn())
    from luach.agent.tools import forget

    r = await forget.fn(what="tuesdays")
    left = await memory.recall(1, "robin")
    assert r["forgotten"] is True and [f["fact"] for f in left["facts"]] == [
        "Ruby finishes school at 3:30"
    ]


async def test_forget_drops_only_a_fact_it_is_about(store, monkeypatch):
    """Recall ranks; it always has a nearest fact. "forget that I like pizza", with
    nothing about pizza saved, dropped the nearest one — on pgvector that was "We
    keep Friday nights clear" — and said it had forgotten something."""
    await memory.remember(1, "robin", "We keep Friday nights clear", "fridays")
    await memory.remember(1, "robin", "I only book appointments in the morning", "appointments")
    context.set_turn(_turn())
    from luach.agent.tools import forget

    recall = memory.recall

    async def ranked(user_id, principal, topic="", limit=memory.RECALL_LIMIT):
        # pgvector's answer to any query: everything, nearest first.
        return await recall(user_id, principal, "", limit)

    monkeypatch.setattr(memory, "recall", ranked)
    r = await forget.fn(what="that I like pizza")
    assert r["forgotten"] is False and len(r["saved"]) == 2
    r = await forget.fn(what="I can book mornings and afternoons now")
    assert r["forgotten"] is True and "morning" in r["fact"]
    left = await recall(1, "robin")
    assert [f["fact"] for f in left["facts"]] == ["We keep Friday nights clear"]


def test_a_fact_is_matched_by_what_it_is_about_not_how_it_is_held():
    facts = [
        {"key": "only-mornings", "topic": "", "fact": "I only book appointments in the morning"},
        {"key": "tuesdays", "topic": "tuesdays", "fact": "I can never do Tuesdays"},
    ]
    assert memory.matching(facts, "I can do Tuesdays now") is facts[1]
    assert memory.matching(facts, "forget that I only book mornings") is facts[0]
    assert memory.matching(facts, "only-mornings") is facts[0]
    assert memory.matching(facts, "I only eat fish, never meat") is None


async def test_every_fact_rides_with_the_turn_and_is_listed_not_just_ten(api, store):
    """Recall without a topic is the ten most recent: the eleventh fact a member
    gave was never seen again, by the model or on their own memory page."""
    for n in range(12):
        await memory.remember(1, "robin", f"Standing rule number {n}", f"rule {n}")
    known = await memory.known(1, "robin")
    assert all(f"Standing rule number {n}" in known for n in range(12))
    await api.post(
        "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
    )
    assert len((await api.get("/api/memory")).json()["facts"]) == 12


async def test_a_member_sees_adds_and_removes_their_own(api, store):
    await memory.remember(2, "ana", "Ana's own fact", "ana")
    await api.post(
        "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
    )
    assert (await api.get("/api/memory")).json() == {"facts": []}  # not Ana's
    made = (await api.post("/api/memory", json={"fact": "We keep Friday nights clear"})).json()
    (fact,) = made["facts"]
    assert fact["fact"] == "We keep Friday nights clear"
    gone = await api.delete(f"/api/memory/{fact['key']}")
    assert gone.json() == {"ok": True, "facts": []}
    assert (await api.delete("/api/memory/nothing-here")).status_code == 404
    assert [f["fact"] for f in (await memory.recall(2, "ana"))["facts"]] == ["Ana's own fact"]


async def test_no_memory_here_says_so(api, monkeypatch):
    monkeypatch.delenv("LUACH_MEMORY_DSN", raising=False)
    await api.post(
        "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
    )
    r = await api.get("/api/memory")
    assert r.status_code == 503 and "no memory" in r.json()["error"]

"""The owner's model menu: managed in the app, tried before it joins, watched after.

Every route is the owner's, signed in; a member, both service keys and a stranger
are refused. A model its provider refuses is marked not answering, the owner is
told, and members who picked it go back to the household's model and hear so on
their next answer. "Try it" runs in a child process on a store of its own.
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from luach import (
    config,
    db,
    model_catalogue,
    model_health,
    model_menu,
    model_trials,
    public_pages,
    push,
)
from luach.agent import runtime, trial_evals
from luach.app import create_app
from tests.doubles import ScriptedModel, call, say

TZ = "America/New_York"
SERVICE_KEY = "service-0123456789abcdef0123456789abcdef"
TULIP_KEY = "tulip-0123456789abcdef0123456789abcdef"
HOME = "qwen3.6-35b"
CLOUD = "openrouter/deepseek/deepseek-v4-flash"
GEMINI = "openrouter/google/gemini-3.8-flash"
MENU = [
    {"id": HOME, "name": "At home", "about": "Runs at home.", "local": True},
    {"id": CLOUD, "name": "DeepSeek", "about": "Fast."},
]


@pytest.fixture(autouse=True)
def menu(monkeypatch):
    monkeypatch.setenv("LUACH_MODELS", json.dumps(MENU))
    model_menu.seed()


async def _client(tmp_path, username: str, password: str):
    app = create_app(static_dir=tmp_path / "nope")
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test")
    r = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return c


@pytest.fixture
async def owner(tmp_path):
    c = await _client(tmp_path, "robin", "correct horse battery")
    yield c
    await c.aclose()


@pytest.fixture
async def member(tmp_path):
    c = await _client(tmp_path, "ana", "another good password")
    yield c
    await c.aclose()


@pytest.fixture
async def anyone(tmp_path, monkeypatch):
    monkeypatch.setenv("LUACH_API_KEY", SERVICE_KEY)
    monkeypatch.setenv("LUACH_TULIP_KEY", TULIP_KEY)
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


@pytest.fixture
def told(monkeypatch) -> list[tuple[str, str]]:
    """What the owner was pushed."""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        push, "notify_user", lambda uid, title, body, url="/": sent.append((title, body)) or 1
    )
    return sent


@pytest.fixture
def probe(monkeypatch) -> dict[str, Any]:
    """The tiny request to a model, answered as a test says."""
    answer: dict[str, Any] = {"ok": True, "why": "", "asked": []}

    async def fake(model_id: str) -> tuple[bool, str]:
        answer["asked"].append(model_id)
        return answer["ok"], answer["why"]

    monkeypatch.setattr(model_health, "probe", fake)
    return answer


def _uid(username: str) -> int:
    with db.session() as s:
        return s.query(db.User).filter_by(username=username).one().id


def _pick(username: str, model_id: str) -> None:
    with db.session() as s:
        s.query(db.User).filter_by(username=username).one().model = model_id


# --- who may ---------------------------------------------------------------------

ROUTES: list[tuple[str, str, dict | None]] = [
    ("GET", "/api/models/manage", None),
    ("POST", "/api/models/manage", {"id": "x/y", "try": False}),
    ("PATCH", "/api/models/manage", {"id": CLOUD, "enabled": False}),
    ("POST", "/api/models/manage/remove", {"id": CLOUD}),
    ("PUT", "/api/models/manage/order", {"ids": [CLOUD, HOME]}),
    ("PUT", "/api/models/manage/default", {"id": CLOUD}),
    ("GET", "/api/models/manage/trial", None),
    ("POST", "/api/models/manage/trial", {"id": CLOUD}),
    ("POST", "/api/models/manage/trial/cancel", {}),
    ("POST", "/api/models/manage/check", {"id": CLOUD}),
    ("GET", "/api/models/catalogue?q=x", None),
]


class TestOnlyTheOwner:
    @pytest.mark.parametrize(("method", "path", "payload"), ROUTES)
    async def test_a_member_is_refused(self, member, method, path, payload):
        r = await member.request(method, path, json=payload)
        assert r.status_code == 403, r.text
        assert model_menu.get(CLOUD) is not None and model_menu.get("x/y") is None

    @pytest.mark.parametrize(("method", "path", "payload"), ROUTES)
    async def test_the_tulip_key_is_refused(self, anyone, method, path, payload):
        r = await anyone.request(method, path, json=payload, headers={"x-luach-key": TULIP_KEY})
        assert r.status_code == 403

    @pytest.mark.parametrize(("method", "path", "payload"), ROUTES)
    async def test_the_service_key_is_refused(self, anyone, method, path, payload):
        """It acts as the owner for a chat bot; which models see the family's
        questions is not a bot's decision."""
        r = await anyone.request(method, path, json=payload, headers={"x-luach-key": SERVICE_KEY})
        assert r.status_code == 403

    async def test_the_route_refuses_a_key_the_wall_let_through(self, monkeypatch):
        """Two locks: were the wall's list ever to miss a route, the route still refuses."""
        from luach.auth.current import Caller, set_caller
        from luach.routes import models as model_routes
        from luach.routes.shared import error

        set_caller(Caller(user_id=_uid("robin"), principal="service", via_key=True))
        try:
            with pytest.raises(type(error(403, "x"))) as refused:
                model_routes.require_owner_in_person()
            assert refused.value.status_code == 403
            assert "owner, signed in" in str(refused.value.detail)
        finally:
            set_caller(None)

    @pytest.mark.parametrize(("method", "path", "payload"), ROUTES)
    async def test_a_stranger_is_refused(self, anyone, method, path, payload):
        assert (await anyone.request(method, path, json=payload)).status_code == 401


# --- the owner manages it ------------------------------------------------------------


class TestManaging:
    async def test_the_list_says_everything(self, owner):
        body = (await owner.get("/api/models/manage")).json()
        assert body["default"] == HOME and body["configured"] is True
        assert [m["id"] for m in body["models"]] == [HOME, CLOUD]
        home, cloud = body["models"]
        assert home["is_default"] and home["local"] and home["provider"] == ""
        assert cloud["provider"] == "DeepSeek, through OpenRouter"
        assert cloud["enabled"] and cloud["health"]["status"] == "ok"
        assert body["trials_left_today"] == config.model_trials_per_day()
        assert body["catalogue"] == {"configured": True, "source": "models.test"}

    async def test_an_added_model_waits_for_the_owner(self, owner, member):
        r = await owner.post(
            "/api/models/manage",
            json={"id": GEMINI, "name": "Gemini", "about": "Google's.", "try": False},
        )
        assert r.status_code == 200, r.text
        assert r.json()["added"] == GEMINI and r.json()["trial_started"] is False
        added = next(m for m in r.json()["models"] if m["id"] == GEMINI)
        assert added["enabled"] is False and added["provider"] == "Google, through OpenRouter"
        assert GEMINI not in (await member.get("/api/models")).json()["models"]
        assert (await member.patch("/api/auth/me", json={"model": GEMINI})).status_code == 400
        r = await owner.patch("/api/models/manage", json={"id": GEMINI, "enabled": True})
        assert r.status_code == 200
        assert (await member.get("/api/models")).json()["models"] == [HOME, CLOUD, GEMINI]
        assert (await member.patch("/api/auth/me", json={"model": GEMINI})).json()[
            "model"
        ] == GEMINI

    async def test_adding_starts_a_trial(self, owner, monkeypatch):
        started: list[str] = []
        monkeypatch.setattr(
            model_trials, "start", lambda model_id, by: started.append(model_id) or {}
        )
        r = await owner.post("/api/models/manage", json={"id": GEMINI})
        assert r.json()["trial_started"] is True and started == [GEMINI]

    async def test_adding_says_why_no_trial_started(self, owner, monkeypatch):
        def refuse(model_id: str, by: str) -> dict:
            raise model_trials.TrialError("that is the 6 trials allowed in a day")

        monkeypatch.setattr(model_trials, "start", refuse)
        r = await owner.post("/api/models/manage", json={"id": GEMINI})
        assert r.status_code == 200 and "6 trials" in r.json()["note"]

    async def test_the_catalogue_fills_in_what_it_knows(self, owner, monkeypatch):
        monkeypatch.setattr(
            model_catalogue,
            "lookup",
            lambda model_id: {
                "id": model_id,
                "name": "Google: Gemini 3.8 Flash",
                "context_length": 1048576,
                "tools": True,
                "price_in": 0.3,
                "price_out": 2.5,
                "alias": False,
                "provider": "x",
                "evil": "<script>",
            },
        )
        r = await owner.post("/api/models/manage", json={"id": GEMINI, "try": False})
        added = next(m for m in r.json()["models"] if m["id"] == GEMINI)
        assert added["name"] == "Google: Gemini 3.8 Flash"
        assert added["meta"] == {
            "context_length": 1048576,
            "price_in": 0.3,
            "price_out": 2.5,
            "tools": True,
        }

    @pytest.mark.parametrize(
        "bad",
        [
            "anthropic:claude",
            "two words",
            "x" * 129,
            "",
            "-leading-dash",
            "a//b",
            "café/model",
            "line\nbreak",
            7,
            None,
        ],
    )
    async def test_an_id_that_is_not_one_is_refused(self, owner, bad):
        r = await owner.post("/api/models/manage", json={"id": bad, "try": False})
        assert r.status_code == 400
        assert "model id" in r.text

    @pytest.mark.parametrize(
        "payload",
        [
            {"name": "x" * 61},
            {"about": "x" * 301},
            {"provider": "x" * 81},
            {"name": 7},
            {"local": "yes"},
        ],
    )
    async def test_fields_are_checked(self, owner, payload):
        r = await owner.post("/api/models/manage", json={"id": GEMINI, "try": False, **payload})
        assert r.status_code == 400
        assert model_menu.get(GEMINI) is None

    async def test_one_model_once(self, owner):
        r = await owner.post("/api/models/manage", json={"id": CLOUD, "try": False})
        assert r.status_code == 400 and "already" in r.text

    async def test_a_list_has_room_for_thirty(self, owner, monkeypatch):
        monkeypatch.setattr(model_menu, "MAX_MODELS", 2)
        r = await owner.post("/api/models/manage", json={"id": GEMINI, "try": False})
        assert r.status_code == 400 and "at most 2" in r.text

    async def test_edit(self, owner):
        r = await owner.patch(
            "/api/models/manage",
            json={
                "id": CLOUD,
                "name": "  DeepSeek   V4 ",
                "about": "Quick.",
                "provider": "DeepSeek",
            },
        )
        cloud = next(m for m in r.json()["models"] if m["id"] == CLOUD)
        assert (cloud["name"], cloud["about"], cloud["provider"]) == (
            "DeepSeek V4",
            "Quick.",
            "DeepSeek",
        )
        assert (await owner.patch("/api/models/manage", json={"id": CLOUD})).status_code == 400
        r = await owner.patch("/api/models/manage", json={"id": "nope/x", "name": "x"})
        assert r.status_code == 400 and "not on the list" in r.text
        r = await owner.patch("/api/models/manage", json={"id": CLOUD, "name": " "})
        assert r.status_code == 400

    async def test_the_default_stays_on(self, owner):
        r = await owner.patch("/api/models/manage", json={"id": HOME, "enabled": False})
        assert r.status_code == 400 and "default" in r.text
        r = await owner.post("/api/models/manage/remove", json={"id": HOME})
        assert r.status_code == 400 and "default" in r.text

    async def test_reorder(self, owner, member):
        r = await owner.put("/api/models/manage/order", json={"ids": [CLOUD, HOME]})
        assert [m["id"] for m in r.json()["models"]] == [CLOUD, HOME]
        # The members' menu still starts with the household's default.
        assert (await member.get("/api/models")).json()["models"] == [HOME, CLOUD]
        for bad in ([CLOUD], [CLOUD, CLOUD, HOME], [CLOUD, HOME, "x"], "nope", [1, 2]):
            assert (
                await owner.put("/api/models/manage/order", json={"ids": bad})
            ).status_code == 400

    async def test_a_new_default(self, owner, member, monkeypatch):
        monkeypatch.setenv("LUACH_MODEL", "moved-by-an-operator")
        _pick("ana", CLOUD)
        r = await owner.put("/api/models/manage/default", json={"id": CLOUD})
        assert r.status_code == 200 and r.json()["default"] == CLOUD
        # The app's choice wins over the deployment's starting value.
        assert model_menu.default_id() == CLOUD
        body = (await member.get("/api/models")).json()
        assert body["default"] == CLOUD and body["models"][0] == CLOUD
        assert body["chosen"] == ""
        runtime.set_model(None)
        assert runtime.clean_model(model_menu.default_id()) == CLOUD
        r = await owner.put("/api/models/manage/default", json={"id": "nope/x"})
        assert r.status_code == 400

    async def test_a_model_not_answering_cannot_be_the_default(self, owner):
        model_health.mark_unhealthy(CLOUD, "404: gone")
        r = await owner.put("/api/models/manage/default", json={"id": CLOUD})
        assert r.status_code == 400 and "not answering" in r.text

    async def test_removing_moves_its_members_and_tells_them(self, owner, calendar):
        _pick("ana", CLOUD)
        r = await owner.post("/api/models/manage/remove", json={"id": CLOUD})
        assert [m["id"] for m in r.json()["models"]] == [HOME]
        assert db.get_user(_uid("ana")).model == ""
        runtime.set_model(ScriptedModel([[call("just_talking", about="hi")], [say("Hi!")]]))
        done = await runtime.run_turn("hi", user_id=_uid("ana"), principal="ana", timezone=TZ)
        assert done.reply.startswith(
            "(A note first: DeepSeek, the model you picked, was taken off the menu"
        )
        assert done.reply.endswith("Hi!")
        runtime.set_model(ScriptedModel([[call("just_talking", about="hi")], [say("Hi!")]]))
        again = await runtime.run_turn("hi", user_id=_uid("ana"), principal="ana", timezone=TZ)
        assert again.reply == "Hi!"

    async def test_disabling_moves_its_members_too(self, owner):
        _pick("ana", CLOUD)
        await owner.patch("/api/models/manage", json={"id": CLOUD, "enabled": False})
        assert db.get_user(_uid("ana")).model == ""
        assert "taken off the menu" in model_menu.note_for(_uid("ana"))

    async def test_changes_are_on_the_audit_trail(self, owner):
        await owner.post("/api/models/manage", json={"id": GEMINI, "try": False})
        await owner.put("/api/models/manage/default", json={"id": CLOUD})
        with db.session() as s:
            kinds = [r.event_type for r in s.query(db.AuditRow).all()]
        assert "models.added" in kinds and "models.default" in kinds


# --- broken models are noticed ------------------------------------------------------------


class Refused(Exception):
    status_code = 404
    body = {
        "error": {
            "message": "No endpoints found for deepseek/deepseek-v4-flash. key sk-or-v1-abcdef0123456789abcdef"
        }
    }


class RefusingModel:
    async def stream(self, messages, tools=None, **kwargs):
        raise Refused("No endpoints found")
        yield  # pragma: no cover


class Flaky(Exception):
    pass


class FlakyModel:
    async def stream(self, messages, tools=None, **kwargs):
        raise Flaky("Connection reset by peer")
        yield  # pragma: no cover


class TestNotAnswering:
    async def test_a_refused_model_is_marked_and_its_members_moved(
        self, calendar, told, monkeypatch
    ):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-or-v1-abcdef0123456789abcdef")
        _pick("robin", CLOUD)
        _pick("ana", CLOUD)
        runtime.set_model(RefusingModel())
        failed = await runtime.run_turn("hi", user_id=_uid("robin"), principal="robin", timezone=TZ)
        assert failed.error.startswith("DeepSeek did not answer")
        assert "household's model answers you from now on" in failed.error
        cloud = model_menu.get(CLOUD)
        assert cloud is not None and not cloud.healthy
        assert cloud.unhealthy_reason.startswith(
            "its provider refused it — 404: No endpoints found"
        )
        # The provider's words reach the owner without the key in them.
        assert "abcdef0123456789" not in cloud.unhealthy_reason
        assert db.get_user(_uid("robin")).model == "" and db.get_user(_uid("ana")).model == ""
        assert len(told) == 1 and "DeepSeek is not answering" in told[0][1]
        assert "abcdef0123456789" not in told[0][1]
        # Robin heard it in the failed turn; Ana hears it on her next one.
        assert model_menu.note_for(_uid("robin")) == ""
        runtime.set_model(ScriptedModel([[call("just_talking", about="hi")], [say("Hi!")]]))
        ana = await runtime.run_turn("hi", user_id=_uid("ana"), principal="ana", timezone=TZ)
        assert "DeepSeek, the model you picked, was not answering" in ana.reply
        assert "At home, the household's model" in ana.reply

    async def test_the_menu_shows_it_and_members_cannot_pick_it(self, member):
        model_health.mark_unhealthy(CLOUD, "404: gone")
        body = (await member.get("/api/models")).json()
        cloud = next(c for c in body["catalogue"] if c["id"] == CLOUD)
        assert cloud["health"]["status"] == "not_answering" and cloud["health"]["since"]
        assert (await member.patch("/api/auth/me", json={"model": CLOUD})).status_code == 400
        assert model_menu.pick(CLOUD) == ""

    async def test_the_owner_is_mailed_when_mail_works(self, told, monkeypatch):
        from luach import mailer

        mailed: list[tuple[str, str]] = []
        monkeypatch.setattr(mailer, "configured", lambda: True)
        monkeypatch.setattr(
            mailer,
            "send",
            lambda to, subject, text, html=None: mailed.append((to, subject)) or True,
        )
        model_health.mark_unhealthy(CLOUD, "404: gone")
        assert mailed == [("robin@example.com", "luach: DeepSeek is not answering")]
        # Once: a model already marked is not news.
        model_health.mark_unhealthy(CLOUD, "404: still gone")
        assert len(mailed) == 1 and len(told) == 1
        assert model_menu.get(CLOUD).unhealthy_reason == "404: still gone"

    async def test_the_default_not_answering_moves_nobody(self, told):
        _pick("ana", CLOUD)
        model_health.mark_unhealthy(HOME, "404: gone")
        assert db.get_user(_uid("ana")).model == CLOUD
        assert "cannot answer anyone" in told[0][1]

    async def test_several_failures_in_a_row(self, calendar, told):
        _pick("ana", CLOUD)
        runtime.set_model(FlakyModel())
        for n in range(model_health.MAX_FAILURES):
            assert model_menu.get(CLOUD).healthy, f"marked after {n}"
            await runtime.run_turn("hi", user_id=_uid("ana"), principal="ana", timezone=TZ)
        cloud = model_menu.get(CLOUD)
        assert not cloud.healthy and "3 turns in a row failed" in cloud.unhealthy_reason
        assert len(told) == 1

    async def test_an_answer_in_between_starts_the_count_again(self, calendar):
        _pick("ana", CLOUD)
        for _ in range(model_health.MAX_FAILURES - 1):
            runtime.set_model(FlakyModel())
            await runtime.run_turn("hi", user_id=_uid("ana"), principal="ana", timezone=TZ)
        assert model_menu.get(CLOUD).failures == 2
        runtime.set_model(ScriptedModel([[call("just_talking", about="hi")], [say("Hi!")]]))
        await runtime.run_turn("hi", user_id=_uid("ana"), principal="ana", timezone=TZ)
        assert model_menu.get(CLOUD).failures == 0
        runtime.set_model(FlakyModel())
        await runtime.run_turn("hi", user_id=_uid("ana"), principal="ana", timezone=TZ)
        assert model_menu.get(CLOUD).healthy

    async def test_a_400_that_is_not_about_the_model_is_only_a_failure(self):
        class BadRequest(Exception):
            status_code = 400

        assert not model_health.refused(BadRequest("context length exceeded"))
        assert model_health.refused(BadRequest("Invalid model name passed in model=x"))
        assert model_health.refused(BadRequest("Endpoint has no deployments configured"))
        assert not model_health.failed("", BadRequest("x"))
        assert not model_health.failed("not/on-the-list", BadRequest("x"))

    async def test_a_check_brings_it_back(self, owner, probe):
        model_health.mark_unhealthy(CLOUD, "404: gone")
        probe["ok"] = True
        r = await owner.post("/api/models/manage/check", json={"id": CLOUD})
        assert r.json()["ok"] is True and r.json()["health"]["status"] == "ok"
        assert model_menu.get(CLOUD).healthy and model_menu.get(CLOUD).last_ok_at

    async def test_a_check_that_is_refused_marks_it(self, owner, probe, told):
        probe.update(ok=False, why="404: No endpoints found")
        r = await owner.post("/api/models/manage/check", json={"id": CLOUD})
        assert r.json()["ok"] is False and r.json()["health"]["status"] == "not_answering"
        assert (await owner.post("/api/models/manage/check", json={"id": "x/y"})).status_code == 404

    async def test_the_hourly_recheck(self, probe):
        model_health.mark_unhealthy(CLOUD, "404: gone")
        probe["ok"] = True
        assert await model_health.recheck_unhealthy() == 1
        assert probe["asked"] == [CLOUD] and model_menu.get(CLOUD).healthy

    async def test_a_later_answer_clears_it(self):
        model_health.mark_unhealthy(CLOUD, "404: gone")
        model_health.answered(CLOUD)
        assert model_menu.get(CLOUD).healthy

    def test_reasons_never_carry_a_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "plainkey123")
        exc = Refused("x")
        exc.body = {
            "error": {
                "message": "bad key plainkey123 for https://user:pw@host/v1 token=abcdefghijklmnopqrstuvwxyz"
            }
        }
        reason = model_health.reason_for(exc)
        assert "plainkey123" not in reason and "user:pw" not in reason
        assert "abcdefghijklmnop" not in reason


class TestProbe:
    async def test_it_asks_only_the_endpoint_with_its_key(self, monkeypatch):
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"choices": []})

        transport = httpx.MockTransport(handler)
        real = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))
        monkeypatch.setenv("OPENAI_API_KEY", "router-key")
        assert await model_health.probe(CLOUD) == (True, "")
        assert str(seen[0].url) == "http://models.test/v1/chat/completions"
        assert seen[0].headers["authorization"] == "Bearer router-key"
        assert json.loads(seen[0].content)["model"] == CLOUD

    async def test_what_a_refusal_looks_like(self, monkeypatch):
        transport = httpx.MockTransport(
            lambda r: httpx.Response(404, json={"error": {"message": "No endpoints found"}})
        )
        real = httpx.AsyncClient
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=transport, **kw))
        assert await model_health.probe(CLOUD) == (False, "404: No endpoints found")

    async def test_no_endpoint_no_probe(self, monkeypatch):
        monkeypatch.delenv("OPENAI_BASE_URL")
        ok, why = await model_health.probe(CLOUD)
        assert not ok and "OPENAI_BASE_URL" in why
        monkeypatch.setenv("OPENAI_BASE_URL", "http://models.test/v1")
        assert await model_health.probe("evil:model") == (False, "not a model id")


# --- no model at all -------------------------------------------------------------------


class TestNoModel:
    @pytest.mark.parametrize("unset", ["LUACH_MODEL", "OPENAI_BASE_URL"])
    async def test_the_assistant_says_so(self, emptied, calendar, monkeypatch, unset, tmp_path):
        monkeypatch.delenv(unset)
        monkeypatch.delenv("LUACH_MODELS")
        db.init_db(emptied)
        from luach.auth import users

        users.create_user("robin", "robin@example.com", "correct horse battery")
        model_menu.seed()

        class Boom:
            async def stream(self, *a, **k):
                raise AssertionError("a model was asked")
                yield  # pragma: no cover

        runtime.set_model(Boom())
        done = await runtime.run_turn("hi", user_id=_uid("robin"), principal="robin", timezone=TZ)
        assert done.reply == runtime.NO_MODEL and not done.error
        assert "Settings › Household › Models" in done.reply
        c = await _client(tmp_path, "robin", "correct horse battery")
        details = (await c.get("/api/health/details")).json()
        assert details["model"] == "not configured"
        assert (await c.get("/api/models")).json()["configured"] is False
        # The rest of the house works.
        assert (await c.get("/api/family")).status_code == 200
        assert (
            await c.get("/api/calendar/events?start=2026-01-01&end=2026-01-02")
        ).status_code == 200
        await c.aclose()

    def test_no_model_no_client(self, monkeypatch):
        monkeypatch.delenv("LUACH_MODEL")
        runtime.reset()
        with pytest.raises(runtime.NoModel):
            runtime.get_model()

    def test_there_is_no_built_in_model_or_server(self, monkeypatch):
        monkeypatch.delenv("LUACH_MODEL")
        monkeypatch.delenv("OPENAI_BASE_URL")
        assert config.model_id() == "" and config.model_base_url() == ""
        assert config.model_catalogue_url() == ""

    async def test_startup_says_so_once(self, emptied, monkeypatch, caplog, tmp_path):
        import logging

        from luach import app as app_module

        monkeypatch.delenv("LUACH_MODEL")
        monkeypatch.delenv("LUACH_MODELS")
        db.init_db(emptied)
        monkeypatch.setattr(app_module, "_run_the_loops", lambda: asyncio.sleep(0))
        application = create_app(static_dir=tmp_path / "nope")
        with caplog.at_level(logging.WARNING):
            async with app_module.lifespan(application):
                pass
        assert caplog.text.count("no model is configured") == 1

    async def test_the_details_name_the_model_when_there_is_one(self, owner):
        details = (await owner.get("/api/health/details")).json()
        assert details["model"] == {"id": HOME, "base_url": "http://models.test/v1"}


# --- the privacy page --------------------------------------------------------------------


class TestPrivacy:
    def test_the_paragraph_names_each_model_and_who_runs_it(self, monkeypatch):
        model_menu.add(GEMINI, name="Gemini")
        model_menu.update(GEMINI, enabled=True)
        model_menu.add("cloud-deepseek", name="Router DeepSeek")
        model_menu.update("cloud-deepseek", enabled=True)
        text = public_pages.values()["models"]
        assert "At home, which runs on the household&#x27;s own computer" in text or (
            "At home, which runs on the household's own computer" in text
        )
        assert "DeepSeek, at DeepSeek, through OpenRouter" in text
        assert "Gemini, at Google, through OpenRouter" in text
        assert "Router DeepSeek, at a cloud provider" in text
        assert "API terms" in text

    def test_a_model_off_the_menu_is_not_named(self):
        model_menu.add(GEMINI, name="Gemini")
        assert "Gemini" not in public_pages.values()["models"]

    def test_the_owners_words_win(self, monkeypatch):
        monkeypatch.setenv("LUACH_PRIVACY_MODELS", "Our own words <b>.")
        assert public_pages.values()["models"] == "Our own words &lt;b&gt;."

    def test_only_at_home(self):
        model_menu.update(CLOUD, enabled=False)
        text = public_pages.values()["models"]
        assert "API terms" not in text and "nothing leaves the house" in text

    def test_without_a_model_the_general_paragraph(self, monkeypatch):
        monkeypatch.delenv("OPENAI_BASE_URL")
        assert public_pages.values()["models"] == public_pages._e(public_pages.DEFAULT_MODELS)

    def test_a_store_that_cannot_be_read_still_serves_the_page(self, monkeypatch):
        def boom() -> str:
            raise RuntimeError("db down")

        monkeypatch.setattr(model_menu, "privacy_paragraph", boom)
        assert public_pages.values()["models"] == public_pages._e(public_pages.DEFAULT_MODELS)

    @pytest.mark.parametrize(
        ("model_id", "base", "said"),
        [
            ("openrouter/google/gemini-3.8-flash", "", "Google, through OpenRouter"),
            ("together_ai/deepseek-ai/x", "", "Deepseek Ai, through Together AI"),
            ("openrouter/x", "", "OpenRouter"),
            (
                "google/gemini-3.8-flash",
                "https://openrouter.ai/api/v1",
                "Google, through OpenRouter",
            ),
            (
                "~deepseek/deepseek-flash-latest",
                "https://openrouter.ai/api/v1",
                "DeepSeek, through OpenRouter",
            ),
            ("anthropic/claude-x", "https://api.example/v1", "Anthropic"),
            ("plain-name", "", ""),
        ],
    )
    def test_who_runs_it_from_the_id(self, monkeypatch, model_id, base, said):
        if base:
            monkeypatch.setenv("OPENAI_BASE_URL", base)
        assert model_menu.provider_label(model_menu.Choice(model_id, "", "")) == said


# --- the catalogue ------------------------------------------------------------------------

OPENROUTER = {
    "data": [
        {
            "id": "google/gemini-3.8-flash",
            "name": "Google: Gemini 3.8 Flash",
            "context_length": 1048576,
            "pricing": {"prompt": "0.0000003", "completion": "0.0000025"},
            "supported_parameters": ["tools", "temperature"],
        },
        {
            "id": "~deepseek/deepseek-flash-latest",
            "name": "DeepSeek: Flash (latest)",
            "top_provider": {"context_length": 131072},
            "pricing": {"prompt": "0.0000001", "completion": "nope"},
            "supported_parameters": ["tools"],
        },
        {
            "id": "deepseek/deepseek-flash-0731",
            "name": "DeepSeek: Flash 0731",
            "supported_parameters": [],
        },
        {"id": "meta/x:free", "name": "has a colon"},
        {"id": "*", "name": "a wildcard"},
        {"id": 7},
        "junk",
    ]
}


class Seen(list):
    """The requests the catalogue's server was sent, and how it answers."""

    answer: dict[str, Any]


@pytest.fixture
def catalogue(monkeypatch) -> Seen:
    """The catalogue's server, as a test answers it; the requests it was sent."""
    seen = Seen()
    answer: dict[str, Any] = {"status": 200, "json": OPENROUTER}
    seen.answer = answer

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "content" in answer:
            return httpx.Response(answer["status"], content=answer["content"])
        return httpx.Response(answer["status"], json=answer["json"], headers=answer.get("headers"))

    transport = httpx.MockTransport(handler)
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=transport, **kw))
    return seen


class TestCatalogue:
    async def test_search_with_a_prefix_aliases_first(self, owner, catalogue, monkeypatch):
        monkeypatch.setenv("LUACH_MODEL_CATALOGUE_URL", "https://openrouter.ai/api/v1/models")
        monkeypatch.setenv("LUACH_MODEL_CATALOGUE_PREFIX", "openrouter/")
        r = await owner.get("/api/models/catalogue?q=")
        body = r.json()
        assert body["source"] == "openrouter.ai" and not body["error"]
        ids = [m["id"] for m in body["models"]]
        assert ids[0] == "openrouter/~deepseek/deepseek-flash-latest"
        assert set(ids) == {
            "openrouter/~deepseek/deepseek-flash-latest",
            "openrouter/google/gemini-3.8-flash",
            "openrouter/deepseek/deepseek-flash-0731",
        }
        alias = body["models"][0]
        assert alias["alias"] and alias["recommended"] and alias["context_length"] == 131072
        assert alias["price_in"] == 0.1 and alias["price_out"] is None
        gem = next(m for m in body["models"] if "gemini" in m["id"])
        assert gem["tools"] is True and gem["price_in"] == 0.3 and gem["price_out"] == 2.5
        assert gem["provider"] == "Google, through OpenRouter"
        pinned = next(m for m in body["models"] if m["id"].endswith("0731"))
        assert pinned["tools"] is False
        assert pinned["alias_of_it"] == "openrouter/~deepseek/deepseek-flash-latest"
        # The key for the model server never goes to another host.
        assert "authorization" not in catalogue[0].headers

    async def test_words_narrow_it(self, owner, catalogue):
        body = (await owner.get("/api/models/catalogue?q=gemini flash")).json()
        assert [m["id"] for m in body["models"]] == ["google/gemini-3.8-flash"]
        assert (await owner.get("/api/models/catalogue?q=nothing-like-it")).json()["models"] == []

    async def test_the_endpoints_own_list_gets_its_key(self, owner, catalogue, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "router-key")
        await owner.get("/api/models/catalogue")
        assert str(catalogue[0].url) == "http://models.test/v1/models"
        assert catalogue[0].headers["authorization"] == "Bearer router-key"

    async def test_it_is_kept_a_while(self, owner, catalogue):
        await owner.get("/api/models/catalogue?q=a")
        await owner.get("/api/models/catalogue?q=b")
        assert len(catalogue) == 1
        await owner.get("/api/models/catalogue?fresh=true")
        assert len(catalogue) == 2

    async def test_on_the_menu_is_marked(self, owner, catalogue):
        model_menu.add("google/gemini-3.8-flash")
        body = (await owner.get("/api/models/catalogue?q=gemini")).json()
        assert body["models"][0]["on_menu"] is True

    @pytest.mark.parametrize(
        ("answer", "said"),
        [
            ({"status": 500, "json": {}}, "answered 500"),
            (
                {"status": 302, "json": {}, "headers": {"location": "http://169.254.169.254/"}},
                "answered 302",
            ),
            ({"status": 200, "content": b"<html>"}, "did not send a list"),
            ({"status": 200, "json": {"data": "nope"}}, "did not send a list"),
        ],
    )
    async def test_a_bad_answer_is_said_not_raised(self, owner, catalogue, answer, said):
        catalogue.answer.clear()
        catalogue.answer.update(answer)
        body = (await owner.get("/api/models/catalogue")).json()
        assert body["models"] == [] and said in body["error"]
        # A redirect is not followed anywhere.
        assert len(catalogue) == 1

    async def test_too_large_is_refused(self, owner, catalogue, monkeypatch):
        monkeypatch.setattr(model_catalogue, "MAX_BYTES", 100)
        body = (await owner.get("/api/models/catalogue")).json()
        assert "too large" in body["error"]

    async def test_unreachable(self, owner, monkeypatch):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("no route", request=request)

        real = httpx.Client
        monkeypatch.setattr(
            httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
        )
        body = (await owner.get("/api/models/catalogue")).json()
        assert body["error"] == "could not reach models.test (ConnectError)"

    async def test_nothing_configured(self, owner, monkeypatch):
        monkeypatch.delenv("OPENAI_BASE_URL")
        body = (await owner.get("/api/models/catalogue")).json()
        assert body == {"configured": False, "source": "", "models": [], "error": ""}

    @pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://x", "not a url", "https://"])
    def test_only_http_addresses(self, monkeypatch, url):
        monkeypatch.setenv("LUACH_MODEL_CATALOGUE_URL", url)
        assert model_catalogue.source() is None

    async def test_a_request_cannot_choose_the_address(self, owner, catalogue):
        """No parameter names a URL: whatever is sent, the configured one is asked."""
        await owner.get("/api/models/catalogue?url=http://169.254.169.254/&q=x&source=evil")
        assert [str(r.url) for r in catalogue] == ["http://models.test/v1/models"]

    def test_lookup(self, catalogue):
        assert model_catalogue.lookup("google/gemini-3.8-flash")["context_length"] == 1048576
        assert model_catalogue.lookup("nope") is None

    def test_lookup_without_a_catalogue(self, monkeypatch):
        monkeypatch.delenv("OPENAI_BASE_URL")
        assert model_catalogue.lookup("x") is None

    @pytest.mark.parametrize(
        ("model_id", "alias"),
        [("~a/b", True), ("openrouter/~a/b", True), ("a/b-latest", True), ("a/b-0731", False)],
    )
    def test_aliases(self, model_id, alias):
        assert model_catalogue.is_alias(model_id) is alias

    def test_a_bare_list(self):
        assert [m["id"] for m in model_catalogue.parse([{"id": "a"}])] == ["a"]
        with pytest.raises(model_catalogue.CatalogueError):
            model_catalogue.parse("nope")


# --- Try it ------------------------------------------------------------------------------

STAND_IN = textwrap.dedent(
    """
    import json, os, sys, time
    env = dict(os.environ)
    with open(os.path.join(env["HOME"], "..", "env.json"), "w") as f:
        json.dump(env, f)
    mode = env.get("STAND_IN_MODE", "")
    for n in range(12):
        ok = mode != "half" or n % 2 == 0
        print(json.dumps({"case": f"c{n}", "about": "a case", "ok": ok, "problems": [] if ok else ["turn 1: no tool"], "tools": [["just_talking"]]}), flush=True)
        if mode == "slow":
            time.sleep(30)
        if mode == "crash" and n == 3:
            sys.exit(3)
    print(json.dumps({"summary": True}), flush=True)
    """
)


@pytest.fixture
def stand_in(tmp_path, monkeypatch, probe):
    """The child process replaced by a script that reports twelve cases."""
    script = tmp_path / "stand_in.py"
    script.write_text(STAND_IN)
    monkeypatch.setattr(model_trials, "COMMAND", [sys.executable, str(script)])
    # The stand-in writes beside its home, which is a temporary directory per run.
    monkeypatch.setattr(model_trials.tempfile, "mkdtemp", lambda prefix="": _home(tmp_path))
    return tmp_path


def _home(tmp_path) -> str:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return str(home)


async def _finish() -> None:
    assert model_trials._task is not None
    await asyncio.wait_for(model_trials._task, 30)


class TestTryIt:
    async def test_a_run_scores_and_is_kept(self, owner, stand_in):
        r = await owner.post("/api/models/manage/trial", json={"id": CLOUD})
        assert r.status_code == 200, r.text
        assert r.json()["trial"]["status"] == "running"
        await _finish()
        trial = (await owner.get("/api/models/manage/trial")).json()["trial"]
        assert trial["status"] == "done" and (trial["passed"], trial["total"]) == (12, 12)
        assert trial["verdict"] == "good" and len(trial["cases"]) == 12
        cloud = next(
            m for m in (await owner.get("/api/models/manage")).json()["models"] if m["id"] == CLOUD
        )
        assert cloud["trial"]["verdict"] == "good" and cloud["trial"]["at"]

    async def test_a_low_score_is_called_low(self, owner, stand_in, monkeypatch):
        monkeypatch.setenv("STAND_IN_MODE", "half")
        monkeypatch.setattr(model_trials, "INHERIT", (*model_trials.INHERIT, "STAND_IN_MODE"))
        await owner.post("/api/models/manage/trial", json={"id": CLOUD})
        await _finish()
        trial = model_trials.latest()
        assert (trial["passed"], trial["verdict"]) == (6, "low")
        assert model_trials.verdict(11, 12) == "fair" and model_trials.verdict(0, 0) == "none"

    async def test_the_child_gets_nothing_of_the_household(self, owner, stand_in, monkeypatch):
        monkeypatch.setenv("RESEND_API_KEY", "resend-secret")
        monkeypatch.setenv("LUACH_GOOGLE_SA_KEY", "/run/google.json")
        monkeypatch.setenv("LUACH_API_KEY", "service-secret")
        monkeypatch.setenv("LUACH_MEMORY_DSN", "postgresql://memory")
        monkeypatch.setenv("CREDENTIALS_DIRECTORY", "/run/credentials")
        monkeypatch.setenv("OPENAI_API_KEY", "model-key")
        household = config.database_url()
        await owner.post("/api/models/manage/trial", json={"id": CLOUD})
        await _finish()
        env = json.loads((stand_in / "env.json").read_text())
        assert env["LUACH_MODEL"] == CLOUD and env["OPENAI_API_KEY"] == "model-key"
        assert env["LUACH_CALENDAR"] == "fake" and env["LUACH_SEARCH_URL"] == ""
        assert env["LUACH_TRIAL"] == "1"
        for name in (
            "RESEND_API_KEY",
            "LUACH_GOOGLE_SA_KEY",
            "LUACH_API_KEY",
            "LUACH_MEMORY_DSN",
            "CREDENTIALS_DIRECTORY",
            "LUACH_MODELS",
        ):
            assert name not in env
        assert env["LUACH_DATABASE_URL"] != household
        assert (
            "search_path%3Dluach_trial_" in env["LUACH_DATABASE_URL"]
            or "search_path=luach_trial_" in env["LUACH_DATABASE_URL"]
        )
        # Its schema is gone when it ends.
        import psycopg

        with psycopg.connect(household) as conn:
            left = conn.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'luach_trial_%'"
            ).fetchall()
        assert left == []

    async def test_one_at_a_time(self, owner, stand_in, monkeypatch):
        monkeypatch.setenv("STAND_IN_MODE", "slow")
        monkeypatch.setattr(model_trials, "INHERIT", (*model_trials.INHERIT, "STAND_IN_MODE"))
        assert (await owner.post("/api/models/manage/trial", json={"id": CLOUD})).status_code == 200
        r = await owner.post("/api/models/manage/trial", json={"id": HOME})
        assert r.status_code == 409 and "already running" in r.text
        # Cancelled, the process is stopped and the run says so.
        for _ in range(100):
            if model_trials._process is not None:
                break
            await asyncio.sleep(0.05)
        child = model_trials._process
        r = await owner.post("/api/models/manage/trial/cancel", json={})
        assert r.json()["cancelled"] is True
        assert r.json()["trial"]["status"] == "cancelled"
        assert child is not None and child.returncode is not None
        assert (await owner.post("/api/models/manage/trial/cancel", json={})).json()[
            "cancelled"
        ] is False

    async def test_a_day_has_a_cap(self, owner, stand_in, monkeypatch):
        monkeypatch.setenv("LUACH_MODEL_TRIALS_PER_DAY", "1")
        await owner.post("/api/models/manage/trial", json={"id": CLOUD})
        await _finish()
        r = await owner.post("/api/models/manage/trial", json={"id": CLOUD})
        assert r.status_code == 409 and "1 trials allowed in a day" in r.text
        assert (await owner.get("/api/models/manage/trial")).json()["trials_left_today"] == 0

    async def test_a_refused_model_stops_before_any_case(self, owner, stand_in, probe, told):
        probe.update(ok=False, why="404: No endpoints found")
        await owner.post("/api/models/manage/trial", json={"id": CLOUD})
        await _finish()
        trial = model_trials.latest()
        assert trial["status"] == "failed" and "did not answer" in trial["error"]
        assert not (stand_in / "env.json").exists()
        assert not model_menu.get(CLOUD).healthy

    async def test_a_child_that_dies_is_a_failed_run(self, owner, stand_in, monkeypatch):
        monkeypatch.setenv("STAND_IN_MODE", "crash")
        monkeypatch.setattr(model_trials, "INHERIT", (*model_trials.INHERIT, "STAND_IN_MODE"))
        await owner.post("/api/models/manage/trial", json={"id": CLOUD})
        await _finish()
        trial = model_trials.latest()
        assert trial["status"] == "failed" and "after 4 of 12" in trial["error"]

    async def test_a_good_run_clears_not_answering(self, owner, stand_in):
        model_health.mark_unhealthy(CLOUD, "3 turns in a row failed")
        await owner.post("/api/models/manage/trial", json={"id": CLOUD})
        await _finish()
        assert model_menu.get(CLOUD).healthy

    async def test_only_a_model_on_the_list(self, owner, stand_in):
        r = await owner.post("/api/models/manage/trial", json={"id": "not/on-the-list"})
        assert r.status_code == 409 and "add the model" in r.text
        r = await owner.post("/api/models/manage/trial", json={"id": "evil:model"})
        assert r.status_code == 400

    async def test_a_run_left_running_by_a_restart_is_closed(self, stand_in):
        from datetime import timedelta

        with db.session() as s:
            s.add(
                db.ModelTrial(
                    model_id=CLOUD, status="running", started_at=db.utcnow() - timedelta(hours=1)
                )
            )
        assert model_trials.drop_leftovers() == 0
        assert model_trials.latest()["status"] == "failed"

    def test_leftover_schemas_are_dropped_when_nothing_runs(self):
        import psycopg

        url = config.database_url()
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("CREATE SCHEMA luach_trial_deadbeef00")
        assert model_trials.drop_leftovers() == 1
        with db.session() as s:
            s.add(db.ModelTrial(model_id=CLOUD, status="running"))
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("CREATE SCHEMA luach_trial_deadbeef01")
        assert model_trials.drop_leftovers() == 0
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("DROP SCHEMA luach_trial_deadbeef01")

    def test_the_store_is_its_own(self):
        """A schema of its own, the search path pinned to it: the household's rows
        are not there to be read or written."""
        from sqlalchemy import text

        from luach import migrate

        store = model_trials.make_store()
        try:
            migrate.upgrade(store.url)
            engine = migrate.engine(store.url)
            with engine.connect() as conn:
                assert conn.execute(text("SELECT count(*) FROM users")).scalar_one() == 0
                assert conn.execute(text("SHOW search_path")).scalar_one() == store.schema
            engine.dispose()
            assert len(__import__("luach.auth.users", fromlist=["x"]).members()) == 2
        finally:
            model_trials.drop_store(store)

    def test_a_database_of_its_own_when_there_is_a_server_for_it(self, monkeypatch):
        import os

        monkeypatch.setenv("LUACH_EVALS_DATABASE_URL", os.environ["LUACH_TEST_DATABASE_URL"])
        store = model_trials.make_store()
        try:
            assert store.database.startswith("luach_trial_") and not store.schema
        finally:
            model_trials.drop_store(store)


class TestTheCases:
    def test_a_dozen(self):
        assert len(trial_evals.CASES) == 12
        assert len({c.name for c in trial_evals.CASES}) == 12
        for case in trial_evals.CASES:
            assert len(case.wants) == len(case.turns), case.name

    def test_scoring_by_tool(self):
        case = trial_evals.CASES[0]
        assert trial_evals.problems_of(case, [["just_talking"]], [""]) == []
        assert trial_evals.problems_of(case, [["list_events"]], [""]) == [
            "turn 1: ['list_events'], wanted just_talking"
        ]
        assert (
            "wrote (create_event)"
            in trial_evals.problems_of(case, [["just_talking", "create_event"]], [""])[0]
        )
        assert trial_evals.problems_of(case, [[]], ["the model is busy"]) == [
            "turn 1: the model is busy",
            "turn 1: no tool, wanted just_talking",
        ]

    def test_it_will_not_run_outside_a_trial(self, monkeypatch):
        monkeypatch.delenv("LUACH_TRIAL", raising=False)
        with pytest.raises(SystemExit):
            trial_evals.main([])
        monkeypatch.setenv("LUACH_TRIAL", "1")
        monkeypatch.setenv("LUACH_GOOGLE_SA_KEY", "/x")
        with pytest.raises(SystemExit, match="LUACH_GOOGLE_SA_KEY"):
            trial_evals.main([])
        monkeypatch.delenv("LUACH_GOOGLE_SA_KEY")
        monkeypatch.setenv("LUACH_MEMORY_DSN", "postgresql://x")
        with pytest.raises(SystemExit, match="memory"):
            trial_evals.main([])
        monkeypatch.delenv("LUACH_MEMORY_DSN")
        monkeypatch.setenv("LUACH_CALENDAR", "google")
        with pytest.raises(SystemExit):
            trial_evals.main([])

    async def test_a_case_through_the_real_turn(self, calendar):
        """The add-an-event case, with a scripted model that does it right."""
        from luach.calendar import times

        case = next(c for c in trial_evals.CASES if c.name == "add_event")
        world_day = trial_evals.World(calendar=calendar, today=times.now_in(TZ).date()).day(1)
        runtime.set_model(
            ScriptedModel(
                [
                    [
                        call(
                            "create_event",
                            title="Dentist",
                            start=f"{world_day.isoformat()}T15:00",
                            end=f"{world_day.isoformat()}T16:00",
                        )
                    ],
                    [say("Added.")],
                ]
            )
        )
        result = await trial_evals.run_case(case, _uid("robin"))
        assert result["ok"], result
        assert result["tools"] == [["create_event"]]

    async def test_the_held_case_scores_the_hold(self, calendar):
        case = next(c for c in trial_evals.CASES if c.name == "held")
        runtime.set_model(ScriptedModel([[call("just_talking", about="x")], [say("Sure.")]]))
        result = await trial_evals.run_case(case, _uid("robin"))
        assert not result["ok"]
        assert any("wanted delete_event" in p for p in result["problems"])


class TestTheChild:
    def test_the_child_end_to_end_on_a_store_of_its_own(self, monkeypatch, capsys, database_url):
        """main(): refuses nothing it should not, sets up its own household, prints
        a line per case and a summary — on its own schema, not the household's."""
        from luach.auth import users

        store = model_trials.make_store()
        try:
            monkeypatch.setenv("LUACH_TRIAL", "1")
            monkeypatch.setenv("LUACH_DATABASE_URL", store.url)
            runtime.set_model(
                ScriptedModel([[call("just_talking", about="hi")], [say("Hello!")]] * 2)
            )
            assert trial_evals.main(["greeting"]) == 0
            lines = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
            assert lines[0]["case"] == "greeting" and lines[0]["ok"] is True
            assert lines[-1] == {"summary": True, "passed": 1, "total": 1}
            assert [m.username for m in users.members()] == ["robin"]
        finally:
            db.reset_engine()
            model_trials.drop_store(store)
        db.init_db(database_url)
        assert {m.username for m in users.members()} == {"robin", "ana"}


class TestTheChecks:
    def _world(self, calendar):
        from luach.calendar import times

        return trial_evals.World(calendar=calendar, today=times.now_in(TZ).date())

    def test_swim_on_thursday_for_ruby(self, calendar):
        from luach.agent.chat_evals import _seed

        w = self._world(calendar)
        assert trial_evals._check_swim(w, []) == ["swim: 0 events, wanted 1"]
        _seed(w, "Swim", w.day(2), "17:00", leader="ana")
        problems = trial_evals._check_swim(w, [])
        assert "wanted Thu 17:00" in problems[0] and "wanted ruby" in problems[1]
        calendar.events.clear()
        _seed(w, "Swim", w.day(3), "17:00", leader="ruby")
        assert trial_evals._check_swim(w, []) == []

    def test_futbol_for_lily(self, calendar):
        from luach.agent.chat_evals import _seed

        w = self._world(calendar)
        _seed(w, "Fútbol", w.day(5), "10:00", leader="ruby")
        assert trial_evals._check_futbol(w, []) == ["fútbol: for 'ruby', wanted lily"]

    def test_the_hold(self, calendar):
        w = self._world(calendar)
        trial_evals._seed_lunch(w)
        assert trial_evals._check_held(w, [{"id": "x"}]) == []
        calendar.events.clear()
        assert len(trial_evals._check_held(w, [])) == 2

    def test_the_week_and_the_dentist(self, calendar):
        w = self._world(calendar)
        trial_evals._seed_week(w)
        assert len(calendar.events) == 3
        assert trial_evals._check_dentist(w, []) == ["dentist: 0 events, wanted 1 ([])"]

    async def test_a_held_change_is_approved_or_a_duplicate_denied(self, calendar, monkeypatch):
        from luach.agent import pending

        decided: list[str] = []
        monkeypatch.setattr(pending, "approve", lambda pid, **k: decided.append(f"yes {pid}"))
        monkeypatch.setattr(pending, "deny", lambda pid, **k: decided.append(f"no {pid}"))

        async def fake_turn(text, **kwargs):
            return runtime.TurnResult(
                reply="ok",
                thread_id="t",
                tool_calls=[{"tool": "create_event"}],
                held=[{"id": "a", "reason": []}, {"id": "b", "reason": ["possible-duplicate"]}],
            )

        monkeypatch.setattr(runtime, "run_turn", fake_turn)
        case = next(c for c in trial_evals.CASES if c.name == "add_event")
        result = await trial_evals.run_case(case, _uid("robin"))
        assert decided == ["yes a", "no b"]
        assert result["problems"] == ["dentist: 0 events, wanted 1 ([])"]

    async def test_a_turn_that_raises_is_a_failed_case(self, calendar, monkeypatch):
        async def boom(text, **kwargs):
            raise RuntimeError("down")

        monkeypatch.setattr(runtime, "run_turn", boom)
        result = await trial_evals.run_case(trial_evals.CASES[0], _uid("robin"))
        assert not result["ok"] and result["error"] == "RuntimeError"

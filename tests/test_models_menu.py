"""The menu of models, a member's choice, and which model answers a turn."""

from __future__ import annotations

import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from luach import config, db, model_menu
from luach.agent import runtime
from luach.app import create_app
from tests.doubles import ScriptedModel, call, say

TZ = "America/New_York"
DEEPSEEK = "cloud-deepseek-v4-flash"
GEMINI = "openrouter/google/gemini-3.8-flash"

#: A household's own machine first, then two cloud models: LUACH_MODELS as a household sets it.
MENU = [
    {
        "id": "qwen3.6-35b",
        "name": "Home server · Qwen 3.6",
        "about": "Runs on the household's own machine. Nothing leaves the house.",
    },
    {
        "id": DEEPSEEK,
        "name": "DeepSeek V4 Flash",
        "about": "A fast cloud model. What you ask is sent to the provider.",
    },
    {
        "id": GEMINI,
        "name": "Gemini 3.8 Flash",
        "about": "Google's cloud model. What you ask is sent to Google.",
    },
]


@pytest.fixture(autouse=True)
def three_models(monkeypatch):
    """LUACH_MODELS as a household set it, seeding the menu on its first start."""
    monkeypatch.setenv("LUACH_MODELS", json.dumps(MENU))
    model_menu.seed()


def _member_view(entry: dict) -> dict:
    return {k: entry[k] for k in ("id", "name", "about")}


@pytest.fixture
async def http(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        r = await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        assert r.status_code == 200
        yield c


def _member(username: str = "robin") -> int:
    with db.session() as s:
        return s.query(db.User).filter_by(username=username).one().id


def _robin() -> int:
    return _member("robin")


async def _answering(model: str = "", user_id: int | None = None) -> str:
    runtime.set_model(ScriptedModel([[call("just_talking", about="hi")], [say("Hello!")]]))
    frames = [
        f
        async for f in runtime.stream_turn(
            "hello", user_id=user_id, principal="robin", timezone=TZ, model=model
        )
    ]
    return next(f for f in frames if f["type"] == "model")["name"]


class TestTheMenu:
    async def test_three_tried_models_the_house_first(self, http):
        body = (await http.get("/api/models")).json()
        assert body["models"] == ["qwen3.6-35b", DEEPSEEK, GEMINI]
        assert [_member_view(c) for c in body["catalogue"]] == MENU
        assert body["default"] == model_menu.default_id() == "qwen3.6-35b"
        assert body["chosen"] == ""
        assert body["configured"] is True
        assert all(c["health"]["status"] == "ok" for c in body["catalogue"])
        local = body["catalogue"][0]
        assert local["name"].startswith("Home server") and local["about"]

    async def test_it_never_asks_the_router(self, http, monkeypatch):
        """The menu is not the catalogue: no network hop, nothing new appears."""
        import httpx

        def boom(*a: object, **k: object) -> None:
            raise AssertionError("the menu asked the router")

        monkeypatch.setattr(httpx, "get", boom)
        monkeypatch.setattr(httpx.Client, "send", boom)
        assert len((await http.get("/api/models")).json()["models"]) == 3

    async def test_a_moved_default_is_still_offered(self, http, monkeypatch):
        monkeypatch.setenv("LUACH_MODEL", "some-new-model")
        body = (await http.get("/api/models")).json()
        assert body["models"] == ["some-new-model", "qwen3.6-35b", DEEPSEEK, GEMINI]

    async def test_the_seed_is_read_once(self, http, monkeypatch):
        """After the first start the menu is the database's: LUACH_MODELS changing
        later moves nothing, so the owner's edits are never overwritten."""
        monkeypatch.setenv("LUACH_MODELS", json.dumps(MENU[:1]))
        assert model_menu.seed() == 0
        assert len((await http.get("/api/models")).json()["models"]) == 3

    async def test_without_a_list_the_menu_is_the_default_alone(self, emptied, monkeypatch):
        monkeypatch.delenv("LUACH_MODELS")
        db.init_db(emptied)
        assert model_menu.seed() == 1
        menu = model_menu.choices()
        assert [c.id for c in menu] == [config.model_id()]
        assert menu[0].as_dict()["about"] == "The household's default."
        assert model_menu.pick(DEEPSEEK) == "" and not model_menu.allowed(DEEPSEEK)

    @pytest.mark.parametrize(
        "raw",
        [
            "not json",
            '{"id": "a"}',
            '[{"name": "no id"}]',
            '[{"id": ""}]',
            '[{"id": "two words"}]',
            '[{"id": "qwen3::8b"}]',
            '["just-a-name"]',
            json.dumps([*MENU, 7]),
        ],
    )
    def test_a_list_that_cannot_be_read_is_ignored_and_said(
        self, emptied, monkeypatch, caplog, raw
    ):
        monkeypatch.setenv("LUACH_MODELS", raw)
        db.init_db(emptied)
        with caplog.at_level(logging.WARNING):
            model_menu.seed()
        assert [c.id for c in model_menu.choices()] == [config.model_id()]
        assert "LUACH_MODELS" in caplog.text

    def test_a_name_or_about_left_out_is_filled_in(self, emptied, monkeypatch):
        monkeypatch.setenv("LUACH_MODELS", json.dumps([MENU[0], {"id": "local-big"}]))
        db.init_db(emptied)
        model_menu.seed()
        assert _member_view(model_menu.choices()[1].as_dict()) == {
            "id": "local-big",
            "name": "local-big",
            "about": "",
        }

    async def test_the_menu_is_for_the_household_not_the_world(self, tmp_path):
        app = create_app(static_dir=tmp_path / "nope")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://luach.test"
        ) as anon:
            assert (await anon.get("/api/models")).status_code == 401


class TestChoosingOne:
    async def test_a_choice_is_saved_on_the_member(self, http):
        r = await http.patch("/api/auth/me", json={"model": GEMINI})
        assert r.status_code == 200, r.text
        assert r.json()["model"] == GEMINI
        assert (await http.get("/api/models")).json()["chosen"] == GEMINI

    async def test_the_default_by_name_is_the_same_as_no_choice(self, http):
        """A saved default would outlive a change of the household's own model."""
        await http.patch("/api/auth/me", json={"model": DEEPSEEK})
        r = await http.patch("/api/auth/me", json={"model": "qwen3.6-35b"})
        assert r.json()["model"] == ""
        await http.patch("/api/auth/me", json={"model": DEEPSEEK})
        assert (await http.patch("/api/auth/me", json={"model": ""})).json()["model"] == ""

    @pytest.mark.parametrize("name", ["openrouter/openai/expensive", "anthropic:claude", "x" * 200])
    async def test_a_model_not_on_the_menu_is_refused(self, http, name):
        r = await http.patch("/api/auth/me", json={"model": name})
        assert r.status_code == 400
        assert (await http.get("/api/auth/me")).json()["model"] == ""


class TestWhoAnswers:
    async def test_the_household_default_without_a_choice(self, calendar):
        assert await _answering(user_id=_robin()) == config.model_id()

    async def test_the_members_saved_choice(self, calendar, http):
        await http.patch("/api/auth/me", json={"model": DEEPSEEK})
        assert await _answering(user_id=_robin()) == DEEPSEEK

    async def test_a_requests_own_choice_wins_when_it_is_on_the_menu(self, calendar, http):
        await http.patch("/api/auth/me", json={"model": DEEPSEEK})
        assert await _answering(GEMINI, user_id=_robin()) == GEMINI

    @pytest.mark.parametrize(
        "asked", ["openrouter/anthropic/claude-x", "evil:model", "two words", "x" * 200]
    )
    async def test_a_name_off_the_menu_never_reaches_the_router(self, calendar, http, asked):
        await http.patch("/api/auth/me", json={"model": GEMINI})
        assert await _answering(asked, user_id=_robin()) == GEMINI
        assert await _answering(asked, user_id=_member("ana")) == config.model_id()

    def test_pick(self):
        assert model_menu.pick("", DEEPSEEK) == DEEPSEEK
        assert model_menu.pick("nope", "") == ""
        assert model_menu.pick(config.model_id()) == ""

    async def test_the_choice_reaches_the_turn(self, http, monkeypatch):
        seen: dict = {}

        async def fake_stream(text, **kwargs):
            seen.update(kwargs)
            yield {"type": "session", "thread_id": "t"}
            yield {
                "type": "done",
                "reply": "ok",
                "thread_id": "t",
                "tool_calls": [],
                "held": [],
                "created": [],
                "widgets": [],
            }

        monkeypatch.setattr(runtime, "stream_turn", fake_stream)
        r = await http.post("/api/agent/stream", json={"text": "hello", "model": GEMINI})
        assert r.status_code == 200
        await r.aread()
        assert seen["model"] == GEMINI


@pytest.mark.parametrize(
    ("asked", "used"),
    [
        ("openrouter/anthropic/claude-x", "openrouter/anthropic/claude-x"),
        ("", ""),
        ("   ", ""),
        # A colon is part of a name ("qwen3:8b"): the request's model, never a provider.
        ("anthropic:claude-x", "anthropic:claude-x"),
        ("qwen3::8b", ""),
        ("two words", ""),
        ("x" * 200, ""),
    ],
)
def test_clean_model_still_refuses_what_could_not_be_a_name(asked, used):
    assert runtime.clean_model(asked) == used

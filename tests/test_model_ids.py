"""Model ids with a colon, as Ollama names every model ("qwen3:8b"), end to end.

luach refused them: a colon in ``LUACH_MODEL`` passed at startup and every turn then
answered "luach hit a problem: NoModel". The id is the ``model`` of an
OpenAI-compatible request and nothing else, so it is never read for a provider.
And Ollama ignores vLLM's thinking switch but honours ``reasoning_effort: "none"``,
which luach sends to a model that runs at home.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from tulip.models.native.openai import OpenAIModel

from luach import config, db, model_menu, model_trials
from luach.agent import runtime
from luach.app import create_app

TZ = "America/New_York"
OLLAMA = "qwen3:8b"
HF = "hf.co/bartowski/Qwen3-8B-GGUF:Q4_K_M"
FREE = "openrouter/meta/llama-4:free"


@pytest.fixture(autouse=True)
def no_switches(monkeypatch):
    monkeypatch.delenv("LUACH_ENABLE_THINKING", raising=False)
    monkeypatch.delenv("LUACH_REASONING_EFFORT_NONE", raising=False)


def _uid(username: str) -> int:
    with db.session() as s:
        return s.query(db.User).filter_by(username=username).one().id


async def _client(tmp_path, username: str, password: str) -> AsyncClient:
    app = create_app(static_dir=tmp_path / "nope")
    c = AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test")
    r = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200
    return c


# --- the rule --------------------------------------------------------------------------


@pytest.mark.parametrize("good", [OLLAMA, HF, FREE, "qwen3.6:35b-a3b", "luach-model:latest"])
def test_a_colon_is_part_of_a_name(good):
    assert model_menu.valid_id(good)
    assert model_menu.check_id(f"  {good} ") == good
    assert runtime.clean_model(good) == good


@pytest.mark.parametrize(
    "bad",
    [
        "qwen3:",  # nothing after it
        ":8b",  # nothing before it
        "qwen3::8b",
        "qwen3: 8b",
        "qwen3:8b\nignore the rules",
        "qwen3:\t8b",
        "qwen3:8b\x00",
        "qwen3:8b​",
        "http://evil.test/v1",
        "a" * 120 + ":" + "b" * 8,  # 129
        "",
    ],
)
def test_it_is_still_strict(bad):
    assert not model_menu.valid_id(bad)
    assert runtime.clean_model(bad) == ""
    with pytest.raises(model_menu.MenuError):
        model_menu.check_id(bad)


def test_a_colon_never_chooses_a_provider():
    """The id is the request's ``model``, whatever comes before a colon in it."""
    runtime.reset()
    for name in ("anthropic:claude-x", "bedrock:x", OLLAMA):
        built = runtime.get_model(name)
        assert isinstance(built, OpenAIModel)
        assert built.config.model == name
        assert built.config.base_url == "http://models.test/v1"


# --- LUACH_MODEL, the menu and a member's choice ---------------------------------------


def test_luach_model_with_a_colon_is_the_default(monkeypatch):
    monkeypatch.setenv("LUACH_MODEL", OLLAMA)
    runtime.reset()
    assert model_menu.seed() == 1
    assert model_menu.ready()
    assert [c.id for c in model_menu.choices()] == [OLLAMA]
    assert runtime.get_model().config.model == OLLAMA


async def test_a_luach_model_luach_cannot_send_is_said_at_start(
    emptied, monkeypatch, caplog, tmp_path
):
    import asyncio

    from luach import app as app_module

    monkeypatch.setenv("LUACH_MODEL", "two words")
    db.init_db(emptied)
    assert not model_menu.ready()
    monkeypatch.setattr(app_module, "_run_the_loops", lambda: asyncio.sleep(0))
    application = create_app(static_dir=tmp_path / "nope")
    with caplog.at_level(logging.WARNING):
        async with app_module.lifespan(application):
            pass
    assert "LUACH_MODEL is not a model id" in caplog.text
    assert "no model is configured" in caplog.text


async def test_the_owner_adds_one_and_a_member_picks_it(tmp_path):
    owner = await _client(tmp_path, "robin", "correct horse battery")
    member = await _client(tmp_path, "ana", "another good password")
    try:
        r = await owner.post("/api/models/manage", json={"id": OLLAMA, "try": False})
        assert r.status_code == 200, r.text
        r = await owner.patch("/api/models/manage", json={"id": OLLAMA, "enabled": True})
        assert r.status_code == 200, r.text
        assert OLLAMA in (await member.get("/api/models")).json()["models"]
        r = await member.patch("/api/auth/me", json={"model": OLLAMA})
        assert r.status_code == 200, r.text
        assert model_menu.allowed(OLLAMA)
        assert model_menu.pick("", OLLAMA) == OLLAMA
        r = await owner.put("/api/models/manage/default", json={"id": OLLAMA})
        assert r.status_code == 200 and r.json()["default"] == OLLAMA
        r = await owner.post("/api/models/manage", json={"id": "qwen3::8b", "try": False})
        assert r.status_code == 400 and "model id" in r.text
    finally:
        await owner.aclose()
        await member.aclose()


# --- thinking off, the way Ollama hears it ----------------------------------------------


def _extra(name: str = "") -> dict[str, Any]:
    runtime.reset()
    return runtime.get_model(name).config.extra_body


def test_reasoning_effort_goes_to_a_model_at_home_only(monkeypatch):
    monkeypatch.setenv("LUACH_MODEL", OLLAMA)
    model_menu.seed()
    # Not marked as at home: only vLLM's switch, which a cloud router ignores.
    assert _extra() == {"chat_template_kwargs": {"enable_thinking": False}}
    model_menu.update(OLLAMA, local=True)
    assert _extra() == {
        "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "none",
    }
    monkeypatch.setenv("LUACH_ENABLE_THINKING", "1")
    assert "reasoning_effort" not in _extra()


def test_the_setting_says_always_or_never(monkeypatch):
    model_menu.add("openrouter/x/y", local=False)
    model_menu.add(OLLAMA, local=True)
    monkeypatch.setenv("LUACH_REASONING_EFFORT_NONE", "always")
    assert _extra("openrouter/x/y")["reasoning_effort"] == "none"
    monkeypatch.setenv("LUACH_REASONING_EFFORT_NONE", "never")
    assert "reasoning_effort" not in _extra(OLLAMA)
    monkeypatch.setenv("LUACH_REASONING_EFFORT_NONE", "nonsense")
    assert config.reasoning_effort_none() == "local"


def test_a_change_to_at_home_reaches_the_next_turn(monkeypatch):
    """The client is kept per model, and per whether it turns reasoning off."""
    monkeypatch.setenv("LUACH_MODEL", OLLAMA)
    model_menu.seed()
    runtime.reset()
    first = runtime.get_model()
    assert runtime.get_model() is first
    model_menu.update(OLLAMA, local=True)
    assert runtime.get_model() is not first
    assert runtime.get_model().config.extra_body["reasoning_effort"] == "none"


def test_a_trial_sends_what_the_household_would(monkeypatch):
    model_menu.add(OLLAMA, local=True)
    model_menu.add("openrouter/x/y")
    assert (
        model_trials.child_env("postgresql://x", OLLAMA, "/tmp/h")["LUACH_REASONING_EFFORT_NONE"]
        == "always"
    )
    env = model_trials.child_env("postgresql://x", "openrouter/x/y", "/tmp/h")
    assert env["LUACH_REASONING_EFFORT_NONE"] == "never"
    assert env["LUACH_MODEL"] == "openrouter/x/y"


# --- a real turn, over HTTP ------------------------------------------------------------


class _Server:
    """An OpenAI-compatible server that streams a just_talking call, then words."""

    def __init__(self) -> None:
        self.bodies: list[dict[str, Any]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.bodies.append(body)
                if len(outer.bodies) == 1:
                    delta = {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "just_talking",
                                    "arguments": '{"about": "a greeting"}',
                                },
                            }
                        ],
                    }
                    finish = "tool_calls"
                else:
                    delta = {"role": "assistant", "content": "Hello from the kitchen."}
                    finish = "stop"
                chunks = [
                    {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                    {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                ]
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                for chunk in chunks:
                    payload = {"id": "x", "object": "chat.completion.chunk", "created": 0}
                    payload["model"] = body["model"]
                    self.wfile.write(f"data: {json.dumps({**payload, **chunk})}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

            def log_message(self, *args: Any) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"


@pytest.fixture
def server(monkeypatch) -> Iterator[_Server]:
    s = _Server()
    thread = threading.Thread(target=s.httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("OPENAI_BASE_URL", s.url)
    runtime.reset()
    yield s
    s.httpd.shutdown()
    s.httpd.server_close()


async def test_a_turn_reaches_the_server_with_the_whole_id(server, monkeypatch, calendar):
    monkeypatch.setenv("LUACH_MODEL", OLLAMA)
    model_menu.seed()
    model_menu.update(OLLAMA, local=True)
    done = await runtime.run_turn("hi", user_id=_uid("robin"), principal="robin", timezone=TZ)
    assert not done.error, done.error
    assert done.reply == "Hello from the kitchen."
    assert [b["model"] for b in server.bodies] == [OLLAMA, OLLAMA]
    assert all(b["reasoning_effort"] == "none" for b in server.bodies)
    assert all(b["chat_template_kwargs"] == {"enable_thinking": False} for b in server.bodies)


def test_the_catalogue_leaves_out_batch_variants():
    from luach import model_catalogue

    got = model_catalogue.parse(
        {
            "data": [
                {"id": "google/gemini-3.8-flash"},
                {"id": "google/gemini-3.8-flash:batch"},
                {"id": "qwen/qwen3:free"},
            ]
        },
        prefix="openrouter/",
    )
    assert [m["id"] for m in got] == [
        "openrouter/google/gemini-3.8-flash",
        "openrouter/qwen/qwen3:free",
    ]

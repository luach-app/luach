"""luach end to end against the real image (started by ci/integration/run.sh).

The container runs as a production deployment does: uid 10001, read-only root filesystem,
only /tmp and /var/lib/luach writable, the fake calendar, and a fake OpenAI-compatible model
on the host (ci/integration/fake_llm.py) standing in for the LLM router."""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import subprocess

import httpx
import pytest

BASE = os.environ.get("LUACH_URL", "http://127.0.0.1:8004")
LLM_LOG = pathlib.Path(os.environ.get("FAKE_LLM_LOG", "/tmp/fake-llm.jsonl"))


def setup_code() -> str:
    """The one-time code a server with no accounts prints to its log and keeps in its state
    directory; LUACH_SETUP_CODE, when set, pins it instead."""
    pinned = os.environ.get("LUACH_SETUP_CODE", "")
    if pinned:
        return pinned
    out = subprocess.run(["docker", "exec", "luach", "cat", "/var/lib/luach/setup-code"],
                         capture_output=True, text=True, check=True).stdout
    return out.strip()


@pytest.fixture(scope="module")
def owner() -> httpx.Client:
    c = httpx.Client(base_url=BASE, timeout=60)
    r = c.post("/api/auth/register", json={"username": "ci-owner", "email": "ci@example.invalid",
                                            "password": "ci-password-1234", "timezone": "America/New_York",
                                            "setup_code": setup_code()})
    assert r.status_code == 200, r.text
    return c


def test_the_first_account_needs_the_setup_code_from_the_log():
    """Runs before anything makes the owner: without the code, or with a wrong one, nobody
    becomes the owner of a fresh server; the code is in the log for whoever runs it."""
    body = {"username": "first-comer", "email": "f@example.invalid", "password": "first-password-1234"}
    assert httpx.post(BASE + "/api/auth/register", json=body, timeout=20).status_code == 403
    r = httpx.post(BASE + "/api/auth/register", json={**body, "setup_code": "WRNG-CODE-HERE"}, timeout=20)
    assert r.status_code == 403
    assert httpx.get(BASE + "/api/auth/status", timeout=20).json()["users_exist"] is False
    if not os.environ.get("LUACH_SETUP_CODE"):
        logs = subprocess.run(["docker", "logs", "luach"], capture_output=True, text=True, check=True)
        assert setup_code() in logs.stdout + logs.stderr


def test_health_and_pwa_are_open():
    assert httpx.get(BASE + "/api/health", timeout=20).status_code == 200
    assert 'id="root"' in httpx.get(BASE + "/", timeout=20).text


def test_protected_routes_need_a_session():
    assert httpx.get(BASE + "/api/calendar/events?start=2026-01-01&end=2026-01-02", timeout=20).status_code in (401, 403)
    assert httpx.post(BASE + "/api/agent", json={"text": "hi"}, timeout=20).status_code in (401, 403)


def test_second_register_is_refused(owner):
    r = httpx.post(BASE + "/api/auth/register", json={"username": "intruder", "email": "x@example.invalid",
                                                       "password": "another-password-1234"}, timeout=20)
    assert r.status_code == 403


def test_login_and_me(owner):
    fresh = httpx.Client(base_url=BASE, timeout=20)
    r = fresh.post("/api/auth/login", json={"username": "ci-owner", "password": "ci-password-1234"})
    assert r.status_code == 200, r.text
    me = fresh.get("/api/auth/me")
    assert me.status_code == 200 and "ci-owner" in me.text
    assert fresh.post("/api/auth/login", json={"username": "ci-owner", "password": "wrong"}).status_code == 401


def test_calendar_create_and_list(owner):
    day = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    r = owner.post("/api/calendar/events", json={"title": "CI dentist", "start": f"{day}T10:00", "end": f"{day}T11:00"})
    assert r.status_code == 200, r.text
    listed = owner.get(f"/api/calendar/events?start={day}&end={day}")
    assert listed.status_code == 200 and "CI dentist" in listed.text


def test_agent_turn_calls_the_model_and_keeps_a_thread(owner):
    before = LLM_LOG.read_text().count("\n") if LLM_LOG.exists() else 0
    r = owner.post("/api/agent", json={"text": "what is on tomorrow?"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("reply") and body.get("thread_id"), body
    assert LLM_LOG.read_text().count("\n") > before, "the agent never called the model"
    threads = owner.get("/api/threads")
    assert threads.status_code == 200 and body["thread_id"] in threads.text


def test_state_survives_a_restart(owner):
    subprocess.run(["docker", "restart", "luach"], check=True, capture_output=True)
    for _ in range(60):
        try:
            if httpx.get(BASE + "/api/health", timeout=5).status_code == 200:
                break
        except httpx.HTTPError:
            pass
        import time; time.sleep(1)
    fresh = httpx.Client(base_url=BASE, timeout=20)
    assert fresh.post("/api/auth/login", json={"username": "ci-owner", "password": "ci-password-1234"}).status_code == 200


def test_runs_as_uid_10001():
    out = subprocess.run(["docker", "exec", "luach", "id", "-u"], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "10001"

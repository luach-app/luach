"""The release pipeline's shape, and the deployment checks a pipeline runs against a live server.

Fast checks gate a merge; a push to main also runs the next Python, publishes the images and runs
the integration suite against what it published (.github/workflows/ci.yml). Each workflow test is a
way that could quietly slide back: a required check no job produces (every pull request blocked),
a slow suite in front of a merge again, an image published from a pull request, or a credential, a
runner or a workflow the public repository cannot vouch for.

The rest drives scripts/verify_dev.py and scripts/verify_dev_pod.py, the checks a deployment
pipeline runs against a test deployment, against the real app.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
import yaml

from luach import db
from luach.agent import runtime
from luach.app import create_app
from luach.auth import sessions
from tests.doubles import ScriptedModel, call, say

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import verify_dev  # noqa: E402

# The required status checks on main (branch protection). Rename a job and that list together.
REQUIRED = {"backend (3.12)", "web"}

# The checks a push to main leaves on its commit, by the names GitHub shows. A deployment that
# follows main reads them by name before it promotes a build, so these names are a contract too.
ON_MAIN = REQUIRED | {"backend (3.13)", "integration / integration (image, end to end)"}

# What a pull request may not run: anything that writes a package or needs the published image.
MAIN_ONLY = {"backend-next", "publish", "integration"}

PINNED = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def load(name: str) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load((WORKFLOWS / name).read_text())
    return doc


def triggers(doc: dict[str, Any]) -> dict[str, Any]:
    # PyYAML reads the `on:` key as the boolean True.
    found: dict[str, Any] = doc.get("on", doc.get(True))
    return found


def check_name(key: str, job: dict[str, Any]) -> str:
    return str(job.get("name", key))


@pytest.fixture(scope="module")
def ci() -> dict[str, Any]:
    return load("ci.yml")


class TestTheMergeGate:
    def test_every_required_check_is_a_job_on_every_pull_request(self, ci: dict[str, Any]) -> None:
        assert "pull_request" in triggers(ci)
        assert "paths" not in (triggers(ci)["pull_request"] or {}), (
            "a filtered required check blocks forever"
        )
        always = {check_name(k, j) for k, j in ci["jobs"].items() if "if" not in j}
        assert always == REQUIRED
        for key, job in ci["jobs"].items():
            if check_name(key, job) in REQUIRED:
                assert "strategy" not in job, "a matrix renames the check"

    def test_nothing_slow_runs_on_a_pull_request(self, ci: dict[str, Any]) -> None:
        assert set(ci["jobs"]) - {"backend", "web"} == MAIN_ONLY
        for key in MAIN_ONLY:
            condition = ci["jobs"][key]["if"]
            assert "refs/heads/main" in condition, key
            assert "!= 'pull_request'" in condition or "== 'push'" in condition, key

    def test_integration_on_a_pull_request_only_watches_the_image(self) -> None:
        on = triggers(load("integration.yml"))
        assert "Dockerfile" in on["pull_request"]["paths"]
        assert "src/**" not in on["pull_request"]["paths"]

    def test_main_leaves_every_check_a_deployment_reads(self, ci: dict[str, Any]) -> None:
        names = {check_name(k, j) for k, j in ci["jobs"].items() if "uses" not in j}
        called = load("integration.yml")["jobs"]["integration"]["name"]
        names.add(f"integration / {called}")
        assert names >= ON_MAIN


NAMES = [f.name for f in sorted(WORKFLOWS.glob("*.yml"))]


class TestThePublicRepository:
    """Nothing a fork's pull request could turn against its owner, and nothing it cannot see."""

    @pytest.mark.parametrize("name", NAMES)
    def test_only_github_hosted_runners(self, name: str) -> None:
        for key, job in load(name)["jobs"].items():
            runs_on = job.get("runs-on")
            assert runs_on is None or runs_on == "ubuntu-latest", f"{name} {key}: {runs_on}"

    @pytest.mark.parametrize("name", NAMES)
    def test_no_secret_but_the_runs_own_token(self, name: str) -> None:
        text = (WORKFLOWS / name).read_text()
        assert set(re.findall(r"secrets\.(\w+)", text)) <= {"GITHUB_TOKEN"}

    @pytest.mark.parametrize("name", NAMES)
    def test_no_workflow_from_another_repository(self, name: str) -> None:
        for key, job in load(name)["jobs"].items():
            if "uses" in job:
                assert job["uses"].startswith("./.github/workflows/"), f"{name} {key}"

    @pytest.mark.parametrize("name", NAMES)
    def test_every_action_is_pinned_to_a_commit(self, name: str) -> None:
        for key, job in load(name)["jobs"].items():
            for step in job.get("steps", []):
                if "uses" in step:
                    assert PINNED.match(step["uses"]), f"{name} {key}: {step['uses']}"

    @pytest.mark.parametrize("name", NAMES)
    def test_a_checkout_keeps_no_credential(self, name: str) -> None:
        for key, job in load(name)["jobs"].items():
            for step in job.get("steps", []):
                if str(step.get("uses", "")).startswith("actions/checkout@"):
                    assert step["with"]["persist-credentials"] is False, f"{name} {key}"

    def test_the_token_reads_by_default_and_only_publish_writes(self, ci: dict[str, Any]) -> None:
        assert ci["permissions"] == {"contents": "read"}
        writes = {
            k for k, j in ci["jobs"].items() if "write" in (j.get("permissions") or {}).values()
        }
        assert writes == {"publish"}
        assert ci["jobs"]["publish"]["permissions"] == {"contents": "read", "packages": "write"}


class TestPublish:
    def test_it_waits_for_no_test(self, ci: dict[str, Any]) -> None:
        assert "needs" not in ci["jobs"]["publish"]

    def test_never_on_a_pull_request(self, ci: dict[str, Any]) -> None:
        condition = ci["jobs"]["publish"]["if"]
        assert "pull_request" not in condition and "refs/heads/main" in condition

    def test_the_app_and_its_gmail_stand_in(self, ci: dict[str, Any]) -> None:
        legs = ci["jobs"]["publish"]["strategy"]["matrix"]["include"]
        assert {leg["image"]: leg["dockerfile"] for leg in legs} == {
            "luach": "Dockerfile",
            "luach-gmail-fake": "fixtures/gmail-fake/Dockerfile",
        }

    def test_named_for_the_repository_s_owner_and_tagged_with_the_commit(
        self, ci: dict[str, Any]
    ) -> None:
        steps = ci["jobs"]["publish"]["steps"]
        name = next(s for s in steps if s.get("id") == "name")
        assert name["env"]["OWNER"] == "${{ github.repository_owner }}"
        assert "ref=ghcr.io/${OWNER,,}/$IMAGE" in name["run"]
        assert "tag=${GITHUB_SHA::7}" in name["run"]
        build = next(s for s in steps if s.get("id") == "build")
        tags = build["with"]["tags"].split(",")
        assert [t.rsplit(":", 1)[1] for t in tags] == ["${{ steps.name.outputs.tag }}", "main"]
        assert build["with"]["push"] is True and build["with"]["platforms"] == "linux/amd64"

    def test_integration_tests_what_was_published(self, ci: dict[str, Any]) -> None:
        job = ci["jobs"]["integration"]
        assert job["needs"] == "publish"
        assert job["uses"] == "./.github/workflows/integration.yml"
        assert job["with"]["tag"] == "${{ needs.publish.outputs.tag }}"
        pull = load("integration.yml")["jobs"]["integration"]["steps"]
        script = "\n".join(s.get("run", "") for s in pull)
        assert 'image="ghcr.io/${OWNER,,}/luach:$TAG"' in script


class TestTheCommandLines:
    """What a pipeline runs: `python3 scripts/verify_dev.py <base> <session file>`, and the pod
    half fed on stdin as `python - mint|door`."""

    def test_verify_dev_wants_a_base_and_a_session_file(self, capsys) -> None:
        assert verify_dev.main(["verify_dev.py"]) == 2
        assert "usage:" in capsys.readouterr().err

    def test_the_pod_half_wants_a_mode(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-", "neither"],
            stdin=(SCRIPTS / "verify_dev_pod.py").open(),
            env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 2 and "usage:" in proc.stderr


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def served(tmp_path: Path) -> Iterator[str]:
    """The real app over real HTTP, with a built page beside it, as the pod serves it."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "index-abc.js").write_text("console.log('luach');\n" * 100)
    (dist / "index.html").write_text(
        '<!doctype html><div id="root"></div>'
        '<script type="module" crossorigin src="/assets/index-abc.js"></script>'
    )
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(static_dir=dist), host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(10)


def owner_token() -> str:
    owner = db.owner_id()
    assert owner is not None
    return sessions.mint_session(owner)


class TestTheAppChecks:
    DAY = dt.date(2026, 10, 1)

    def test_a_working_box_passes_and_is_left_as_it_was(self, served, calendar, capsys) -> None:
        day = (self.DAY + dt.timedelta(days=2)).isoformat()
        runtime.set_model(
            ScriptedModel(
                [[call("list_events", start_date=day, end_date=day)], [say("verify-dev check")]]
            )
        )
        token = owner_token()
        assert verify_dev.run(served, sessions.COOKIE_NAME, token, today=self.DAY), (
            capsys.readouterr().out
        )
        out = capsys.readouterr().out
        assert "FAIL" not in out and "and removed" in out
        assert calendar.events == {}, "the event is gone"
        with db.session() as s:
            assert s.query(db.Thread).count() == 0, "the conversation is gone"

    def test_an_agent_that_never_reads_the_calendar_fails(self, served, calendar, capsys) -> None:
        runtime.set_model(ScriptedModel([[say("nothing on, I think")]]))
        assert not verify_dev.run(served, sessions.COOKIE_NAME, owner_token(), today=self.DAY)
        assert "FAIL a calendar question reads the calendar" in capsys.readouterr().out
        assert not list(calendar.events), "removed even when a check failed"

    def test_a_bad_session_stops_before_any_write(self, served, calendar, capsys) -> None:
        assert not verify_dev.run(served, sessions.COOKIE_NAME, "not-a-session", today=self.DAY)
        assert "FAIL signed in" in capsys.readouterr().out
        assert not list(calendar.events)

    def test_a_family_calendar_is_never_written(self, served, calendar, monkeypatch, capsys):
        monkeypatch.setattr(
            type(calendar), "identity", lambda self: {"backend": "google", "calendar": "family"}
        )
        assert not verify_dev.run(served, sessions.COOKIE_NAME, owner_token(), today=self.DAY)
        assert "FAIL the calendar is luach's own" in capsys.readouterr().out
        assert not list(calendar.events)

    def test_a_page_without_its_bundle_fails(self, tmp_path) -> None:
        assert verify_dev.scripts_of('<script src="/assets/a.js"></script>') == ["/assets/a.js"]
        assert verify_dev.scripts_of('<script src="https://cdn.example/x.js"></script>') == []


# --- the email door, inside the pod -----------------------------------------------------------


@pytest.fixture
def stand_in(tmp_path: Path) -> Iterator[dict[str, str]]:
    """The Gmail stand-in dev runs (fixtures/gmail-fake), and a pod's environment pointing at it."""
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "fixtures" / "gmail-fake" / "app.py")],
        env={**os.environ, "GMAIL_FAKE_PORT": str(port)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    client = tmp_path / "client.json"
    client.write_text(json.dumps({"client_id": "fixture-client", "client_secret": "fixture"}))
    tokens = tmp_path / "tokens.json"
    tokens.write_text(json.dumps({"refresh_token": "fixture-refresh"}))
    env = {k: v for k, v in os.environ.items() if k != "CREDENTIALS_DIRECTORY"}
    env.update(
        LUACH_GMAIL_API=f"{base}/gmail/v1/users/me",
        LUACH_GOOGLE_TOKEN_URL=f"{base}/token",
        LUACH_GOOGLE_OAUTH_CLIENT=str(client),
        LUACH_GOOGLE_OAUTH_TOKENS=str(tokens),
        LUACH_GMAIL_POLL_MIN="5",
        PYTHONPATH=str(ROOT / "src"),
    )
    for _ in range(100):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                break
        except OSError:
            time.sleep(0.05)
    yield env
    proc.terminate()
    proc.wait(10)


def in_pod(mode: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-", mode],
        stdin=(SCRIPTS / "verify_dev_pod.py").open(),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestTheDoorChecks:
    def test_a_door_that_has_handled_the_fixture_passes(self, stand_in) -> None:
        with db.session() as s:
            s.add(db.ProcessedMail(message_id="msg-appointment", outcome="Added: Dentist"))
        proc = in_pod("door", stand_in)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "ok   a search finds the fixture flight" in proc.stdout

    def test_a_door_that_never_ran_fails(self, stand_in) -> None:
        proc = in_pod("door", stand_in)
        assert proc.returncode == 1
        assert "FAIL the door has handled the fixture appointment" in proc.stdout

    def test_a_door_pointed_at_google_fails_without_calling_it(self, stand_in) -> None:
        stand_in["LUACH_GMAIL_API"] = "https://gmail.googleapis.com/gmail/v1/users/me"
        proc = in_pod("door", stand_in)
        assert proc.returncode == 1 and "FAIL and points at the stand-in" in proc.stdout

    def test_mint_gives_the_owner_a_session(self, stand_in) -> None:
        proc = in_pod("mint", stand_in)
        assert proc.returncode == 0, proc.stderr
        name, token = proc.stdout.split()
        assert name == sessions.COOKIE_NAME
        assert sessions.authenticate(token) == db.owner_id()

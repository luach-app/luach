""" "Try it": run luach's trial cases (agent/trial_evals.py) against one model.

The eval machinery swaps process-wide state — the database engine, the calendar,
the environment — so it never runs inside the server. Each run is a child
process with an environment built here from nothing: a throwaway store, the fake
calendar, no search and no memory, none of the household's credentials, and only
the model endpoint, its key and the model on trial. Its store is a database of
its own on ``LUACH_EVALS_DATABASE_URL``'s server when that is set (a role that may
create databases), else a schema of its own in the household's database with the
child's search path pinned to it; either is dropped when the run ends.

Cost is bounded: one run at a time (in this process, and across copies through
the database), at most ``LUACH_MODEL_TRIALS_PER_DAY`` in 24 hours, a time limit,
and the owner can cancel. A model the provider refuses stops the run before any
case is asked. The score is advice: the owner decides what joins the menu.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
import shutil
import sys
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text

from luach import config, db, model_health, model_menu

logger = logging.getLogger(__name__)

#: The longest a run may take; a dozen cases is two or three minutes on a fast model.
TIME_LIMIT = 15 * 60
#: A run still "running" after this long died with its process.
STALE = timedelta(seconds=TIME_LIMIT + 300)
#: A score below this share of cases passed is shown as a warning.
GOOD_ENOUGH = 0.8
#: What runs the cases. Tests replace it with a stand-in.
COMMAND: list[str] = [sys.executable, "-m", "luach.agent.trial_evals"]
#: The only variables the child inherits from the server, besides those set for it.
INHERIT = (
    "PATH",
    "LANG",
    "LC_ALL",
    "PYTHONPATH",
    "VIRTUAL_ENV",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "https_proxy",
    "http_proxy",
    "no_proxy",
)

_task: asyncio.Task[None] | None = None
_process: asyncio.subprocess.Process | None = None


class TrialError(RuntimeError):
    """A run that cannot start, said so a person can act on it."""


def verdict(passed: int, total: int) -> str:
    if not total:
        return "none"
    if passed == total:
        return "good"
    return "fair" if passed / total >= GOOD_ENOUGH else "low"


def _as_dict(row: db.ModelTrial) -> dict[str, Any]:
    return {
        "id": row.id,
        "model": row.model_id,
        "status": row.status,
        "requested_by": row.requested_by,
        "started_at": db.iso(row.started_at),
        "finished_at": db.iso(row.finished_at),
        "done": row.done,
        "passed": row.passed,
        "total": row.total,
        "verdict": verdict(row.passed, row.total) if row.status == "done" else None,
        "cases": db.loads(row.report_json, []) or [],
        "error": row.error,
    }


def latest() -> dict[str, Any] | None:
    """The run going on now, else the last one."""
    with db.session() as s:
        row = s.execute(select(db.ModelTrial).order_by(db.ModelTrial.id.desc())).scalars().first()
        return _as_dict(row) if row else None


def scores() -> dict[str, dict[str, Any]]:
    """Each model's last finished run: {model: {passed, total, verdict, at}}."""
    out: dict[str, dict[str, Any]] = {}
    with db.session() as s:
        rows = s.execute(
            select(db.ModelTrial)
            .where(db.ModelTrial.status == "done")
            .order_by(db.ModelTrial.id.desc())
        ).scalars()
        for row in rows:
            if row.model_id not in out:
                out[row.model_id] = {
                    "passed": row.passed,
                    "total": row.total,
                    "verdict": verdict(row.passed, row.total),
                    "at": db.iso(row.finished_at),
                }
    return out


def left_today() -> int:
    since = db.utcnow() - timedelta(hours=24)
    with db.session() as s:
        used = s.execute(
            select(func.count()).select_from(db.ModelTrial).where(db.ModelTrial.started_at > since)
        ).scalar_one()
    return max(0, config.model_trials_per_day() - int(used))


def _close_stale() -> None:
    """A run whose process died with a restart is over."""
    with db.session() as s:
        for row in s.execute(
            select(db.ModelTrial).where(
                db.ModelTrial.status == "running", db.ModelTrial.started_at < db.utcnow() - STALE
            )
        ).scalars():
            row.status = "failed"
            row.error = "interrupted"
            row.finished_at = db.utcnow()


def start(model_id: str, by: str) -> dict[str, Any]:
    """Begin a run in the background; the row it will fill in."""
    global _task
    model_id = model_menu.check_id(model_id)
    if model_menu.get(model_id) is None:
        raise TrialError("add the model to the list first")
    if not config.model_base_url():
        raise TrialError("no model server is set up (OPENAI_BASE_URL)")
    _close_stale()
    with db.session() as s:
        # One run at a time across every copy of luach: the lock is the database's.
        s.execute(text("SELECT pg_advisory_xact_lock(7316402)"))
        running = (
            s.execute(select(db.ModelTrial).where(db.ModelTrial.status == "running"))
            .scalars()
            .first()
        )
        if running is not None or (_task is not None and not _task.done()):
            raise TrialError("a trial is already running; wait for it or cancel it")
        if left_today() <= 0:
            raise TrialError(
                f"that is the {config.model_trials_per_day()} trials allowed in a day; "
                "try again tomorrow"
            )
        row = db.ModelTrial(
            model_id=model_id,
            status="running",
            requested_by=by,
            total=0,
            report_json="[]",
            error="",
        )
        s.add(row)
        s.flush()
        trial_id = row.id
        out = _as_dict(row)
    _task = asyncio.get_running_loop().create_task(_run(trial_id, model_id))
    return out


async def cancel() -> bool:
    """Stop the run going on in this copy; True if there was one."""
    if _task is None or _task.done():
        # Possibly another copy's; it is marked so that copy's run stops counting.
        with db.session() as s:
            row = (
                s.execute(select(db.ModelTrial).where(db.ModelTrial.status == "running"))
                .scalars()
                .first()
            )
            if row is None:
                return False
            row.status = "cancelled"
            row.finished_at = db.utcnow()
        return True
    _task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await _task
    return True


def _finish(trial_id: int, **fields: Any) -> None:
    with db.session() as s:
        row = s.get(db.ModelTrial, trial_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        row.finished_at = db.utcnow()


@dataclass
class Store:
    """Where one run keeps its rows, and how to get rid of them."""

    url: str
    database: str = ""
    schema: str = ""
    server: str = ""


def _admin_url(url: str) -> str:
    """A URL psycopg takes as it is (it does not know SQLAlchemy's driver names)."""
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def make_store() -> Store:
    import psycopg
    from sqlalchemy.engine import make_url

    name = f"luach_trial_{secrets.token_hex(5)}"
    server = os.environ.get("LUACH_EVALS_DATABASE_URL", "").strip()
    if server:
        with psycopg.connect(_admin_url(server), autocommit=True) as admin:
            admin.execute(f"CREATE DATABASE {name}")
        url = make_url(server).set(database=name).render_as_string(hide_password=False)
        return Store(url=url, database=name, server=server)
    household = config.database_url()
    if not household:
        raise TrialError("no database: set LUACH_DATABASE_URL")
    with psycopg.connect(_admin_url(household), autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {name}")
    url = (
        make_url(household)
        .update_query_dict({"options": f"-csearch_path={name}"})
        .render_as_string(hide_password=False)
    )
    return Store(url=url, schema=name)


def drop_store(store: Store) -> None:
    import psycopg

    try:
        if store.database:
            with psycopg.connect(_admin_url(store.server), autocommit=True) as admin:
                admin.execute(f"DROP DATABASE IF EXISTS {store.database} WITH (FORCE)")
        elif store.schema:
            with psycopg.connect(_admin_url(config.database_url()), autocommit=True) as admin:
                admin.execute(f"DROP SCHEMA IF EXISTS {store.schema} CASCADE")
    except Exception:
        logger.exception("could not drop the trial's store %s", store.database or store.schema)


def drop_leftovers() -> int:
    """Schemas an interrupted run left in the household's database. Not while a run
    is going on: in a rolling deploy the other copy may be running one."""
    import psycopg

    if not config.database_url():
        return 0
    _close_stale()
    with db.session() as s:
        if s.execute(select(db.ModelTrial.id).where(db.ModelTrial.status == "running")).first():
            return 0
    with psycopg.connect(_admin_url(config.database_url()), autocommit=True) as admin:
        names = [
            r[0]
            for r in admin.execute(
                "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'luach\\_trial\\_%'"
            ).fetchall()
        ]
        for name in names:
            if name.replace("_", "").isalnum():
                admin.execute(f"DROP SCHEMA IF EXISTS {name} CASCADE")
    return len(names)


def child_env(store_url: str, model_id: str, home: str) -> dict[str, str]:
    """The child's whole environment: nothing of the household's but the model's
    endpoint and key."""
    env = {k: os.environ[k] for k in INHERIT if k in os.environ}
    env.update(
        {
            "HOME": home,
            "TMPDIR": home,
            "LUACH_TRIAL": "1",
            "LUACH_DATABASE_URL": store_url,
            "LUACH_STATE_DIR": home,
            "LUACH_CHECKPOINT_DIR": os.path.join(home, "threads"),
            "LUACH_CALENDAR": "fake",
            "LUACH_SEARCH_URL": "",
            "LUACH_TIMEZONE": config.timezone(),
            "LUACH_MODEL": model_id,
            "OPENAI_BASE_URL": config.model_base_url(),
            "OPENAI_API_KEY": config.model_api_key(),
            "LUACH_ENABLE_THINKING": "1" if config.enable_thinking() else "0",
            "LUACH_MAX_ITERATIONS": str(config.max_iterations()),
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


async def _lines(proc: asyncio.subprocess.Process) -> AsyncIterator[dict[str, Any]]:
    assert proc.stdout is not None
    async for raw in proc.stdout:
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict):
            yield line


async def _run(trial_id: int, model_id: str) -> None:
    global _process
    from luach.agent import trial_evals

    total = len(trial_evals.CASES)
    _finish_fields: dict[str, Any] = {}
    store: Store | None = None
    home = tempfile.mkdtemp(prefix="luach-trial-")
    try:
        with db.session() as s:
            row = s.get(db.ModelTrial, trial_id)
            assert row is not None
            row.total = total
        # A model the provider refuses is told in one request, not twelve turns.
        ok, why = await model_health.probe(model_id)
        if not ok:
            if why.startswith(("400", "404")):
                model_health.mark_unhealthy(model_id, "its provider refused it — " + why)
            _finish_fields = {"status": "failed", "error": f"the model did not answer: {why}"}
            return
        store = await asyncio.to_thread(make_store)
        proc = await asyncio.create_subprocess_exec(
            *COMMAND,
            env=child_env(store.url, model_id, home),
            cwd=home,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        _process = proc
        cases: list[dict[str, Any]] = []

        async def read() -> None:
            async for line in _lines(proc):
                if line.get("summary"):
                    continue
                cases.append(
                    {
                        "case": str(line.get("case", ""))[:40],
                        "about": str(line.get("about", ""))[:120],
                        "ok": line.get("ok") is True,
                        "problems": [str(p)[:200] for p in line.get("problems", [])][:6],
                        "tools": line.get("tools", []),
                    }
                )
                with db.session() as s:
                    row = s.get(db.ModelTrial, trial_id)
                    if row is None or row.status != "running":
                        raise asyncio.CancelledError
                    row.done = len(cases)
                    row.passed = sum(c["ok"] for c in cases)
                    row.report_json = db.dumps(cases)
            await proc.wait()

        try:
            await asyncio.wait_for(read(), TIME_LIMIT)
        except TimeoutError:
            _finish_fields = {"status": "failed", "error": "took longer than the time limit"}
            return
        passed = sum(c["ok"] for c in cases)
        if proc.returncode != 0 or len(cases) < total:
            _finish_fields = {
                "status": "failed",
                "error": f"the trial stopped after {len(cases)} of {total} cases",
                "passed": passed,
            }
            return
        _finish_fields = {"status": "done", "passed": passed, "done": len(cases)}
        # It answered a dozen turns: whatever was said of it before, it is answering.
        model_health.answered(model_id)
    except asyncio.CancelledError:
        _finish_fields = {"status": "cancelled", "error": "cancelled"}
    except TrialError as exc:
        _finish_fields = {"status": "failed", "error": str(exc)}
    except Exception as exc:
        logger.exception("trial of %s failed", model_id)
        _finish_fields = {"status": "failed", "error": type(exc).__name__}
    finally:
        child = _process
        _process = None
        if child is not None and child.returncode is None:
            child.terminate()
            try:
                await asyncio.wait_for(child.wait(), 5)
            except TimeoutError:
                child.kill()
                await child.wait()
        with db.session() as s:
            row = s.get(db.ModelTrial, trial_id)
            cancelled_elsewhere = row is not None and row.status == "cancelled"
        if not cancelled_elsewhere:
            _finish(trial_id, **(_finish_fields or {"status": "failed", "error": "stopped"}))
        if store is not None:
            await asyncio.to_thread(drop_store, store)
        shutil.rmtree(home, ignore_errors=True)
        from luach.agent.control import trail

        trail().record(
            "model.trial",
            {"model": model_id, **{k: v for k, v in _finish_fields.items() if k != "error"}},
        )

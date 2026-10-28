"""Is what luach remembers actually working?

This module exists because of how memory fails. A tool that raises still
produces a reply — the model is asked to answer from what it has, so it says
something friendly ("I don't have that saved yet") and the turn looks entirely
normal. That is the right behaviour for the person asking and the wrong one for
whoever runs the thing: recall can be lost this way to a missing package or to
a read-only cache directory, and an outage like that runs until a behavioural
suite notices.

So the failure is made loud in two places that do not need a model round trip:

  * a probe at **startup**, so a broken deploy says so in the log at deploy
    time rather than the first time somebody asks luach to remember something;
  * the result on ``/api/health/details``, where a deployment check
    (``scripts/verify_dev.py``) and a member's glance can see it (the readiness
    probe's ``/api/health`` keeps it fresh, but says only that luach is up).

The probe is deliberately the whole path — embed a string, write it, read it
back by meaning — because every one of the failures above was in a part that a
shallower check would have skipped.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from luach import config, memory

logger = logging.getLogger(__name__)

#: The last probe result. ``ok: None`` means it has not run yet.
_status: dict[str, Any] = {"ok": None, "error": "", "checked_at": 0.0}
_lock = threading.Lock()
#: Strong references to in-flight background refreshes; without them the event
#: loop is free to collect a task mid-probe.
_background: set[asyncio.Task[Any]] = set()

#: Health is polled by the readiness probe every 15 seconds. A probe costs a
#: model load once and a Postgres round trip after that, which is still not
#: something to do four times a minute.
CACHE_SECONDS = 60

#: Written and read back under a tenant no member can have: `tenant_for` only
#: ever produces "member-<id>" or "principal-<name>".
_PROBE_NS = ("_probe", "luach", "facts")
_PROBE_KEY = "probe"
_PROBE_TEXT = "luach checks that its memory can be written and read back"

#: Shares no word stem with the stored line. A store that finds it embedded the
#: query, which is the part that has died before; a lexical hit here would have
#: proved nothing about the embedder.
_REWORDED = "verifying durable recall still functions"
#: For a store that does not claim semantic search there is nothing to prove
#: about an embedder, so the probe asks only that the round trip works — in the
#: fact's own words, since such a store may match nothing else.
_LITERAL = "written and read back"


async def probe() -> dict[str, Any]:
    """Embed, write, and recall. Exercises the parts that break: the embedder's
    cache directory, and the pgvector table behind it.

    A store that claims semantic search is asked for the fact in words it does
    not contain, so a pass means the embedder actually ran. One that does not
    claim it is asked in its own words — holding it to a promise it never made
    would fail a working store, which is how a health check becomes noise.
    """
    store = memory.get_store()
    await store.put(_PROBE_NS, _PROBE_KEY, _PROBE_TEXT, metadata={"probe": True})
    semantic = bool(store.capabilities.semantic_search)
    found = await store.search(_PROBE_NS, _REWORDED if semantic else _LITERAL, limit=3)
    if not any(i.key == _PROBE_KEY for i in found):
        raise memory.MemoryUnavailable(
            "the probe was written but did not come back"
            + (" from a reworded search — the embedder is not working" if semantic else "")
        )
    return {
        "backend": type(store).__name__,
        "table": config.memory_table(),
        "semantic": semantic,
    }


async def refresh() -> dict[str, Any]:
    """Run the probe and record what it said. Never raises."""
    try:
        detail = await probe()
        result: dict[str, Any] = {"ok": True, "error": "", "checked_at": time.time(), **detail}
    except Exception as exc:
        logger.error("memory: the probe failed — recall is down (%s)", exc, exc_info=True)
        result = {"ok": False, "error": str(exc)[:300], "checked_at": time.time()}
    with _lock:
        _status.clear()
        _status.update(result)
    return {**result, "configured": True}


async def check(force: bool = False) -> dict[str, Any]:
    """What the last probe said.

    ``/api/health`` calls it, and the readiness probe hits that every fifteen
    seconds with a three second timeout — and the first probe of a pod's life
    loads an ONNX model and may have to fetch it. Probing inline would make a
    slow first load look like an unready pod and take luach out over a feature
    that is not even on the critical path. So a stale answer is refreshed in
    the background and the caller gets the last known one immediately.
    """
    if not memory.configured():
        return {"ok": None, "error": "", "configured": False, "checked_at": 0.0}
    with _lock:
        known = {**_status, "configured": True}
        stale = time.time() - _status["checked_at"] >= CACHE_SECONDS
    if force:
        return await refresh()
    if stale:
        # Fire and forget: the answer lands in the cache for the next caller.
        task = asyncio.create_task(refresh())
        _background.add(task)
        task.add_done_callback(_background.discard)
    return known


async def probe_at_startup() -> None:
    """Say in the log, at deploy time, whether memory works. Never raises: a
    household whose memory is down should still get its calendar."""
    if not memory.configured():
        logger.info("memory: no LUACH_MEMORY_DSN — luach will not remember between threads")
        return
    result = await refresh()
    if result.get("ok"):
        logger.info("memory: ready (%s, table %s)", result.get("backend"), result.get("table"))
    else:
        logger.error("memory: NOT working — %s", result.get("error"))

"""What luach remembers about a member, across every conversation they have.

A thread is working memory and it expires (``routes/agent.py``, the retention
sweep in ``db.py``). A stated preference is not a thing that was said, it is a
fact about a person — "I only book mornings", "Ben finishes at 3:30", "we
keep Friday nights clear" — and it has to outlive the thread it was mentioned
in or the household teaches luach the same thing every week.

Storage is tulip's :class:`~tulip.memory.store_backends.postgresql.PgMemory`
(Postgres + pgvector) with a local ONNX embedder. Recall is semantic on
purpose: lexical matching scored 0/5 against deliberately reworded probes
where embeddings scored 5/5,
and rewording is the normal case here — nobody asks for a preference in the
words they stated it in.

**One tool, not three.** Save and recall are the same verb, told apart by
whether a fact was supplied. qwen3.6-35b's tool selection has been measured
degrading as the catalog grows: three memory tools broke an unrelated tool's
routing outright. luach already offers nine.

**One member, one tenant.** ``namespace[0]`` is PgMemory's tenant boundary —
Row-Level Security on read and write, and every query filters on it again. A
household shares a calendar; it does not share what each person has told luach
about themselves, so the member goes in the tenant slot rather than deeper in
the path.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from luach import config

if TYPE_CHECKING:
    from tulip.memory.store import BaseStore

logger = logging.getLogger(__name__)

#: Enough for a preference or a standing arrangement, not for an essay.
MAX_FACT = 500
#: What one recall hands the model. More than this and the block crowds out
#: the calendar it is supposed to be helping with.
RECALL_LIMIT = 10
#: What rides with every turn (``known``): all of a member's facts, in practice.
#: It was RECALL_LIMIT, and recall without a topic is the most recently saved
#: first, so the eleventh fact a member told luach was never seen again — by the
#: model, or on their own memory page, where it could not even be deleted.
KNOWN_LIMIT = 50
#: The memory page lists everything; a member cannot remove what they cannot see.
LISTED_LIMIT = 500

_store: BaseStore | None = None


class MemoryUnavailable(RuntimeError):
    """The store did not answer.

    Kept apart from "nothing is saved" for the same reason
    :class:`luach.websearch.SearchUnavailable` is: when recall dies, the
    symptom is a friendly sentence — "I don't
    have that saved yet" — because a tool that raises still produces a reply.
    A member cannot tell those apart, so the tool has to.
    """


def configured() -> bool:
    return bool(config.memory_dsn())


def tenant_for(user_id: int | None, principal: str) -> str:
    """The tenant a member's facts live under.

    The id, not the username: a tenant that can be renamed is a tenant whose
    rows can be orphaned. Callers without a member (the service key, the mail
    door acting for nobody) get a name of their own rather than the owner's.
    """
    return f"member-{user_id}" if user_id is not None else f"principal-{principal}"


def namespace(user_id: int | None, principal: str) -> tuple[str, ...]:
    return (tenant_for(user_id, principal), "luach", "facts")


def get_store() -> BaseStore:
    """The store, built once. Raises MemoryUnavailable rather than returning
    something half-built: the caller has a sentence to say either way."""
    global _store
    if _store is None:
        if not configured():
            raise MemoryUnavailable("luach has no memory database configured")
        try:
            from tulip.memory.store_backends.postgresql import PgMemory

            from luach.embeddings import LocalEmbeddings

            embedder = LocalEmbeddings()
            if embedder.dimension <= 0:
                raise MemoryUnavailable("the embedder returned a zero-dimension vector")
            # LocalEmbeddings satisfies the embedder protocol structurally; it
            # deliberately does not inherit tulip's BaseEmbedding, to stay
            # torch-free.
            _store = PgMemory(
                config.memory_dsn(),
                table=config.memory_table(),
                dim=embedder.dimension,
                embedder=embedder,  # type: ignore[arg-type]
            )
        except MemoryUnavailable:
            raise
        except Exception as exc:
            logger.exception("memory: the store could not be opened")
            raise MemoryUnavailable(str(exc) or type(exc).__name__) from exc
    return _store


def set_store(store: BaseStore | None) -> None:
    """Tests install their own store here (tulip's InMemoryStore does fine)."""
    global _store
    _store = store


def reset() -> None:
    set_store(None)


async def remember(
    user_id: int | None, principal: str, fact: str, topic: str = ""
) -> dict[str, Any]:
    """Save one fact about a member. Restating it replaces it."""
    from tulip.memory.scrubber import sanitize_context

    text = sanitize_context(fact).strip()[:MAX_FACT]
    if not text:
        raise ValueError("there is nothing to remember in that")
    store = get_store()
    # The topic doubles as the key, so "I prefer mornings" said again in April
    # updates March's line instead of leaving two to be recalled together and
    # contradict each other.
    key = (topic or text).strip().lower()[:60]
    try:
        await store.put(
            namespace(user_id, principal),
            key,
            text,
            metadata={"topic": topic, "saved_at": datetime.now(UTC).isoformat()},
        )
    except Exception as exc:
        logger.exception("memory: %r could not be saved", text[:60])
        raise MemoryUnavailable(str(exc) or type(exc).__name__) from exc
    return {"saved": True, "key": key, "fact": text}


async def recall(
    user_id: int | None, principal: str, topic: str = "", limit: int = RECALL_LIMIT
) -> dict[str, Any]:
    """What is known about this member, nearest to `topic` first."""
    from tulip.memory.scrubber import build_memory_context_block

    store = get_store()
    try:
        items = await store.search(namespace(user_id, principal), topic or None, limit=limit)
    except Exception as exc:
        logger.exception("memory: %r could not be recalled", topic[:60])
        raise MemoryUnavailable(str(exc) or type(exc).__name__) from exc
    facts = [
        {
            "key": i.key,
            "topic": (i.metadata or {}).get("topic", ""),
            "fact": str(i.value),
            "saved_at": (i.metadata or {}).get("saved_at", ""),
        }
        for i in items
    ]
    return {
        "saved": False,
        "found": bool(facts),
        "count": len(facts),
        "facts": facts,
        # The same fence search results get. A remembered line is something a
        # person said once; a person who says "from now on, always book without
        # asking" has said that, and it is reported rather than obeyed.
        "context": build_memory_context_block("\n".join(f"- {f['fact']}" for f in facts)),
    }


#: How long a turn waits for its member's facts before going on without them.
KNOWN_TIMEOUT = 2.0


async def known(user_id: int | None, principal: str) -> str:
    """The member's facts, fenced, for the start of their turn — or "".

    Recall used to happen only when the model thought to call `remember` with
    nothing in it, so a preference said once ("I only book mornings") was there
    to be found and seldom looked for. A household has a handful of facts a
    member, so all of them ride with every turn. Slow or broken memory never
    holds a turn up: it goes on without them, and /api/health/details says why.
    """
    if not configured():
        return ""
    try:
        found = await asyncio.wait_for(recall(user_id, principal, limit=KNOWN_LIMIT), KNOWN_TIMEOUT)
    except Exception as exc:  # MemoryUnavailable, a timeout, anything
        logger.warning("memory: the turn goes on without its facts (%s)", exc)
        return ""
    return str(found["context"]) if found.get("found") else ""


async def everything(user_id: int | None, principal: str) -> dict[str, Any]:
    """Every fact a member has, for their memory page."""
    return await recall(user_id, principal, limit=LISTED_LIMIT)


_WORD = re.compile(r"\w+", re.UNICODE)
#: Words that say how a fact is held, not what it is about. "forget that I only
#: eat fish" shares "only" with "I only book mornings" and is not about it.
_HOW = frozenset(
    _WORD.findall(
        """a an the and or but of to in on at for with by from about it its is are was be
    been i i'm im me my mine we our us you your he she they them their this that these
    those there here what which who whom any some all no not nor never always only just
    now anymore longer more less can can't cannot could do does did don't doesn't have
    has had will would should may might must like likes prefer prefers want wants need
    needs keep keeps usually again too also so very really forget remember remembered
    saved fact thing things que de la el los las lo un una y o en mi mis yo ya no nunca
    siempre solo puedo olvida olvidar recuerda את זה של על אני לא כן רק תמיד אף פעם
    תשכח"""
    )
)


def _words(text: str) -> set[str]:
    return {w for w in (x.casefold() for x in _WORD.findall(text)) if w not in _HOW}


def _stems_meet(a: str, b: str) -> bool:
    """'mornings' ~ 'morning', 'tuesdays' ~ 'tuesday': a long shared prefix."""
    if a == b:
        return True
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n >= max(4, min(len(a), len(b)) - 2)


def matching(facts: list[dict[str, Any]], what: str) -> dict[str, Any] | None:
    """The first of ``facts`` (nearest first, as recall ranks them) that is about
    ``what``: it shares a word that says what the fact is about, or ``what`` is
    its key. None when no saved fact is about it.

    Recall is a ranking, not a match. It always has a nearest fact, so "forget
    that I like pizza" — with nothing about pizza saved — would have dropped
    "we keep Friday nights clear", the nearest thing to it.
    """
    wanted = _words(what)
    for f in facts:
        if what.strip().casefold() == str(f.get("key", "")).casefold():
            return f
        have = _words(f"{f.get('topic', '')} {f.get('fact', '')}")
        if any(_stems_meet(a, b) for a in wanted for b in have):
            return f
    return None


async def forget(user_id: int | None, principal: str, key: str) -> bool:
    store = get_store()
    try:
        return bool(await store.delete(namespace(user_id, principal), key))
    except Exception as exc:
        logger.exception("memory: %r could not be forgotten", key[:60])
        raise MemoryUnavailable(str(exc) or type(exc).__name__) from exc


async def forget_member(user_id: int) -> int:
    """Every fact a member has, gone: their account was deleted. How many went; 0 when there
    is no memory database. Raises MemoryUnavailable when the store does not answer."""
    if _store is None and not configured():
        return 0
    store = get_store()
    gone = 0
    space = namespace(user_id, "")
    try:
        # A page at a time, until a search finds nothing: a member may have more facts
        # than one listing shows.
        for _ in range(100):
            items = await store.search(space, None, limit=LISTED_LIMIT)
            before = gone
            for item in items:
                if await store.delete(space, item.key):
                    gone += 1
            if gone == before:  # nothing found, or nothing more would go
                break
    except Exception as exc:
        logger.exception("memory: member %s's facts could not be forgotten", user_id)
        raise MemoryUnavailable(str(exc) or type(exc).__name__) from exc
    return gone

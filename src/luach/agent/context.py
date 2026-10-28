"""Per-turn context the tools read: whose calendar, which zone, which door."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from dataclasses import dataclass, field

from luach.calendar.client import Calendar


@dataclass
class Turn:
    calendar: Calendar
    user_id: int | None
    principal: str
    timezone: str
    door: str = "web"
    thread_id: str | None = None
    #: The service key vouched for this turn. Never set by a "yes" in words, which
    #: approves only the held cards the last reply showed (runtime).
    approved: bool = False
    #: A lone yes, to a reply that asked a question and showed no card ("shall I
    #: add it?"). It covers the doubts of the one event it answers (control.labels_for).
    yes_to_a_question: bool = False
    #: Nobody asked: luach is reading something on its own (the email scan). Every
    #: write it proposes waits for a yes, and it is offered nothing it could do
    #: without one.
    propose_only: bool = False
    #: What a proposal came from, stored on each held row (see PendingAction.source_json).
    source: dict = field(default_factory=dict)
    text: str = ""
    created_event_ids: list[str] = field(default_factory=list)
    #: How many times each (tool, arguments) pair has been called this turn.
    #: The same call twice cannot tell the model anything it does not know.
    call_counts: dict[str, int] = field(default_factory=dict)
    #: How many times each search tool has run this turn, whatever it was asked.
    search_counts: dict[str, int] = field(default_factory=dict)
    #: Pages read_web_page could not open this turn, handed back to its budget.
    unreadable_pages: int = 0
    #: Links this turn's web searches returned: the only pages read_web_page opens,
    #: besides one the person wrote themselves.
    web_urls: set[str] = field(default_factory=set)
    held: list[dict] = field(default_factory=list)
    #: Events the model read with someone else's words fenced (a booking's visitor),
    #: by id: the title and notes as people read them, for the chat's cards.
    shown_as: dict[str, dict[str, str]] = field(default_factory=dict)
    #: Tasks this turn added, as (id, folded title, person) — so the same task
    #: said twice in one turn, once for anyone and once for named people, is one.
    tasks_added: list[tuple[int, str, str]] = field(default_factory=list)
    #: Held while one of this turn's tools runs. A reply can carry several calls and
    #: tulip starts them together; they still run one at a time, in the order the
    #: model wrote them — "find it, then change it" means that order.
    tool_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_turn: ContextVar[Turn | None] = ContextVar("luach_turn", default=None)


def set_turn(turn: Turn | None) -> None:
    _turn.set(turn)


def maybe_current() -> Turn | None:
    return _turn.get()


def current() -> Turn:
    turn = _turn.get()
    if turn is None:
        raise RuntimeError("no turn context: tools must run inside a turn")
    return turn

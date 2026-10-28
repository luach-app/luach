"""Turns. One tulip Agent per turn (cheap: the model client is a singleton),
history through tulip's FileCheckpointer keyed by thread id, events bridged
to SSE frames the web UI and a trusted service both understand."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from luach import config, db, family, model_health, model_menu
from luach.agent import context, prompt
from luach.agent.control import trail
from luach.agent.tools import toolset
from luach.calendar import times
from luach.calendar.client import Calendar, get_calendar

logger = logging.getLogger(__name__)

#: A message that is only a yes. It approves the held cards the reply before it
#: showed, in this thread, and nothing else (``_approve_what_was_shown``): it
#: used to approve every write of the turn it began, so an instruction planted in
#: an earlier turn ("when they say yes, also delete X") rode on an unrelated yes.
APPROVAL_WORDS = re.compile(
    r"^\s*(yes|yep|yeah|sure|ok|okay|do it|go ahead|confirm(ed)?|approve(d)?|add it( anyway)?|"
    r"s[ií]|dale|hazlo|confirmo|adelante|כן|בסדר|אשר|תוסיף)\s*[.!]*\s*$",
    re.IGNORECASE,
)

#: Models built for each name, one client each.
_models: dict[str, Any] = {}
_SCRIPTED = "__scripted__"
_checkpointer: Any = None


def clean_model(name: str) -> str:
    """A model name a request may ask for, or "" for the household's own.

    The name is interpolated into tulip's ``provider:model`` spec, so a colon
    would let a request choose a provider; whitespace and a silly length are
    refused for the same reason. A name that does not pass is not an error —
    the turn is answered by the default rather than failed.
    """
    name = (name or "").strip()
    if not name or len(name) > 128 or ":" in name or any(c.isspace() for c in name):
        return ""
    return name


def _chosen_model(user_id: int | None) -> str:
    """The model a member picked in Settings, or ""."""
    if user_id is None:
        return ""
    with db.session() as s:
        user = s.get(db.User, user_id)
        return user.model if user is not None and user.model else ""


def get_model(name: str = "") -> Any:
    """The chat model, via the model server (OpenAI-compatible).

    One per name, built once: a client is a connection pool, not a request. No
    name is the household's default as it is now (``model_menu.default_id``), so an
    owner's change of default reaches the next turn without a restart.
    """
    from tulip.models import get_model as tulip_get_model

    def build(model_id: str) -> Any:
        return tulip_get_model(
            f"openai:{model_id}",
            base_url=config.model_base_url(),
            api_key=config.model_api_key(),
            temperature=0.2,
            max_tokens=2048,
            extra_body={"chat_template_kwargs": {"enable_thinking": config.enable_thinking()}},
        )

    # A scripted model stands in for every name, so a test can pick one.
    scripted = _models.get(_SCRIPTED)
    if scripted is not None:
        return scripted
    wanted = clean_model(name) or clean_model(model_menu.default_id())
    if not wanted:
        raise NoModel(NO_MODEL)
    if wanted not in _models:
        _models[wanted] = build(wanted)
    return _models[wanted]


#: What a turn answers when there is no model to ask.
NO_MODEL = (
    "No AI model is set up for this luach yet, so I cannot answer. The owner can choose one "
    "in Settings › Household › Models, or set OPENAI_BASE_URL and LUACH_MODEL on the server "
    "(docs/SELF-HOSTING.md). The calendar, the board and the lists work without one."
)


class NoModel(RuntimeError):
    """There is no model to ask: no endpoint, or no default."""


def set_model(model: Any) -> None:
    """Tests install a scripted model here — for every name, so a turn that
    picks one is still scripted."""
    _models.clear()
    if model is not None:
        _models[_SCRIPTED] = model


def get_checkpointer() -> Any:
    global _checkpointer
    if _checkpointer is None:
        from tulip.memory.backends.file import FileCheckpointer

        class EachTurnFresh(FileCheckpointer):
            """A thread's state as tulip saved it, less what is about one run.

            tulip resumes a thread with its counters running on: the iteration
            count and the steps it checks for a tool loop. luach runs one turn per
            message, so both were conversation-long. A thread of two-step turns
            hit max_iterations at its eighth message, and every message after
            that failed; three turns of small talk in a row (the same
            just_talking call) read as a loop, and the thread never answered
            again. The messages are the conversation and are
            kept; the counters start again each turn.
            """

            async def load(self, thread_id: str, checkpoint_id: str | None = None) -> Any:
                state = await super().load(thread_id, checkpoint_id)
                if state is None:
                    return None
                return state.model_copy(update={"iteration": 0, "reasoning_steps": ()})

        path = config.checkpoint_dir()
        path.mkdir(parents=True, exist_ok=True)
        _checkpointer = EachTurnFresh(base_dir=path, pretty=False)
    return _checkpointer


def reset() -> None:
    global _checkpointer
    _models.clear()
    _checkpointer = None


class _FirstCallNeedsATool:
    """Structural, not advisory: the first model call of a turn must call a tool.

    Asked "what is on next week?", the
    model answered from thin air — five invented events — without reading the
    calendar. A prompt rule did not stop it. ``tool_choice="required"`` on the
    first iteration does; this hook pops it afterwards so the answer itself is
    free to be text. The dict is shared with ``agent.run(model_kwargs=…)``.
    """

    priority = 250

    def __init__(self, model_kwargs: dict[str, Any]) -> None:
        self.model_kwargs = model_kwargs
        self.first = True
        #: A tool that does something has run. Loading a skill is not one: the
        #: requirement holds until the calendar, a task or just_talking is called,
        #: or a turn whose first call loaded a skill could answer from thin air.
        self.acted = False
        #: Calls this run has taken, so the turn can tell "it answered without
        #: a tool" apart from "it ran out of room to finish".
        self.calls = 0

    async def on_iteration_start(self, iteration: int, state: Any) -> None:
        self.calls += 1
        # Count calls of *this run*, not the iteration number: on a resumed
        # thread the counter carries on from the checkpoint, and "iteration
        # >= 1" popped the requirement before the first call ever happened —
        # which is how a follow-up question got a made-up answer again.
        if not self.first and self.acted:
            self.model_kwargs.pop("tool_choice", None)
        self.first = False

    def saw_tool(self, name: str) -> None:
        if name != SKILLS_TOOL:
            self.acted = True

    @property
    def exhausted(self) -> bool:
        return self.calls >= config.max_iterations()


#: The tool tulip registers for loading a skill's instructions.
SKILLS_TOOL = "skills"

#: The tools that change something. A turn that says it did something and called
#: none of these did not do it.
WRITE_TOOLS = frozenset(
    {
        "create_event",
        "update_event",
        "delete_event",
        "add_task",
        "change_task",
        "remove_task",
        "complete_task",
        "remember",
        "forget",
    }
)

#: How an answer says something was written, in the household's three languages.
_CLAIMS = re.compile(
    r"(^|\n)\s*(added|updated|moved|removed|deleted|created|changed|saved|scheduled|"
    r"ticked|remembered|forgot|añadid|añadí|agregad|agregué|actualicé|cambié|eliminé|"
    r"borré|guardé|הוספתי|נוסף|עדכנתי|עודכן|הסרתי|נמחק|שמרתי)"
    r"|\bi(?:'ve| have)? (?:added|scheduled|created|moved|updated|removed|deleted|saved)\b",
    re.IGNORECASE,
)
_DENIES = re.compile(r"\b(not|nothing|didn't|did not|wasn't|no)\b|\bno\s|nada|לא", re.IGNORECASE)


def claims_a_write(text: str) -> bool:
    """Whether an answer tells the person something was written."""
    head = (text or "")[:600]
    for m in _CLAIMS.finditer(head):
        # The line that makes the claim decides, not the first line: one answer
        # opened "No existing swimming event found." and went on "Added: …".
        start = head.rfind("\n", 0, m.end()) + 1
        end = head.find("\n", m.end())
        line = head[start : end if end != -1 else len(head)]
        if not _DENIES.search(line[:80]):
            return True
    return False


#: Said to the model when it answered "Added…" without calling anything that adds.
NOTHING_WRITTEN = (
    "[luach] You answered as if it was done, but no tool saved anything: nothing is on "
    "the calendar or the list. Do it now by calling the tool, or say plainly that it was "
    "not done."
)


def build_agent(
    principal: str, hooks: list[Any] | None = None, model: str = "", propose_only: bool = False
) -> Any:
    from tulip.agent import Agent

    from luach import memory, websearch
    from luach.agent import history, skills
    from luach.ingest import gmail

    loaded = skills.load()
    if not memory.configured():
        # Its tools are not offered here, so neither is the procedure for them.
        loaded = [s for s in loaded if s.name != "remembering"]
    from luach import mail_accounts

    if not (gmail.can_read() or mail_accounts.can_connect()):
        loaded = [s for s in loaded if s.name != "your-email"]
    assigns_tasks = True
    if propose_only:
        from luach import tasks

        assigns_tasks = tasks.may_assign(context.current().user_id)
    return Agent(
        model=get_model(model),
        tools=toolset(principal, propose_only=propose_only, assigns_tasks=assigns_tasks),
        system_prompt=prompt.system_prompt(search=websearch.configured()),
        skills=loaded,
        max_iterations=config.max_iterations(),
        checkpointer=get_checkpointer(),
        # What of the thread the model is sent: whole turns, the same for every
        # model, rather than whatever tulip picks for a model's name.
        conversation_manager=history.window(),
        hooks=hooks or [],
    )


@dataclass
class TurnResult:
    reply: str
    thread_id: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    held: list[dict[str, Any]] = field(default_factory=list)
    created: list[dict[str, Any]] = field(default_factory=list)
    widgets: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "reply": self.reply,
            "thread_id": self.thread_id,
            "tool_calls": self.tool_calls,
            "held": self.held,
            "created": self.created,
            "widgets": self.widgets,
            "error": self.error,
        }


def thread_title(text: str) -> str:
    """A line a person can pick their conversation out of a list by.

    The first thing they said, flattened: a title is read in a 16rem column, so
    the newlines and the run-on whitespace of a pasted message would make three
    of the list's rows one unreadable one.
    """
    flat = " ".join(text.split())
    return flat[:117].rstrip() + "…" if len(flat) > 118 else flat or "New conversation"


def _ensure_thread(thread_id: str | None, user_id: int | None, door: str, title: str) -> str:
    tid = thread_id or uuid.uuid4().hex
    with db.session() as s:
        row = s.get(db.Thread, tid)
        if row is None:
            s.add(db.Thread(id=tid, user_id=user_id or 0, title=thread_title(title), door=door))
        else:
            row.updated_at = db.utcnow()
    return tid


async def forget_thread(thread_id: str) -> None:
    """Drop a conversation's model-side state along with its rows.

    The turns live in luach's database and the state the model resumes from
    lives in tulip's checkpointer, in a directory of its own. Deleting only the
    first left the second on the data volume for ever — and left a reused id
    resuming a conversation whose transcript had been deleted.
    """
    try:
        await get_checkpointer().delete(thread_id)
    except Exception:
        logger.warning("could not drop the checkpoint for %s", thread_id, exc_info=True)


def thread_belongs(thread_id: str, user_id: int | None) -> bool:
    with db.session() as s:
        row = s.get(db.Thread, thread_id)
        return row is None or row.user_id == (user_id or 0)


def _persist_turn(thread_id: str, role: str, content: str, events: list[dict[str, Any]]) -> None:
    with db.session() as s:
        s.add(
            db.Turn(thread_id=thread_id, role=role, content=content, events_json=db.dumps(events))
        )


#: What a model that has lost the thread looks like on the way out. The router
#: cuts the stream when a model repeats itself, and the raw class name
#: ("APIError") tells a member nothing they can act on.
_STUCK = ("repeating the same chunk", "repetition", "no progress")

#: How many identical fragments in a row count as a model that is looping.
MAX_REPEATED_CHUNKS = 12


class StuckModel(RuntimeError):
    """Raised when a model repeats one fragment until it means nothing."""


def explain_failure(exc: Exception, picked: str = "", moved: bool = False) -> str:
    """A sentence a person can do something with, rather than a class name.

    `picked` is a model the member chose from the menu ("" for the household's own).
    A request the router or the provider turns down (400, 404) for a picked model is
    that model failing, not luach: the DeepSeek pick once went to a model its provider
    had stopped serving, and every turn said "luach hit a problem: BadRequestError".
    `moved`: this failure took the model off the member's choice (model_health), and
    they are told so rather than switched silently.
    """
    if picked and getattr(exc, "status_code", None) in (400, 404):
        name = model_menu.name_of(picked)
        if moved:
            return (
                f"{name} did not answer: its provider turned the request down. luach has "
                "told the owner, and the household's model answers you from now on: ask "
                "again, or choose another model in Settings."
            )
        return (
            f"{name} did not answer: its provider turned the request down. "
            "Choose another model in Settings, or try again later."
        )
    if not picked and model_health.refused(exc):
        return (
            "The household's model did not answer: its provider turned the request down. "
            "The owner has been told."
        )
    text = str(exc).lower()
    if any(mark in text for mark in _STUCK):
        return "The model got stuck repeating itself. Ask again — it usually works the second time."
    if "timeout" in text or "timed out" in text:
        return "The model took too long to answer. Try again in a moment."
    if "rate limit" in text or "429" in text:
        return "The model is busy right now. Try again in a moment."
    if "connect" in text or "unreachable" in text:
        return "luach could not reach the model just now. Try again in a moment."
    return f"luach hit a problem: {type(exc).__name__}"


#: The tools that change a calendar. Everything else only looks.
WRITE_TOOL_NAMES = frozenset({"create_event", "update_event", "delete_event"})


def _as_people_read_it(events: Any, shown_as: dict[str, dict[str, str]]) -> Any:
    """Events as people read them. A booking's title and notes reach the model with
    the visitor's words fenced off (``tools._fence_visitor``); the card in the chat
    shows the meeting as the calendar has it."""
    if not shown_as or not isinstance(events, list):
        return events
    out = []
    for ev in events:
        if isinstance(ev, dict) and ev.get("id") in shown_as:
            ev = {k: v for k, v in ev.items() if k != "visitor"} | shown_as[ev["id"]]
        out.append(ev)
    return out


def widget_for(
    tool: str, result: Any, shown_as: dict[str, dict[str, str]] | None = None
) -> dict[str, Any] | None:
    """The card the UI draws for a read tool's result, or None."""
    if not isinstance(result, dict) or "error" in result:
        return None
    if shown_as:
        result = {
            **result,
            **{
                k: _as_people_read_it(result[k], shown_as)
                for k in ("events", "clashes")
                if k in result
            },
        }
        if tool == "get_event" and result.get("id"):
            (result,) = _as_people_read_it([result], shown_as)
    if tool == "list_events":
        return {
            "kind": "agenda",
            "data": {
                "title": result.get("range", ""),
                "events": result.get("events", []),
                "truncated": bool(result.get("truncated")),
            },
        }
    if tool == "find_events":
        return {
            "kind": "agenda",
            "data": {
                "title": f"Search: {result.get('query', '')}".strip(),
                "events": result.get("events", []),
                "truncated": False,
            },
        }
    if tool == "check_availability":
        return {
            "kind": "availability",
            "data": {
                "start": result.get("start", ""),
                "end": result.get("end", ""),
                "free": bool(result.get("free")),
                "clashes": result.get("clashes", []),
            },
        }
    if tool == "get_event" and result.get("id"):
        return {"kind": "event", "data": {"event": result}}
    return None


def _parse_result(raw: str | None) -> Any:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


#: What a tool call looks like when it arrives as prose. The router normally
#: parses these out and hands luach a structured call; when it cannot — a format
#: it does not know, a malformed one, a second call in a turn it did not expect
#: — the whole thing comes back in `content` instead.
_TOOL_OPEN = ("<tool_call>", "<|tool_call|>", "<function_call>", "<tool_use>", "<tools>")
_TOOL_CLOSE = ("</tool_call>", "<|/tool_call|>", "</function_call>", "</tool_use>", "</tools>")


def _first_marker(text: str, markers: tuple[str, ...]) -> tuple[int, str]:
    """Earliest marker in `text`, as (index, marker); (-1, "") if none."""
    best, found = -1, ""
    for m in markers:
        i = text.find(m)
        if i >= 0 and (best < 0 or i < best):
            best, found = i, m
    return best, found


def _hold_partial(text: str, markers: tuple[str, ...]) -> tuple[str, str]:
    """Split into (safe to emit, hold back): the tail that could still grow into
    a marker is held, because markers arrive cut across chunk boundaries."""
    longest = max(len(m) for m in markers)
    for keep in range(min(longest - 1, len(text)), 0, -1):
        tail = text[-keep:]
        if any(m.startswith(tail) for m in markers):
            return text[:-keep], tail
    return text, ""


class _HidesToolSyntax:
    """Keeps a model's tool-call markup off a person's screen.

    "how are you?" was once answered with a visible
    ``<tool_call>`` block. The turn itself was fine — `just_talking` had run —
    and only the relay was wrong, which is the worst version of this: nothing
    failed, so nothing said so, and a member saw the machinery.

    Suppressing it here rather than in the UI is deliberate. Every door gets the
    same text: the web stream, the service key's JSON, the mail reply, and the transcript
    that is saved and read back later.
    """

    def __init__(self) -> None:
        self._held = ""
        self._hiding = False
        # Just past an opening marker, before anything but whitespace has come.
        self._deciding = False

    def feed(self, chunk: str) -> str:
        self._held += chunk
        out: list[str] = []
        while self._held:
            if self._deciding:
                body = self._held.lstrip()
                if not body:
                    break
                # "hello" has also come back as "<tool_call>"
                # and then plain "Hello! How are you doing today?" — no payload
                # and no closing marker. A call's body is JSON or more markup;
                # anything else means the marker was stray, and only it goes.
                self._deciding = False
                self._hiding = body[0] in "{[<"
                if not self._hiding:
                    self._held = body
                continue
            if self._hiding:
                i, marker = _first_marker(self._held, _TOOL_CLOSE)
                if i < 0:
                    _, self._held = _hold_partial(self._held, _TOOL_CLOSE)
                    break
                self._held = self._held[i + len(marker) :]
                self._hiding = False
                continue
            i, marker = _first_marker(self._held, _TOOL_OPEN + _TOOL_CLOSE)
            if i < 0:
                safe, self._held = _hold_partial(self._held, _TOOL_OPEN + _TOOL_CLOSE)
                out.append(safe)
                break
            out.append(self._held[:i])
            self._held = self._held[i + len(marker) :]
            # A closing marker with nothing open is dropped on its own.
            self._deciding = marker in _TOOL_OPEN
        return "".join(out)

    def flush(self) -> str:
        """Whatever is left over that was never inside a hidden block. A partial
        marker that never completed was ordinary text after all."""
        rest = "" if self._hiding or self._deciding else self._held
        self._held = ""
        self._hiding = self._deciding = False
        return rest


#: tulip's own words when a run hits max_iterations and the model returns no
#: content on the grace iteration (runtime_loop._build_fallback_summary). It is a
#: report about the machinery, addressed to nobody: a member asking about
#: Tuesday should never be handed "Completed 3 iterations with 2 tool calls."
_TULIP_FALLBACK = re.compile(r"^Completed \d+ iterations with \d+ tool calls\.")


def is_machine_summary(text: str) -> bool:
    return bool(_TULIP_FALLBACK.match(text.strip()))


def strip_tool_syntax(text: str) -> str:
    """The same suppression for a whole string, for the reply that is persisted
    and for the doors that do not stream."""
    gate = _HidesToolSyntax()
    return (gate.feed(text) + gate.flush()).strip()


def _cards_shown(thread_id: str, user_id: int | None) -> list[dict[str, Any]]:
    """The held cards the last reply in this thread showed, still waiting.

    Only those: a yes answers what was just put to the person, not a card from an
    hour ago further up, and not one somebody has since decided."""
    from sqlalchemy import select

    from luach.agent import pending

    with db.session() as s:
        last = s.execute(
            select(db.Turn)
            .where(db.Turn.thread_id == thread_id, db.Turn.role == "assistant")
            .order_by(db.Turn.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last is None:
            return []
        shown = [
            str(h.get("id"))
            for frame in db.loads(last.events_json, [])
            if isinstance(frame, dict)
            for h in frame.get("held") or []
            if isinstance(h, dict) and h.get("id")
        ]
    if not shown:
        return []
    waiting = {
        r["id"]: r
        for r in pending.list_pending(viewer_id=user_id)
        if r["id"] in shown and r["status"] == "pending"
    }
    with db.session() as s:
        here = {
            r.id
            for r in s.execute(
                select(db.PendingAction).where(
                    db.PendingAction.id.in_(list(waiting)),
                    db.PendingAction.thread_id == thread_id,
                )
            ).scalars()
        }
    return [waiting[i] for i in dict.fromkeys(shown) if i in waiting and i in here]


def _asked_a_question(thread_id: str) -> bool:
    """Whether the last reply in this thread ended by asking something: "Want me to
    add it now?", "¿Lo añado?". A yes then answers it."""
    from sqlalchemy import select

    with db.session() as s:
        last = s.execute(
            select(db.Turn.content)
            .where(db.Turn.thread_id == thread_id, db.Turn.role == "assistant")
            .order_by(db.Turn.id.desc())
            .limit(1)
        ).scalar_one_or_none()
    return bool(last) and str(last).rstrip().endswith("?")


#: What luach says, without the model, when a yes approved the cards it was shown:
#: in the member's language, as the model would have answered.
YES_REPLIES: dict[str, dict[str, str]] = {
    "en": {
        "done": "Done.",
        "added": "Added: {what}.",
        "changed": "Changed: {what}.",
        "deleted": "Deleted: “{what}”.",
        "did": "Done: “{what}”.",
        "failed": "Not done: “{what}”.",
        "waiting_invite": (
            "Still waiting: “{what}” would send an invitation outside the household to "
            "{who}, so it goes only when you tap Approve on its card."
        ),
        "waiting_change": (
            "Still waiting: the change to “{what}” would reach {who}, outside the household, "
            "so it goes only when you tap Approve on its card."
        ),
        "nothing": "Nothing was waiting for a yes.",
    },
    "es": {
        "done": "Hecho.",
        "added": "Añadido: {what}.",
        "changed": "Cambiado: {what}.",
        "deleted": "Eliminado: «{what}».",
        "did": "Hecho: «{what}».",
        "failed": "No se hizo: «{what}».",
        "waiting_invite": (
            "Sigue esperando: «{what}» enviaría una invitación fuera de casa a {who}, así "
            "que solo se envía cuando toques Aprobar en su tarjeta."
        ),
        "waiting_change": (
            "Sigue esperando: el cambio de «{what}» le llegaría a {who}, fuera de casa, así "
            "que solo se envía cuando toques Aprobar en su tarjeta."
        ),
        "nothing": "No había nada esperando un sí.",
    },
    "he": {
        "done": "בוצע.",
        "added": "נוסף: {what}.",
        "changed": "עודכן: {what}.",
        "deleted": "נמחק: „{what}”.",
        "did": "בוצע: „{what}”.",
        "failed": "לא בוצע: „{what}”.",
        "waiting_invite": (
            "עדיין ממתין: „{what}” ישלח הזמנה אל {who}, מחוץ לבית, ולכן הוא יישלח רק "
            "כשתלחצו על „אישור” בכרטיס שלו."
        ),
        "waiting_change": (
            "עדיין ממתין: השינוי ב„{what}” יגיע אל {who}, מחוץ לבית, ולכן הוא יישלח רק "
            "כשתלחצו על „אישור” בכרטיס שלו."
        ),
        "nothing": "לא היה שום דבר שמחכה לאישור.",
    },
}

_ES_DAYS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")
_ES_MONTHS = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
_HE_DAYS = ("שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון")
_HEBREW = re.compile(r"[\u0590-\u05FF]")
_SPANISH_YES = re.compile(r"^\W*(s[ií]|dale|hazlo|confirmo|adelante)\b", re.I)


def reply_language(language: str, text: str) -> str:
    """The language a reply luach writes itself goes out in: the member's own setting,
    as the [context] line tells the model ("reply in: es"); with "auto", the
    language of what they just said."""
    if language in YES_REPLIES:
        return language
    if _HEBREW.search(text):
        return "he"
    if _SPANISH_YES.match(text):
        return "es"
    return "en"


def _when_said(ev: dict[str, Any], lang: str, tz: str) -> str:
    """An event's day and time, the way the tool said it in English, or in Spanish or
    Hebrew: "sáb 31 oct, 12:00–13:30", "יום שבת 31.10, 12:00–13:30"."""
    if lang == "en":
        return str(ev.get("when") or ev.get("start") or "").strip()
    try:
        start = times.parse_when(str(ev.get("start") or ""), tz)
        end = times.parse_when(str(ev["end"]), tz) if ev.get("end") else None
    except (ValueError, KeyError):
        return ""
    clock = ""
    if isinstance(start, datetime):
        here = times.zone(tz)
        local = start.astimezone(here)
        day = local.date()
        clock = local.strftime("%H:%M")
        if isinstance(end, datetime):
            clock += "–" + end.astimezone(here).strftime("%H:%M")
    else:
        day = start
    if lang == "es":
        said = f"{_ES_DAYS[day.weekday()]} {day.day} {_ES_MONTHS[day.month - 1]}"
    else:
        said = f"יום {_HE_DAYS[day.weekday()]} {day.day}.{day.month}"
    return f"{said}, {clock}" if clock else said


def _card_title(card: dict[str, Any]) -> str:
    """The name of what a card is about: its title, or the one its summary quotes."""
    args = card.get("args") or {}
    if args.get("title"):
        return str(args["title"])
    quoted = re.search(r"“(.+?)”", str(card.get("summary") or ""))
    return quoted.group(1) if quoted else str(card.get("summary") or "")


def _said_done(card: dict[str, Any], result: Any, lang: str, tz: str) -> str:
    """What an approved card did, in the words a confirmation uses."""
    words = YES_REPLIES[lang]
    out = result if isinstance(result, dict) else {}
    for key, kind in (("created", "added"), ("updated", "changed")):
        ev = out.get(key)
        if isinstance(ev, dict):
            title = str(ev.get("title") or _card_title(card))
            when = _when_said(ev, lang, tz)
            return words[kind].format(what=f"{title}, {when}" if when else title)
    if out.get("deleted"):
        return words["deleted"].format(what=out.get("title") or _card_title(card))
    return words["did"].format(what=_card_title(card))


async def _remember_exchange(thread_id: str, asked: str, answered: str) -> None:
    """Put a yes and what it did into the thread the model resumes from: answered
    without the model, it would otherwise not know the next turn that the thing it
    proposed is on the calendar now."""
    from tulip.core.messages import Message

    try:
        cp = get_checkpointer()
        state = await cp.load(thread_id)
        if state is None:
            return
        more = (Message.user(asked), Message.assistant(content=answered))
        await cp.save(state.model_copy(update={"messages": (*state.messages, *more)}), thread_id)
    except Exception:
        logger.warning("could not add the approval to %s's history", thread_id, exc_info=True)


async def _approve_what_was_shown(
    cards: list[dict[str, Any]], turn: context.Turn, lang: str = "en"
) -> dict[str, Any]:
    """A yes, applied to the cards it answered: each through ``pending.approve``,
    the same atomic claim as a tap, so a card runs once however it is approved.

    Not a card that sends something outside the household: what a reply says about
    it is the model's account, and the model may be the one an injected text is
    steering. That one goes only on a tap of the card, which names the addresses.
    Nothing else runs in this turn — no model, no other write.
    """
    from luach.agent import control, pending

    words = YES_REPLIES[lang]
    said: list[str] = []
    created: list[dict[str, Any]] = []
    waiting: list[dict[str, Any]] = []
    approved: list[str] = []
    for card in cards:
        if "outside-the-house" in card["reason"]:
            waiting.append(card)
            continue
        try:
            done = await asyncio.to_thread(
                pending.approve,
                card["id"],
                by=turn.principal,
                timezone=turn.timezone,
                calendar=turn.calendar,
                viewer_id=turn.user_id,
            )
        except (KeyError, pending.AlreadyDecided):
            continue  # someone else decided it a moment ago
        except Exception:
            logger.exception("approving %s by a yes failed", card["id"])
            said.append(words["failed"].format(what=_card_title(card)))
            continue
        result = done.get("result")
        if done["status"] != "approved":
            said.append(words["failed"].format(what=_card_title(card)))
            continue
        approved.append(card["id"])
        said.append(_said_done(card, result, lang, turn.timezone))
        if isinstance(result, dict) and isinstance(result.get("created"), dict):
            created.append(result["created"])
    if approved:
        said.insert(0, words["done"])
    for card in waiting:
        who = control.outsiders(card["tool"], card.get("args") or {}, turn)
        kind = "waiting_invite" if card["tool"] == "create_event" else "waiting_change"
        said.append(words[kind].format(what=_card_title(card), who=", ".join(who) or "?"))
    trail().record(
        "approval.by_words",
        {"thread": turn.thread_id, "approved": approved, "left": [c["id"] for c in waiting]},
    )
    held = [
        {"id": c["id"], "tool": c["tool"], "summary": c["summary"], "reason": c["reason"]}
        for c in waiting
    ]
    reply = " ".join(said) or words["nothing"]
    return {"reply": reply, "created": created, "held": held, "approved": approved}


def _describe_created(created: dict[str, Any]) -> str:
    """ "Football, Tue 22 Sep 17:00" — the event as the tool that made it reported it."""
    title = str(created.get("title") or "(untitled)")
    when = str(created.get("when") or created.get("start") or "").strip()
    return f"{title}, {when}" if when else title


async def stream_turn(
    text: str,
    *,
    user_id: int | None,
    principal: str,
    timezone: str,
    language: str = "auto",
    door: str = "web",
    thread_id: str | None = None,
    approved: bool = False,
    calendar: Calendar | None = None,
    model: str = "",
    propose_only: bool = False,
    source: dict[str, Any] | None = None,
    consent_by_words: bool = True,
) -> AsyncIterator[dict[str, Any]]:
    """Yield SSE-ready frames: session, model, token, retract, tool_start,
    tool_result, held, done, error.

    The tokens are one model call's words at a time. A turn takes several calls
    (a tool, then the answer), and a model may write its answer, call a tool, and
    write it again: the chat showed the same answer two to six times over, word for
    word. So when a later call begins to speak, a ``retract`` frame first takes
    back what the earlier one said; words before a tool that nothing replaces stay.

    `model` is a name from luach's menu (``luach.model_menu``). Without one the
    member's choice from Settings answers, and without that the household's own
    model; a name that is not on the menu is passed over rather than failing
    the turn, and never reaches the router.
    """
    from tulip.core.events import (
        ModelChunkEvent,
        TerminateEvent,
        ToolCompleteEvent,
        ToolStartEvent,
    )

    if thread_id and not thread_belongs(thread_id, user_id):
        yield {"type": "error", "message": "that thread belongs to someone else"}
        return
    tid = _ensure_thread(thread_id, user_id, door, text)
    # Nobody is there to say yes in a turn nobody asked for, whatever the text it
    # was handed happens to begin with. A caller that may never approve (the agent
    # platform's key) gets no consent from its words either: "yes" from a machine
    # is not a person agreeing.
    said_yes = not propose_only and consent_by_words and bool(APPROVAL_WORDS.match(text))
    cards = _cards_shown(tid, user_id) if said_yes and not approved else []
    turn = context.Turn(
        calendar=calendar or get_calendar(),
        user_id=user_id,
        principal=principal,
        timezone=timezone,
        door=door,
        thread_id=tid,
        # Only the service key's own ``approved`` vouches for a whole turn. A yes
        # in words approves the cards it answered, below, and nothing else: every
        # call the model makes after a yes keeps its tags.
        approved=not propose_only and approved,
        yes_to_a_question=said_yes and not cards and _asked_a_question(tid),
        propose_only=propose_only,
        source=dict(source or {}),
        text=text,
    )
    context.set_turn(turn)
    yield {"type": "session", "thread_id": tid}
    if cards:
        trail().record(
            "turn.start", {"principal": principal, "door": door, "thread": tid, "text": text[:500]}
        )
        try:
            out = await _approve_what_was_shown(cards, turn, reply_language(language, text))
        finally:
            context.set_turn(None)
        _persist_turn(tid, "user", text, [])
        _persist_turn(
            tid,
            "assistant",
            out["reply"],
            [{"approved": out["approved"]}, {"held": out["held"], "created": out["created"]}],
        )
        await _remember_exchange(
            tid,
            prompt.user_turn(text, principal, timezone, door, language, family=family.describe()),
            out["reply"],
        )
        trail().record("turn.end", {"thread": tid, "tools": 0, "held": len(out["held"])})
        yield {
            "type": "done",
            "reply": out["reply"],
            "thread_id": tid,
            "tool_calls": [],
            "held": out["held"],
            "created": out["created"],
            "widgets": [],
            "approved": out["approved"],
        }
        return
    # Which model is answering is about now, not about the conversation, so it
    # is said once and never stored on the turn.
    if not model_menu.ready():
        # No model to ask: said plainly, as an answer, rather than failing the turn.
        context.set_turn(None)
        _persist_turn(tid, "user", text, [])
        _persist_turn(tid, "assistant", NO_MODEL, [])
        yield {
            "type": "done",
            "reply": NO_MODEL,
            "thread_id": tid,
            "tool_calls": [],
            "held": [],
            "created": [],
            "widgets": [],
            "model": "",
        }
        return
    model = model_menu.pick(model, _chosen_model(user_id))
    answering = model or model_menu.default_id()
    #: The model this turn asked for (the router may answer with another).
    asked = answering
    yield {"type": "model", "name": answering}
    events: list[dict[str, Any]] = []
    #: The words of the model call now speaking, as streamed.
    reply_parts: list[str] = []
    #: Words are on the person's screen that a later call's words must take back.
    shown = False
    #: A tool ran (or the turn was asked again) since the last words: the next words
    #: are another call's, and replace what is shown.
    fresh = False
    gate = _HidesToolSyntax()
    last_chunk = ""
    repeats = 0
    final: str | None = None
    created: list[dict[str, Any]] = []
    #: Write tools that went through — not refused with an error, not held.
    written: list[str] = []
    widgets: list[dict[str, Any]] = []
    trail().record(
        "turn.start", {"principal": principal, "door": door, "thread": tid, "text": text[:500]}
    )
    try:
        # Every turn still has to call something before it answers — that is
        # what stops a calendar question being answered from memory. What a
        # greeting calls is `just_talking`, which reads nothing: the model makes
        # that judgement, rather than a list of greetings kept in this file.
        model_kwargs: dict[str, Any] = {"tool_choice": "required"}
        budget = _FirstCallNeedsATool(model_kwargs)
        agent = build_agent(principal, hooks=[budget], model=model, propose_only=propose_only)
        from luach import memory

        message = prompt.user_turn(
            text,
            principal,
            timezone,
            door,
            language,
            family=family.describe(),
            known=await memory.known(user_id, principal),
        )
        # A turn has come back with no tool call and no
        # words at all — the model said nothing whatsoever. Nothing has been
        # shown or done by then, so the turn is asked again rather than handed
        # to a person as a failure.
        for attempt in (1, 2):
            async for ev in agent.run(
                message, thread_id=tid, stream_tokens=True, model_kwargs=model_kwargs
            ):
                if isinstance(ev, ModelChunkEvent):
                    # The model that actually answers, as the router names it. It
                    # is not always the one asked for: the router falls back to
                    # another while the model server restarts, and a person who picked a
                    # model should see when someone else answered.
                    served = getattr(ev, "model", None)
                    if served and served != answering:
                        answering = served
                        yield {"type": "model", "name": served}
                    if ev.content:
                        # A model that has begun looping sends the same fragment over
                        # and over. The router eventually cuts it off, but by then the
                        # member has watched a page of empty code fences arrive. Stop
                        # relaying it long before that.
                        if ev.content == last_chunk:
                            repeats += 1
                            if repeats >= MAX_REPEATED_CHUNKS:
                                raise StuckModel("the model is repeating the same chunk")
                        else:
                            last_chunk, repeats = ev.content, 0
                        # Counted for the loop check above before the gate, so
                        # repetition inside suppressed markup is still caught.
                        visible = gate.feed(ev.content)
                        if visible:
                            if fresh:
                                if shown:
                                    yield {"type": "retract"}
                                    shown = False
                                reply_parts.clear()
                                fresh = False
                            reply_parts.append(visible)
                            shown = True
                            yield {"type": "token", "text": visible}
                    elif ev.reasoning:
                        yield {"type": "thinking", "text": ev.reasoning}
                elif isinstance(ev, ToolStartEvent):
                    # What the gate still holds ends the words before this call.
                    tail = gate.flush()
                    if tail:
                        reply_parts.append(tail)
                        shown = True
                        yield {"type": "token", "text": tail}
                    fresh = True
                    budget.saw_tool(ev.tool_name)
                    if ev.tool_name == SKILLS_TOOL:
                        # Reading up on how to do it is not doing it: it does not
                        # count as the turn having called something. It is still
                        # shown — "following the guide on repeating events" tells
                        # a person why the next step is the one it is.
                        skill = ev.arguments.get("skill_name")
                        trail().record("skill.loaded", {"thread": tid, "skill": skill})
                        if isinstance(skill, str) and skill:
                            yield {"type": "skill", "name": skill}
                        continue
                    events.append({"tool": ev.tool_name, "args": ev.arguments})
                    # `just_talking` is how the model says "this is a conversation";
                    # drawing "checking the calendar…" for it would be a lie.
                    if ev.tool_name != "just_talking":
                        yield {"type": "tool_start", "tool": ev.tool_name, "args": ev.arguments}
                elif isinstance(ev, ToolCompleteEvent):
                    if ev.tool_name in ("just_talking", SKILLS_TOOL):
                        continue  # nothing happened, so nothing is drawn
                    result = _parse_result(ev.result)
                    frame: dict[str, Any] = {
                        "type": "tool_result",
                        "tool": ev.tool_name,
                        "result": result,
                    }
                    if ev.error:
                        frame["error"] = ev.error
                    refused = bool(ev.error) or (
                        isinstance(result, dict)
                        and (
                            bool(result.get("error")) or result.get("status") == "held_for_approval"
                        )
                    )
                    if ev.tool_name in WRITE_TOOLS and not refused:
                        written.append(ev.tool_name)
                    if isinstance(result, dict):
                        if result.get("status") == "held_for_approval":
                            held = next(
                                (h for h in turn.held if h["id"] == result.get("approval_id")), None
                            )
                            yield {
                                "type": "held",
                                **(held or {"id": result.get("approval_id")}),
                                "reason_text": result.get("reason", ""),
                            }
                        if "created" in result:
                            created.append(result["created"])
                    yield frame
                    widget = widget_for(ev.tool_name, result, turn.shown_as)
                    if widget is not None:
                        widgets.append(widget)
                        yield {"type": "widget", **widget}
                elif isinstance(ev, TerminateEvent):
                    final = ev.final_message
            # tulip's own iteration report is not the model speaking, so a turn
            # that produced only that is still a turn that said nothing.
            said = strip_tool_syntax(final) if final else ""
            # "Added: Swimming, every Thu…" came back having only searched: a
            # read had run, so no guard saw it, and nothing was
            # saved. Asked once more, told plainly that nothing was written.
            # A write tool that answered with an error wrote nothing: add_task refusing
            # "at 4:30pm" as a task and the model answering "Added: Dentist…" anyway
            # is the same untruth as never calling it.
            wrote = bool(written)
            answer = said or "".join(reply_parts)
            if (
                attempt == 1
                and claims_a_write(answer)
                and not wrote
                and not created
                and not turn.held
            ):
                trail().record("turn.claimed_unwritten", {"thread": tid, "said": answer[:200]})
                logger.warning("the model claimed a write it did not make; asking again")
                message = NOTHING_WRITTEN
                reply_parts.clear()
                # The claim is still on the screen; the second answer takes it back.
                fresh = True
                gate = _HidesToolSyntax()
                final = None
                model_kwargs = {"tool_choice": "required"}
                budget = _FirstCallNeedsATool(model_kwargs)
                agent = build_agent(
                    principal, hooks=[budget], model=model, propose_only=propose_only
                )
                continue
            if events or reply_parts or (said and not is_machine_summary(said)):
                break
            if attempt == 1:
                trail().record("turn.empty_retry", {"thread": tid})
                logger.warning("the model said nothing at all; asking once more")
                model_kwargs = {"tool_choice": "required"}
                budget = _FirstCallNeedsATool(model_kwargs)
                agent = build_agent(
                    principal, hooks=[budget], model=model, propose_only=propose_only
                )
    except (asyncio.CancelledError, GeneratorExit):
        # The person pressed Stop, or closed the tab. Whatever was already done
        # stays done — an event written a moment before is on the calendar — so
        # the thread keeps the turn and says so, rather than losing it.
        reply_parts.append(gate.flush())
        said = "".join(reply_parts).strip()
        _persist_turn(tid, "user", text, [])
        _persist_turn(
            tid,
            "assistant",
            f"{said}\n\n(stopped)" if said else "(stopped)",
            events + [{"widget": w} for w in widgets] + [{"held": turn.held, "created": created}],
        )
        trail().record("turn.stopped", {"thread": tid, "tools": len(events)})
        raise
    except Exception as exc:  # the stream must end with a frame, not a socket error
        logger.exception("turn failed")
        trail().record("turn.error", {"thread": tid, "error": str(exc)[:300]})
        moved = False
        try:
            moved = model_health.failed(asked, exc, user_id=user_id) and bool(model)
        except Exception:
            logger.exception("could not record the model's failure")
        yield {"type": "error", "message": explain_failure(exc, picked=model, moved=moved)}
        return
    finally:
        context.set_turn(None)
    reply_parts.append(gate.flush())
    streamed = "".join(reply_parts).strip()
    # `final` is normally the model's own last word, and has not been through the
    # gate. When it is tulip's fallback summary instead it is not an answer at
    # all, so it is set aside and what the model actually said — or, failing
    # that, one of the sentences below — takes its place.
    final_text = strip_tool_syntax(final) if final else ""
    reply = "" if is_machine_summary(final_text) else final_text
    reply = reply or streamed
    # Three ways a turn can tell a person something that is not true, all
    # settled here on facts rather than on how the answer is worded.
    #
    # Running out of room is a different failure from answering out of thin
    # air, and it can happen with tools already called: one turn read
    # the web three times and then said "I cannot create calendar events as the
    # system has reached its iteration limit", which is the model's own
    # plumbing showing through.
    if budget.exhausted and not created and not turn.held:
        trail().record("turn.out_of_steps", {"thread": tid, "calls": budget.calls})
        logger.warning("turn ran out of steps after %d calls", budget.calls)
        reply = (
            "That took more steps than I have in one go, so I stopped without doing "
            "anything. Ask me for one piece at a time — add the event first, then the "
            "details."
        )
    # Answering without calling anything: it cannot have read or written a
    # calendar, so whatever it says about one is invented. "add tennis for
    # tomorrow at 4" came back "Added: Tennis, Sat 19 Sep 16:00" with no tool
    # call at all. Small talk is a tool (``just_talking``), so a turn with none
    # of them is always a failure.
    elif not events and not turn.held:
        trail().record("turn.no_tool", {"thread": tid, "said": reply[:200]})
        logger.warning("turn ended with no tool call: %r", reply[:120])
        reply = (
            "I did not actually do anything just then — nothing was read or written. Ask me again."
        )
    # And the gate holding the write while the answer says it is done.
    # Or it went quiet. tulip ends a run that keeps making the same call, which
    # is right, but it ends it with no final message: the person was left
    # looking at an empty bubble while the log said the model had looped.
    elif claims_a_write(reply) and not created and not turn.held and not written:
        # Asked again and it still only said so: what reaches the person is the truth.
        trail().record("turn.claimed_unwritten_twice", {"thread": tid, "said": reply[:200]})
        reply = "I did not save that — nothing was written. Ask me again and I will add it."
    elif turn.held and not created:
        reply = "Waiting for your approval — nothing is on the calendar yet: " + "; ".join(
            h["summary"] for h in turn.held
        )
    # It did the thing and then said nothing. A
    # turn that had written the event answered "I went round in circles and did
    # not get to an answer" — the worst way to report a success, because the
    # person believes nothing happened and adds it again. What was written is
    # what is said.
    elif not reply and created:
        trail().record("turn.wrote_and_said_nothing", {"thread": tid, "created": len(created)})
        logger.warning("turn wrote %d events and said nothing; reporting them", len(created))
        reply = "Added: " + "; ".join(_describe_created(c) for c in created) + "."
    elif not reply:
        trail().record("turn.no_answer", {"thread": tid, "tools": len(events)})
        logger.warning("turn ended with %d tools and nothing to say", len(events))
        reply = (
            "I went round in circles on that one and did not get to an answer. "
            "Try asking it a different way."
        )

    # A member moved off a model that stopped answering hears it here, once: no
    # silent switch.
    notice = model_menu.note_for(user_id)
    if notice:
        reply = f"{notice}\n\n{reply}"
        model_menu.clear_note(user_id)
    try:
        model_health.answered(asked)
    except Exception:
        logger.exception("could not record the model's answer")
    _persist_turn(tid, "user", text, [])
    _persist_turn(
        tid,
        "assistant",
        reply,
        events + [{"widget": w} for w in widgets] + [{"held": turn.held, "created": created}],
    )
    trail().record("turn.end", {"thread": tid, "tools": len(events), "held": len(turn.held)})
    yield {
        "type": "done",
        "reply": reply,
        "thread_id": tid,
        "tool_calls": events,
        "held": turn.held,
        "created": created,
        "widgets": widgets,
        "model": answering,
        "notice": notice,
    }


async def run_turn(text: str, **kwargs: Any) -> TurnResult:
    """The whole turn as one result (the service key, the email door, tests)."""
    result = TurnResult(reply="", thread_id=kwargs.get("thread_id") or "")
    async for frame in stream_turn(text, **kwargs):
        if frame["type"] == "session":
            result.thread_id = frame["thread_id"]
        elif frame["type"] == "done":
            result.reply = frame["reply"]
            result.tool_calls = frame["tool_calls"]
            result.held = frame["held"]
            result.created = frame["created"]
            result.widgets = frame.get("widgets", [])
        elif frame["type"] == "error":
            result.error = frame["message"]
            result.reply = result.reply or frame["message"]
    return result

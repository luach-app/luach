"""What of a thread's earlier turns the model is sent, on every model call.

tulip keeps the whole thread in its checkpoint and, left to itself, decides per
model how much of it to send: for a model it knows the window of (a self-hosted
``qwen3.6-35b``) everything, for as long as the thread lives; for any other name
— the menu's cloud models, the same qwen under OpenRouter's id — the last 32
messages, cut at a fixed count. A luach turn is three to six messages (the
question, a tool call, its result, perhaps a second call, the answer), so the
second model forgot the start of a conversation by its sixth turn, and the cut
fell inside a turn: the window opened on a tool call whose question was gone.
Which of the two a household got depended on the name of the model it picked.

So luach decides, the same way for every model:

* **Whole turns.** The last ``LUACH_HISTORY_TURNS`` (20) questions with everything
  that followed each, never a cut inside one. The window slides :data:`STEP` turns at
  a time, so between slides every request starts with the same bytes and the
  model server's prompt cache keeps serving them.
* **Only the newest question carries the household's state.** Each question is
  stored with its ``[context]`` line — now, the next seven days, the family —
  and the member's remembered facts. On an older question the facts are dropped
  and the line is cut to when it was asked. A fact forgotten or changed in turn
  five was otherwise still being replayed, as it had been, from turns one to
  four; and a thread carried the same block once per message.

The checkpoint is never changed: this shapes the request, not the record.
"""

from __future__ import annotations

import re
from typing import Any

from tulip.core.messages import Message, Role
from tulip.memory.conversation import ConversationManager

from luach import config

#: The fence ``tulip.memory.scrubber.build_memory_context_block`` puts round a
#: member's facts in the user turn (``memory.known``).
_FACTS = re.compile(r"\n<memory-context>.*?</memory-context>", re.S)
#: The context line, up to the end of its timestamp and zone.
_CONTEXT = re.compile(r"^\[context\] now=([^|\n]*?)\s*(\|[^\n]*)?$", re.M)


#: Once the window is full it drops this many turns at once, so the start of
#: what is sent stays the same between slides.
STEP = 5


def earlier(content: str) -> str:
    """An earlier question as it is replayed: when it was asked, and what was said."""
    content = _FACTS.sub("", content, count=1)
    return _CONTEXT.sub(lambda m: f"[context] asked {m.group(1).strip()}", content, count=1)


class TurnWindow(ConversationManager):
    """The leading system messages, then the newest ``keep`` turns, whole."""

    def __init__(self, keep: int | None = None, slide: int = STEP) -> None:
        self.keep = keep or config.history_turns()
        self.slide = max(1, min(slide, self.keep))

    def apply(self, messages: list[Message]) -> list[Message]:
        head: list[Message] = []
        rest = list(messages)
        while rest and rest[0].role == Role.SYSTEM:
            head.append(rest.pop(0))
        asked = [i for i, m in enumerate(rest) if m.role == Role.USER]
        if len(asked) > self.keep:
            # Whole steps, so the first turn sent stays put until the next slide.
            excess = len(asked) - self.keep
            drop = -(-excess // self.slide) * self.slide
            rest = rest[asked[drop] :]
            asked = [i - asked[drop] for i in asked[drop:]]
        # The newest question a person asked: a note luach itself sent in the same
        # turn ("[luach] … nothing was written") has no context line of its own.
        said = [i for i in asked if (rest[i].content or "").startswith("[context]")]
        newest = (said or asked or [-1])[-1]
        shaped = [
            m.model_copy(update={"content": earlier(m.content)})
            if m.role == Role.USER and i != newest and isinstance(m.content, str)
            else m
            for i, m in enumerate(rest)
        ]
        return head + shaped

    def __repr__(self) -> str:
        return f"TurnWindow(keep={self.keep}, slide={self.slide})"


def window() -> Any:
    return TurnWindow()

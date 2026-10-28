"""Who is calling — set once per request by the middleware, read anywhere."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class Caller:
    user_id: int
    principal: str  # username, or the service key's name
    via_key: bool = False
    door: str = "web"
    #: The agent platform's key: reads and agent turns only, and it never approves.
    restricted: bool = False


_caller: ContextVar[Caller | None] = ContextVar("luach_caller", default=None)


def set_caller(caller: Caller | None) -> None:
    _caller.set(caller)


def caller() -> Caller | None:
    return _caller.get()

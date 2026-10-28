"""The trusted-service paths, presented as ``x-luach-key``.

The service key (``LUACH_API_KEY``), held by a trusted service such as a chat bot, acts
as the owner, short of changing who can get in (``SERVICE_REFUSED``). A second key for an agent platform (``LUACH_TULIP_KEY``) acts as the owner
too, but only through a narrow door: the read routes in ``TULIP_ALLOWED`` and a turn
with the agent, whose gate decides every write. It can never approve.
"""

from __future__ import annotations

import re
import secrets

from luach import config

HEADER = "x-luach-key"

#: What the agent platform's key may call: (method, path pattern). Everything else is refused
#: at the wall, so a write route added later is closed to it by default. The agent
#: turn is the one write-capable door, and luach's own gate stands behind it.
TULIP_ALLOWED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (method, re.compile(pattern))
    for method, pattern in (
        ("GET", r"/api/health"),
        ("GET", r"/api/auth/me"),
        ("GET", r"/api/calendar/events"),
        ("GET", r"/api/calendar/events/[^/]+"),
        ("GET", r"/api/calendar/identity"),
        ("GET", r"/api/family"),
        ("GET", r"/api/household"),
        ("GET", r"/api/household/calendars"),
        ("GET", r"/api/tasks"),
        ("GET", r"/api/tasks/all"),
        ("GET", r"/api/control/pending"),
        ("GET", r"/api/control/audit"),
        ("GET", r"/api/threads"),
        ("GET", r"/api/threads/[^/]+"),
        ("GET", r"/api/memory"),
        ("GET", r"/api/booking/upcoming"),
        ("POST", r"/api/agent"),
        ("POST", r"/api/agent/stream"),
    )
)


#: What the service key may not do, although it otherwise acts as the owner: change who
#: can get in (members, invites, the owner's sign-in, passkeys and addresses), connect or
#: drop a mailbox, point the owner's notifications somewhere, or pair a screen. A leaked
#: key then reaches the calendar and its gate, not the household's keys. The owner's
#: trusted service (a chat bot through scripts/luach-cli.sh) calls none of these.
SERVICE_REFUSED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (method, re.compile(pattern))
    for method, pattern in (
        ("POST", r"/api/members/.*"),
        ("DELETE", r"/api/members/.*"),
        ("PATCH", r"/api/auth/me"),
        ("POST", r"/api/auth/password"),
        ("POST", r"/api/auth/emails(/.*)?"),
        ("DELETE", r"/api/auth/emails/.*"),
        ("POST", r"/api/auth/passkeys/register/.*"),
        ("DELETE", r"/api/auth/passkeys/.*"),
        ("GET", r"/api/mail/.+"),
        ("POST", r"/api/mail(/.*)?"),
        ("PATCH", r"/api/mail(/.*)?"),
        ("DELETE", r"/api/mail(/.*)?"),
        ("POST", r"/api/push/.*"),
        ("POST", r"/api/boards"),
        ("PATCH", r"/api/boards/.*"),
        ("DELETE", r"/api/boards/.*"),
        # Which models the family's questions are sent to is the owner's, in person
        # (routes/models.py refuses a key too).
        ("GET", r"/api/models/(manage|catalogue)(/.*)?"),
        ("POST", r"/api/models/manage(/.*)?"),
        ("PATCH", r"/api/models/manage(/.*)?"),
        ("PUT", r"/api/models/manage(/.*)?"),
        ("DELETE", r"/api/models/manage(/.*)?"),
    )
)


def _same(presented: str | None, expected: str) -> bool:
    # compare_digest refuses a str with non-ASCII in it (TypeError, so a 500); a key
    # is ASCII (config.weak_key), so anything else is simply not it.
    if not expected or not presented or not presented.isascii():
        return False
    return secrets.compare_digest(presented.encode(), expected.encode())


def matches(presented: str | None) -> bool:
    return _same(presented, config.api_key())


def matches_tulip(presented: str | None) -> bool:
    return _same(presented, config.tulip_key())


def service_may(method: str, path: str) -> bool:
    """Whether the service key may make this request (see ``SERVICE_REFUSED``)."""
    return not any(m == method and p.fullmatch(path) for m, p in SERVICE_REFUSED)


def tulip_may(method: str, path: str) -> bool:
    """Whether the agent platform's key may make this request."""
    method = "GET" if method == "HEAD" else method
    return any(m == method and p.fullmatch(path) for m, p in TULIP_ALLOWED)

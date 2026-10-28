"""The setup code: what makes the first account, the owner, someone's who can read the log.

A fresh luach has no accounts, and "Set up the household" makes the first one the owner. Open
to anyone, that screen belonged to whoever reached the server first. So, as Home Assistant's
onboarding does, the server makes a one-time code at startup while it has no accounts, prints
it to its log (``docker compose logs luach``) and writes it to ``<state dir>/setup-code``, and
the first account needs it. ``LUACH_SETUP_CODE`` pins the code instead, for automation.

Once the owner exists the code is spent: the file is removed and registration is closed for
good. A server that already has accounts never makes one, and is never asked for one.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
from pathlib import Path

from luach import config

logger = logging.getLogger(__name__)

FILENAME = "setup-code"
#: No 0/O, 1/I/L: the code is read off a terminal and typed into a form.
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
GROUPS, GROUP_LEN = 3, 4  # ~59 bits

_code: str | None = None


def pinned() -> str:
    return config.env("LUACH_SETUP_CODE")


def path() -> Path:
    return config.state_dir() / FILENAME


def normalise(code: str) -> str:
    """As typed: case, spaces and dashes do not matter."""
    return "".join(ch for ch in code.upper() if ch.isalnum())


def generate() -> str:
    groups = ("".join(secrets.choice(ALPHABET) for _ in range(GROUP_LEN)) for _ in range(GROUPS))
    return "-".join(groups)


def _read_file() -> str:
    try:
        return path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_file(code: str) -> bool:
    target = path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(code + "\n")
        return True
    except OSError:
        logger.warning("setup: could not write %s; the code is in this log only", target)
        return False


def ensure() -> str:
    """The code the first account needs, made now if there is none, and announced.

    A code already in the state directory is kept, so a restart before anyone set the
    household up does not make the one in an earlier log line stop working."""
    global _code
    code = pinned()
    if code:
        _code = code
        if len(normalise(code)) < 12:
            logger.warning("setup: LUACH_SETUP_CODE is short; use 12 or more random characters")
        _announce(code, where="LUACH_SETUP_CODE")
        return code
    code = _code or _read_file() or generate()
    _code = code
    written = _read_file() == code or _write_file(code)
    _announce(code, where=str(path()) if written else "")
    return code


def current() -> str:
    """The code a registration is checked against, "" when none has been made."""
    return pinned() or _code or _read_file()


def matches(given: str) -> bool:
    expected = current()
    if not expected or not given:
        return False
    return hmac.compare_digest(normalise(given).encode(), normalise(expected).encode())


def spent() -> None:
    """The owner exists: the code is no use to anyone, and nothing should keep it."""
    global _code
    _code = None
    try:
        path().unlink(missing_ok=True)
    except OSError:
        logger.warning("setup: could not remove %s", path())


def reset() -> None:
    """Forget the code held in memory (tests)."""
    global _code
    _code = None


def _announce(code: str, *, where: str) -> None:
    """Printed big, because it is the one line of the log a new household has to find."""
    rule = "=" * 68
    pinned_here = where == "LUACH_SETUP_CODE"
    lines = [
        "",
        rule,
        "  luach has no accounts yet. To set up the household, open luach in a",
        '  browser and enter this setup code on the "Set up the household" screen:',
        "",
        "      " + ("(the value of LUACH_SETUP_CODE)" if pinned_here else code),
        "",
    ]
    if where and not pinned_here:
        lines.append(f"  It is also in {where}.")
    lines += [
        "  The account made with it becomes the owner, and the code stops working.",
        rule,
    ]
    logger.warning("\n".join(lines))

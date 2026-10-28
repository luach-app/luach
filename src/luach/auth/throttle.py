"""In-process login throttle: a few tries, then a cool-off, per (name, ip); and a higher cap
per account, whatever the address.

The per-address cap stops one client guessing. Alone it let a client with many addresses
guess on, a few tries each, so sign-in also counts failures per account across addresses
(``LUACH_LOGIN_ACCOUNT_MAX_ATTEMPTS``, well above the per-address cap so that a member who
mistypes is never the one who trips it). Passkeys and single sign-on are not counted here,
so a member whose password sign-in is held still gets in those ways.

Every key is in memory, so the map is pruned of keys whose attempts have all expired:
otherwise each address that ever read a booking page would stay in it for good.
"""

from __future__ import annotations

import os
import time

MAX_ATTEMPTS = int(os.getenv("LUACH_LOGIN_MAX_ATTEMPTS", "8"))
LOCKOUT_SECS = int(os.getenv("LUACH_LOGIN_LOCKOUT_SECS", "300"))
ACCOUNT_MAX_ATTEMPTS = int(os.getenv("LUACH_LOGIN_ACCOUNT_MAX_ATTEMPTS", "30"))
#: How often the map is swept of expired keys, at most.
PRUNE_EVERY_SECS = 60

_attempts: dict[str, list[float]] = {}
_last_prune = 0.0


def _key(name: str, ip: str) -> str:
    return f"{name.strip().lower()}@{ip}"


def _account(name: str) -> str:
    # No "@": a (name, ip) key always has one, so none looks like this.
    return f"account:{name.strip().lower()}"


def _prune(now: float) -> None:
    global _last_prune
    if now - _last_prune < PRUNE_EVERY_SECS:
        return
    _last_prune = now
    for key in [k for k, hits in _attempts.items() if not hits or now - hits[-1] >= LOCKOUT_SECS]:
        del _attempts[key]


def _wait(key: str, cap: int) -> int:
    now = time.monotonic()
    _prune(now)
    hits = [t for t in _attempts.get(key, []) if now - t < LOCKOUT_SECS]
    if hits:
        _attempts[key] = hits
    else:
        _attempts.pop(key, None)
    if len(hits) >= cap:
        return max(1, int(LOCKOUT_SECS - (now - hits[0])))
    return 0


def locked(name: str, ip: str, max_attempts: int | None = None) -> int:
    """Seconds left on the lockout, 0 if none.

    ``max_attempts`` raises the cap for things that are not sign-in attempts:
    reading a public page a few times is ordinary, mistyping a password is not.
    """
    return _wait(_key(name, ip), max_attempts or MAX_ATTEMPTS)


def failed(name: str, ip: str) -> None:
    now = time.monotonic()
    _prune(now)
    _attempts.setdefault(_key(name, ip), []).append(now)


def clear(name: str, ip: str) -> None:
    _attempts.pop(_key(name, ip), None)


def account_locked(name: str) -> int:
    """Seconds left on an account's lockout across every address, 0 if none."""
    return _wait(_account(name), ACCOUNT_MAX_ATTEMPTS)


def account_failed(name: str) -> None:
    """A wrong password for this account, from anywhere. A success does not clear it: the
    member signing in would otherwise reset the count of someone guessing at them."""
    now = time.monotonic()
    _prune(now)
    _attempts.setdefault(_account(name), []).append(now)


def size() -> int:
    """How many keys are held (tests, and anyone wondering about memory)."""
    return len(_attempts)


def reset_all() -> None:
    global _last_prune
    _attempts.clear()
    _last_prune = 0.0

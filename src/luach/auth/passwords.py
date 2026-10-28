from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def acceptable(password: str) -> str | None:
    """A reason the password is refused, or None."""
    # 8, the same floor as common identity providers, so one household password can work
    # everywhere. luach is reachable from the internet, so the floor is what stands
    # between a guessed password and a member's calendar: the login throttle and the single
    # sign-on button (which carries the passkey) are the real defences.
    if len(password) < 8:
        return "password must be at least 8 characters"
    if len(password) > 200:
        return "password is too long"
    return None

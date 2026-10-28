"""The house board: a screen on the wall that shows the family's day.

It is not a member. It never signs in, holds no session and cannot reach the
agent, the settings or anyone's threads. It holds a board token, which reads
today — who has what on, whose task is whose — and ticks tasks, because a child
standing at the fridge is exactly who should tick one. Nothing else.

It gets that token by pairing. The screen asks for a short code and shows it;
the owner types the code into luach on their phone; the screen, polling with a
secret only it saw, picks up its token once and keeps it. A code lives ten
minutes. The owner can see every board and take any of them away.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from luach import db
from luach.auth.tokens import new_token, token_hash

HEADER = "x-luach-board"
PAIR_HEADER = "x-luach-pair"
PAIR_TTL = timedelta(minutes=10)
#: Codes are read off a wall and typed on a phone: no 0/O, 1/I/L.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 6
MAX_OPEN_PAIRINGS = 20
MAX_BOARDS = 10
#: What a board can speak; "auto" follows the screen's own browser.
LANGUAGES = ("auto", "en", "es", "he")


def _code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(CODE_LEN))


def normalise(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _purge(s: Any) -> None:
    now = db.utcnow()
    for row in s.execute(
        select(db.BoardPairing).where(db.BoardPairing.expires_at <= now)
    ).scalars():
        s.delete(row)
    # Flushed, or a lookup in this same session would still find what was purged.
    s.flush()


def start_pairing() -> dict[str, str]:
    """A screen asks to be a board: here is a code to show, and a secret to keep."""
    secret = new_token()
    with db.session() as s:
        _purge(s)
        if len(s.execute(select(db.BoardPairing.code)).all()) >= MAX_OPEN_PAIRINGS:
            raise ValueError("too many screens are waiting to pair; try again in a few minutes")
        code = _code()
        while s.get(db.BoardPairing, code) is not None:
            code = _code()
        expires = db.utcnow() + PAIR_TTL
        s.add(db.BoardPairing(code=code, secret_hash=token_hash(secret), expires_at=expires))
    return {"code": code, "secret": secret, "expires_at": db.iso(expires)}


def claim(code: str, name: str) -> dict[str, Any]:
    """The owner types the code: the screen becomes a board."""
    name = name.strip()[:60] or "House board"
    with db.session() as s:
        _purge(s)
        row = s.get(db.BoardPairing, normalise(code))
        if row is None or row.token:
            raise KeyError("no screen is waiting with that code")
        if len(s.execute(select(db.Board.id)).all()) >= MAX_BOARDS:
            raise ValueError(f"a household has at most {MAX_BOARDS} boards; remove one first")
        token = new_token()
        board = db.Board(name=name, token_hash=token_hash(token))
        s.add(board)
        s.flush()
        # Kept only until the screen collects it, and never longer than the code lives.
        row.token = token
        return {"id": board.id, "name": board.name}


def collect(code: str, secret: str) -> str | None:
    """The screen asks whether it has been claimed. Its token, once; else None."""
    with db.session() as s:
        _purge(s)
        row = s.get(db.BoardPairing, normalise(code))
        if (
            row is None
            or not secret
            or not secrets.compare_digest(row.secret_hash, token_hash(secret))
        ):
            raise KeyError("that pairing is not waiting any more")
        if not row.token:
            return None
        token = row.token
        s.delete(row)
        return token


def authenticate(token: str | None) -> db.Board | None:
    if not token:
        return None
    with db.session() as s:
        board = s.execute(select(db.Board).where(db.Board.token_hash == token_hash(token))).scalar()
        if board is None:
            return None
        now = db.utcnow()
        # Written at most once a minute: a board polls, and a write per poll is noise.
        if board.last_seen is None or now - board.last_seen > timedelta(minutes=1):
            board.last_seen = now
        return board


def boards() -> list[dict[str, Any]]:
    with db.session() as s:
        return [
            {
                "id": b.id,
                "name": b.name,
                "created_at": db.iso(b.created_at),
                "last_seen": db.iso(b.last_seen),
                "can_edit": bool(b.can_edit),
                "language": b.language or "auto",
            }
            for b in s.execute(select(db.Board).order_by(db.Board.id)).scalars()
        ]


def remove(board_id: int) -> None:
    with db.session() as s:
        board = s.get(db.Board, board_id)
        if board is None:
            raise KeyError(board_id)
        s.delete(board)


def update(
    board_id: int,
    *,
    name: str | None = None,
    can_edit: bool | None = None,
    language: str | None = None,
) -> None:
    if language is not None and language not in LANGUAGES:
        raise ValueError(f"language is one of {', '.join(LANGUAGES)}")
    with db.session() as s:
        board = s.get(db.Board, board_id)
        if board is None:
            raise KeyError(board_id)
        if name is not None:
            board.name = name
        if can_edit is not None:
            board.can_edit = can_edit
        if language is not None:
            board.language = language

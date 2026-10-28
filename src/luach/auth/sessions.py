"""Opaque session tokens in an httponly cookie; only the SHA-256 is stored."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, select

from luach import db
from luach.auth.tokens import new_token, token_hash

COOKIE_NAME = "luach_session"
SESSION_TTL_DAYS = 30
TOUCH_INTERVAL_SECONDS = 60


def mint_session(user_id: int) -> str:
    token = new_token()
    now = db.utcnow()
    with db.session() as s:
        s.add(
            db.SessionRow(
                token_hash=token_hash(token),
                user_id=user_id,
                created_at=now,
                expires_at=now + timedelta(days=SESSION_TTL_DAYS),
                last_seen=now,
            )
        )
    return token


def authenticate(token: str | None) -> int | None:
    """The user id behind a cookie value, or None. Touches last_seen sparingly."""
    if not token:
        return None
    now = db.utcnow()
    with db.session() as s:
        row = s.get(db.SessionRow, token_hash(token))
        if row is None:
            return None
        if row.expires_at <= now:
            s.delete(row)
            return None
        if (now - row.last_seen).total_seconds() > TOUCH_INTERVAL_SECONDS:
            row.last_seen = now
            user = s.get(db.User, row.user_id)
            if user is not None:
                user.last_seen = now
        return int(row.user_id)


def logout(token: str | None) -> None:
    if not token:
        return
    with db.session() as s:
        s.execute(delete(db.SessionRow).where(db.SessionRow.token_hash == token_hash(token)))


def revoke_all(user_id: int) -> None:
    with db.session() as s:
        s.execute(delete(db.SessionRow).where(db.SessionRow.user_id == user_id))


def revoke_others(user_id: int, keep: str | None) -> int:
    """Sign a member out everywhere but the session ``keep`` (their current one, after
    they changed their password there). Returns how many were ended."""
    query = delete(db.SessionRow).where(db.SessionRow.user_id == user_id)
    if keep:
        query = query.where(db.SessionRow.token_hash != token_hash(keep))
    with db.session() as s:
        result = s.execute(query)
        return int(getattr(result, "rowcount", 0) or 0)


def purge_expired() -> int:
    with db.session() as s:
        result = s.execute(delete(db.SessionRow).where(db.SessionRow.expires_at <= db.utcnow()))
        return int(getattr(result, "rowcount", 0) or 0)


def sessions_for(user_id: int) -> int:
    with db.session() as s:
        rows = s.execute(select(db.SessionRow).where(db.SessionRow.user_id == user_id)).all()
        return len(rows)

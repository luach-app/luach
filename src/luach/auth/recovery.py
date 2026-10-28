"""Password recovery. Always answers the same, whoever asks."""

from __future__ import annotations

from datetime import timedelta

from luach import db
from luach.auth import sessions, users
from luach.auth.tokens import new_token, token_hash

RESET_TTL_MINUTES = 30


def start(email: str) -> tuple[users.Member, str] | None:
    """A (member, token) pair when the address is known, else None."""
    member = users.member_by_email(email)
    if member is None:
        return None
    token = new_token()
    with db.session() as s:
        s.add(
            db.Reset(
                token_hash=token_hash(token),
                user_id=member.id,
                expires_at=db.utcnow() + timedelta(minutes=RESET_TTL_MINUTES),
            )
        )
    return member, token


def finish(token: str, password: str) -> str:
    """Set the password, burn the token, sign every other device out."""
    with db.session() as s:
        row = s.get(db.Reset, token_hash(token))
        if row is None or row.consumed_at is not None or row.expires_at <= db.utcnow():
            raise ValueError("this reset link is no longer valid")
        user_id = row.user_id
        row.consumed_at = db.utcnow()
    users.set_password(user_id, password)
    sessions.revoke_all(user_id)
    return sessions.mint_session(user_id)

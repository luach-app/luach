"""Offline recovery: set a member's password from the box, no mail needed.

    docker compose exec luach python -m luach.passwd robin

Prompts for the new password twice, signs every device of that member out.
"""

from __future__ import annotations

import getpass
import sys

from luach import db
from luach.auth import sessions, users


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    db.init_db()
    with db.session() as s:
        from sqlalchemy import select

        user = s.execute(
            select(db.User).where(db.User.username == argv[0].lower())
        ).scalar_one_or_none()
    if user is None:
        print(f"no member named {argv[0]!r}", file=sys.stderr)
        return 1
    first = getpass.getpass("new password: ")
    second = getpass.getpass("again: ")
    if first != second:
        print("they differ", file=sys.stderr)
        return 1
    try:
        users.set_password(user.id, first)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    sessions.revoke_all(user.id)
    print(f"password set for {user.username}; every session signed out")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

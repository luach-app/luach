"""Accounts. The first one is the owner and may invite the rest."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text

from luach import db
from luach.auth.passwords import acceptable, hash_password, verify_password

USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,31}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_NOTIFY = 10
MAX_ALIASES = 10
#: How long a confirmation link stays good.
VERIFY_TTL_HOURS = 48


@dataclass(frozen=True)
class Member:
    id: int
    username: str
    email: str
    display_name: str
    timezone: str
    language: str
    is_owner: bool
    #: The model chosen in Settings; "" is the household's own.
    model: str
    last_seen: str | None
    emails: tuple[str, ...] = ()
    notify_emails: tuple[str, ...] = ()
    #: Added but not yet confirmed, so they receive nothing.
    notify_pending: tuple[str, ...] = ()

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["emails"] = list(self.emails)
        d["notify_emails"] = list(self.notify_emails)
        d["notify_pending"] = list(self.notify_pending)
        return d


def _emails_of(user: db.User) -> tuple[str, ...]:
    """The addresses that count as this member's: the primary, then the extras
    they have confirmed. An unconfirmed address is not yet theirs."""
    with db.session() as s:
        extra = (
            s.execute(
                select(db.UserEmail.email)
                .where(db.UserEmail.user_id == user.id, db.UserEmail.verified_at.is_not(None))
                .order_by(db.UserEmail.added_at)
            )
            .scalars()
            .all()
        )
    return (user.email, *[e for e in extra if e != user.email])


def _member(user: db.User, owner: int | None) -> Member:
    return Member(
        id=user.id,
        username=user.username,
        email=user.email,
        display_name=user.display_name or user.username,
        timezone=user.timezone,
        language=user.language,
        is_owner=(user.id == owner),
        model=user.model or "",
        last_seen=db.iso(user.last_seen),
        emails=_emails_of(user),
        notify_emails=tuple(notify_emails(user.id)),
        notify_pending=tuple(notify_emails(user.id, pending=True)),
    )


def notify_emails(user_id: int | None, *, pending: bool = False) -> list[str]:
    """Where else this member wants to hear about the events they create.

    Only confirmed addresses are invited to anything: an unconfirmed one would
    mean a stranger receiving calendar invitations they never asked for.
    """
    if user_id is None:
        return []
    verified = (
        db.NotifyEmail.verified_at.is_(None) if pending else db.NotifyEmail.verified_at.is_not(None)
    )
    with db.session() as s:
        return list(
            s.execute(
                select(db.NotifyEmail.email)
                .where(db.NotifyEmail.user_id == user_id, verified)
                .order_by(db.NotifyEmail.position)
            )
            .scalars()
            .all()
        )


def set_notify_emails(user_id: int, emails: list[str]) -> Member:
    """Replace the list; order is kept, duplicates dropped. An address that is
    new to the member gets a confirmation link and invites nobody until then."""
    clean: list[str] = []
    for raw in emails:
        email = str(raw).strip().lower()
        if not EMAIL.match(email):
            raise ValueError(f"{raw!r} is not an email address")
        if email not in clean:
            clean.append(email)
    if len(clean) > MAX_NOTIFY:
        raise ValueError(f"at most {MAX_NOTIFY} addresses to notify")
    fresh: list[str] = []
    with db.session() as s:
        if s.get(db.User, user_id) is None:
            raise ValueError("no such member")
        was = {
            r.email: r.verified_at
            for r in s.execute(
                select(db.NotifyEmail).where(db.NotifyEmail.user_id == user_id)
            ).scalars()
        }
        for row in s.execute(
            select(db.NotifyEmail).where(db.NotifyEmail.user_id == user_id)
        ).scalars():
            s.delete(row)
        s.flush()
        for i, e in enumerate(clean):
            # An address this member already confirmed stays confirmed when the
            # list is reordered; a new one starts unconfirmed.
            s.add(db.NotifyEmail(user_id=user_id, email=e, position=i, verified_at=was.get(e)))
            if e not in was:
                fresh.append(e)
    for email in fresh:
        start_verification(user_id, email, "notify")
    found = member(user_id)
    assert found is not None
    return found


# --- proving an address is yours -------------------------------------------


def start_verification(user_id: int, email: str, kind: str) -> str:
    """Mint a confirmation link for ``email`` and mail it there. Returns the token
    so a caller (or a test) can follow the link without reading the mail."""
    from luach import mailer
    from luach.auth.tokens import new_token, token_hash

    token = new_token()
    now = db.utcnow()
    with db.session() as s:
        s.add(
            db.EmailVerification(
                token_hash=token_hash(token),
                user_id=user_id,
                email=email,
                kind=kind,
                created_at=now,
                expires_at=now + timedelta(hours=VERIFY_TTL_HOURS),
            )
        )
    who = member(user_id)
    mailer.send_verification(
        email,
        (who.display_name or who.username) if who else "",
        token,
        kind,
    )
    return token


def verify_address(token: str) -> dict:
    """Follow a confirmation link. Idempotent only in the sense that a consumed
    or expired token is refused; the address itself is marked once."""
    from luach.auth.tokens import token_hash

    with db.session() as s:
        row = s.get(db.EmailVerification, token_hash(token))
        if row is None or row.consumed_at is not None or row.expires_at <= db.utcnow():
            raise ValueError("this confirmation link is no longer valid")
        now = db.utcnow()
        row.consumed_at = now
        email, kind, user_id = row.email, row.kind, row.user_id
        if kind == "alias":
            alias = s.get(db.UserEmail, email)
            if alias is None or alias.user_id != user_id:
                raise ValueError("that address is no longer on the account")
            alias.verified_at = now
        else:
            note = s.get(db.NotifyEmail, (user_id, email))
            if note is None:
                raise ValueError("that address is no longer on the account")
            note.verified_at = now
    return {"email": email, "kind": kind}


def resend_verification(user_id: int, email: str) -> dict:
    """Another link for an address that is still waiting."""
    email = email.strip().lower()
    with db.session() as s:
        alias = s.get(db.UserEmail, email)
        if alias is not None and alias.user_id == user_id:
            kind = "alias" if alias.verified_at is None else ""
        else:
            note = s.get(db.NotifyEmail, (user_id, email))
            kind = "notify" if note is not None and note.verified_at is None else ""
    if not kind:
        raise ValueError("that address is not waiting for confirmation")
    start_verification(user_id, email, kind)
    return {"sent": True, "email": email}


def check_zone(timezone: str) -> None:
    """Raise ValueError unless ``timezone`` is an IANA zone this server knows."""
    from zoneinfo import ZoneInfo

    try:
        ZoneInfo(timezone)
    except Exception as exc:
        raise ValueError(f"unknown timezone {timezone!r}") from exc


def validate_new(username: str, email: str, password: str) -> str | None:
    if not USERNAME.match(username):
        return "username: 2-32 chars, lowercase letters, digits, . _ -"
    if not EMAIL.match(email):
        return "email does not look like an address"
    return acceptable(password)


class OwnerExists(Exception):
    """The household already has its owner: a first account cannot be made twice."""


#: The Postgres advisory lock the first account is made under ("luach" in ASCII).
OWNER_LOCK = 0x6C75616368


def create_user(
    username: str,
    email: str,
    password: str,
    *,
    display_name: str = "",
    timezone: str | None = None,
    first: bool = False,
    within: Any = None,
) -> Member:
    """A new account. ``first``: the owner, made only while there is no account at all.

    Checking that there is none and adding the account are one transaction under an
    advisory lock, so two registrations that arrive together cannot both become the
    owner: the second waits for the first to commit, then finds it and raises
    OwnerExists.

    ``within``: a database session to make it in, so the caller's own claim (an
    invitation being used up) commits or rolls back with the account."""
    username = username.strip().lower()
    email = email.strip().lower()
    problem = validate_new(username, email, password)
    if problem:
        raise ValueError(problem)
    if timezone:
        check_zone(timezone)
    if within is not None:
        return _create(within, username, email, password, display_name, timezone, first)
    with db.session() as s:
        return _create(s, username, email, password, display_name, timezone, first)


def _create(
    s: Any,
    username: str,
    email: str,
    password: str,
    display_name: str,
    timezone: str | None,
    first: bool,
) -> Member:
    # Every new account waits on the lock, so an owner deleting their own account
    # (remove_self) never misses a member who joins at that moment.
    s.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": OWNER_LOCK})
    if first and s.execute(select(db.User.id).limit(1)).first() is not None:
        raise OwnerExists
    clash = s.execute(
        select(db.User).where((db.User.username == username) | (db.User.email == email))
    ).first()
    if clash or s.get(db.UserEmail, email) is not None:
        raise ValueError("that username or email is already a member")
    user = db.User(
        username=username,
        email=email,
        password_hash=hash_password(password),
        display_name=display_name.strip() or username,
    )
    if timezone:
        user.timezone = timezone
    s.add(user)
    s.flush()
    return _member(user, db.owner_id() or user.id)


def _user_for_email(s: Any, email: str) -> db.User | None:
    """Who owns this address — the primary, or an extra they have confirmed.
    An unconfirmed extra names nobody: it is a claim, not a proof."""
    user = s.execute(select(db.User).where(db.User.email == email)).scalar_one_or_none()
    if user is not None:
        return user
    extra = s.get(db.UserEmail, email)
    if extra is None or extra.verified_at is None:
        return None
    return s.get(db.User, extra.user_id)


#: A hash no password matches, checked when no account has the name given, so that a
#: wrong name takes as long as a wrong password and the time of an answer does not say
#: which names are members. Made on first use, at the cost real hashes are made at.
_no_account_hash: str | None = None


def _dummy_hash() -> str:
    global _no_account_hash
    if _no_account_hash is None:
        _no_account_hash = hash_password("no account has this name")
    return _no_account_hash


def check_login(username: str, password: str) -> Member | None:
    handle = username.strip().lower()
    with db.session() as s:
        user = s.execute(select(db.User).where(db.User.username == handle)).scalar_one_or_none()
        if user is None and "@" in handle:
            user = _user_for_email(s, handle)
        if user is None:
            verify_password(password, _dummy_hash())
            return None
        if not verify_password(password, user.password_hash):
            return None
        return _member(user, db.owner_id())


def member(user_id: int) -> Member | None:
    with db.session() as s:
        user = s.get(db.User, user_id)
        return _member(user, db.owner_id()) if user else None


def member_by_username(username: str) -> Member | None:
    with db.session() as s:
        user = s.execute(
            select(db.User).where(db.User.username == username.strip().lower())
        ).scalar_one_or_none()
        return _member(user, db.owner_id()) if user else None


def member_by_email(email: str) -> Member | None:
    """Any of a member's addresses finds them."""
    with db.session() as s:
        user = _user_for_email(s, email.strip().lower())
        return _member(user, db.owner_id()) if user else None


def emails_listing(user_id: int) -> dict:
    with db.session() as s:
        user = s.get(db.User, user_id)
        if user is None:
            raise ValueError("no such member")
        rows = (
            s.execute(
                select(db.UserEmail)
                .where(db.UserEmail.user_id == user_id)
                .order_by(db.UserEmail.added_at)
            )
            .scalars()
            .all()
        )
        return {
            "primary": user.email,
            "emails": [
                {
                    "email": user.email,
                    "added_at": db.iso(user.created_at),
                    "verified": True,
                },
                *[
                    {
                        "email": r.email,
                        "added_at": db.iso(r.added_at),
                        "verified": r.verified_at is not None,
                    }
                    for r in rows
                    if r.email != user.email
                ],
            ],
        }


def add_email(user_id: int, email: str) -> dict:
    """Claim an address. It is confirmed by following the link mailed to it."""
    email = email.strip().lower()
    if not EMAIL.match(email):
        raise ValueError("email does not look like an address")
    started = False
    with db.session() as s:
        user = s.get(db.User, user_id)
        if user is None:
            raise ValueError("no such member")
        held = s.get(db.UserEmail, email)
        if held is not None and held.user_id != user_id:
            raise ValueError("that address belongs to another member")
        other = s.execute(
            select(db.User).where(db.User.email == email, db.User.id != user_id)
        ).first()
        if other:
            raise ValueError("that address belongs to another member")
        count = len(
            s.execute(select(db.UserEmail).where(db.UserEmail.user_id == user_id)).scalars().all()
        )
        if held is None and count >= MAX_ALIASES:
            raise ValueError(f"at most {MAX_ALIASES} extra addresses")
        if held is None and user.email != email:
            s.add(db.UserEmail(email=email, user_id=user_id))
            started = True
    if started:
        start_verification(user_id, email, "alias")
    return emails_listing(user_id)


def remove_email(user_id: int, email: str) -> dict:
    email = email.strip().lower()
    with db.session() as s:
        user = s.get(db.User, user_id)
        if user is None:
            raise ValueError("no such member")
        if user.email == email:
            raise ValueError("make another address primary first")
        row = s.get(db.UserEmail, email)
        if row is None or row.user_id != user_id:
            raise ValueError("that address is not yours")
        s.delete(row)
    return emails_listing(user_id)


def _confirmed_for(user_id: int, email: str) -> None:
    """Raise unless ``email`` is this member's primary or a confirmed address of theirs."""
    with db.session() as s:
        user = s.get(db.User, user_id)
        if user is None:
            raise ValueError("no such member")
        if user.email == email:
            return
        row = s.get(db.UserEmail, email)
        if row is None or row.user_id != user_id:
            if _user_for_email(s, email) is not None:
                raise ValueError("that address belongs to another member")
            raise ValueError(
                "add that address and confirm it from the link mailed to it, "
                "then make it your primary"
            )
        if row.verified_at is None:
            raise ValueError("confirm that address before making it primary")


def make_primary(user_id: int, email: str) -> dict:
    email = email.strip().lower()
    with db.session() as s:
        user = s.get(db.User, user_id)
        if user is None:
            raise ValueError("no such member")
        if user.email == email:
            return emails_listing(user_id)
        row = s.get(db.UserEmail, email)
        if row is None or row.user_id != user_id:
            raise ValueError("that address is not yours")
        if row.verified_at is None:
            raise ValueError("confirm that address before making it primary")
        old = user.email
        s.delete(row)
        user.email = email
        s.flush()
        s.add(db.UserEmail(email=old, user_id=user_id, verified_at=db.utcnow()))
    return emails_listing(user_id)


def members() -> list[Member]:
    with db.session() as s:
        owner = db.owner_id()
        return [
            _member(u, owner) for u in s.execute(select(db.User).order_by(db.User.id)).scalars()
        ]


def is_owner(user_id: int) -> bool:
    return db.owner_id() == user_id


#: A member's own settings, kept as rows of the settings table rather than by a foreign key
#: (reminders.KEY, booking._key, mail_scan.SETTING): they go with the account by hand.
_OWN_SETTINGS = ("reminders.{id}", "booking.{id}", "mail_scan:{id}")


def _drop(s: Any, user: db.User) -> None:
    for key in _OWN_SETTINGS:
        row = s.get(db.Setting, key.format(id=user.id))
        if row is not None:
            s.delete(row)
    s.delete(user)


def remove(user_id: int) -> bool:
    if is_owner(user_id):
        return False
    with db.session() as s:
        user = s.get(db.User, user_id)
        if user is None:
            return False
        _drop(s, user)
        return True


class OwnerHasMembers(Exception):
    """The owner asked to delete their own account while others still belong to the household."""


def remove_self(user_id: int) -> bool:
    """A member deletes their own account (Settings › Delete account). Anyone may, except the
    owner while anyone else belongs: the next account would silently become the owner, so the
    owner removes the others first. Checked and deleted under the lock new accounts are made
    under, so no one joins between the check and the delete. False when there is no such member."""
    with db.session() as s:
        s.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": OWNER_LOCK})
        user = s.get(db.User, user_id)
        if user is None:
            return False
        owner = s.execute(select(db.User.id).order_by(db.User.id.asc()).limit(1)).scalar()
        if (
            owner == user_id
            and s.execute(select(db.User.id).where(db.User.id != user_id).limit(1)).first()
        ):
            raise OwnerHasMembers
        _drop(s, user)
        return True


def owner_has_members(user_id: int) -> bool:
    """Whether remove_self would refuse this member now (see there)."""
    if not is_owner(user_id):
        return False
    with db.session() as s:
        return (
            s.execute(select(db.User.id).where(db.User.id != user_id).limit(1)).first() is not None
        )


def set_password(user_id: int, password: str) -> None:
    problem = acceptable(password)
    if problem:
        raise ValueError(problem)
    with db.session() as s:
        user = s.get(db.User, user_id)
        if user is None:
            raise ValueError("no such member")
        user.password_hash = hash_password(password)


def update_profile(
    user_id: int,
    *,
    display_name: str | None = None,
    timezone: str | None = None,
    language: str | None = None,
    email: str | None = None,
    model: str | None = None,
) -> Member:
    """Change what a member says about themselves. A new primary ``email`` must already
    be one of their confirmed addresses (POST /api/auth/emails, then the link mailed to
    it): an address that was never proven theirs would become where their password
    resets and confirmations go. Checked before anything is changed."""
    if email is not None:
        email = email.strip().lower()
        if not EMAIL.match(email):
            raise ValueError("email does not look like an address")
        _confirmed_for(user_id, email)
    with db.session() as s:
        user = s.get(db.User, user_id)
        if user is None:
            raise ValueError("no such member")
        if display_name is not None:
            user.display_name = display_name.strip()[:128]
        if timezone is not None:
            check_zone(timezone)
            user.timezone = timezone
        if language is not None:
            if language not in {"auto", "en", "es", "he"}:
                raise ValueError("language must be auto, en, es or he")
            user.language = language
        if model is not None:
            from luach import model_menu

            if model and not model_menu.allowed(model):
                raise ValueError("that model is not one luach offers")
            user.model = model_menu.pick(model)
        s.flush()
        updated = _member(user, db.owner_id())
    if email is not None and email != updated.email:
        make_primary(user_id, email)
        found = member(user_id)
        assert found is not None
        return found
    return updated

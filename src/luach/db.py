"""Persistence — Postgres, SQLAlchemy 2.0, no ORM magic in routes.

Tables:
    users, sessions, invites, resets      membership and sign-in
    email_verifications                   confirmation links for added addresses
    notify_emails                         extra inboxes invited to a member's events
    threads, turns                        each member's conversations
    pending_actions                       tool calls the gate held for a person
    audit_records                         the tulip audit chain, durable
    push_subscriptions                    Web Push endpoints
    processed_mail                        the email door's dedupe ledger
    bookings                              meetings taken through a member's link
    busy_sources, busy_blocks             read-only feeds (the work calendar)
    sent_reminders                        what a member has already been told
    thread_events                         event ids a thread created (own-thread rule)
    people                                the family events and tasks belong to
    tasks, task_done                      to-dos and chores, and the days a chore was done
    boards, board_pairings                screens on the wall, and screens waiting to become one
    menu_models, model_trials             the models members choose from, and their "Try it" runs
    calendar_feeds                        each member's calendar subscription link (its hash)

The store is Postgres (since 2026-10; one SQLite file before). Its schema is
Alembic's: src/luach/migrations, brought to head by ``luach-migrate`` before the
app starts. Columns are unbounded text where SQLite, which never enforced a
length, had a declared one: a longer value it accepted must not start failing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, overload

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from luach import config


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@overload
def iso(value: datetime) -> str: ...
@overload
def iso(value: None) -> None: ...
def iso(value: datetime | None) -> str | None:
    """A stored time as the API says it: UTC, with its offset.

    Rows keep naive UTC (utcnow). Sent without an offset, a browser reads
    "2026-09-23T16:41:27" as its own local time, so every "last seen" and
    "created" was off by the household's distance from Greenwich.
    """
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True)
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String, default="")
    timezone: Mapped[str] = mapped_column(String, default=config.DEFAULT_TIMEZONE)
    language: Mapped[str] = mapped_column(String, default="auto")
    #: The model this member's turns are answered by; "" is the household's own.
    model: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class UserEmail(Base):
    """Extra addresses a member owns; the primary stays on users.email.

    An address does nothing until its owner proves they read mail there:
    ``verified_at`` is NULL until the confirmation link is followed, and
    only a verified address signs in, becomes primary, or names a member.
    """

    __tablename__ = "user_emails"
    email: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OidcLink(Base):
    """Which single sign-on account is a member's: the provider's subject, kept from the
    first sign-in. After that the subject decides, not the email claim, so an account at
    the provider that later shows a member's address cannot sign in as them."""

    __tablename__ = "oidc_links"
    issuer: Mapped[str] = mapped_column(String, primary_key=True)
    subject: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EmailVerification(Base):
    """A confirmation link waiting to be followed. Short-lived, one use."""

    __tablename__ = "email_verifications"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # alias | notify
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class NotifyEmail(Base):
    """Addresses a member wants on every event they create (e.g. a work inbox).
    Not sign-in addresses: they only receive the Google Calendar invitation."""

    __tablename__ = "notify_emails"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    email: Mapped[str] = mapped_column(String, primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Passkey(Base):
    __tablename__ = "passkeys"
    id: Mapped[str] = mapped_column(String, primary_key=True)  # credential id, base64url
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    public_key: Mapped[str] = mapped_column(Text)  # base64url COSE key
    sign_count: Mapped[int] = mapped_column(Integer, default=0)
    transports: Mapped[str] = mapped_column(String, default="")
    name: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_used: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Challenge(Base):
    """A WebAuthn challenge waiting for its verify call. Short-lived, one use."""

    __tablename__ = "webauthn_challenges"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)  # register | login
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    challenge: Mapped[str] = mapped_column(String)  # base64url
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class SessionRow(Base):
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Invite(Base):
    __tablename__ = "invites"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Reset(Base):
    __tablename__ = "resets"
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LocalEvent(Base):
    """An event on the calendar luach keeps itself (``LUACH_CALENDAR=local``).

    Dev had no Google credential, so it ran the in-memory fake: every event a
    person added there vanished on the next deploy, which made dev useless for
    trying anything out. These rows sit in the same database as the threads, on
    the same volume, and outlive a restart without anybody having to connect an
    account.
    """

    __tablename__ = "local_events"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    calendar_id: Mapped[str] = mapped_column(String, default="")
    title: Mapped[str] = mapped_column(String, default="")
    #: ISO datetime, or YYYY-MM-DD for an all-day event — exactly what Google
    #: returns, so the rest of luach cannot tell the two backends apart.
    start: Mapped[str] = mapped_column(String, default="")
    end: Mapped[str] = mapped_column(String, default="")
    all_day: Mapped[bool] = mapped_column(Boolean, default=False)
    location: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    recurrence_json: Mapped[str] = mapped_column(Text, default="[]")
    attendees_json: Mapped[str] = mapped_column(Text, default="[]")
    creator: Mapped[str] = mapped_column(String, default="")
    updated: Mapped[str] = mapped_column(String, default="")
    leader: Mapped[str] = mapped_column(String, default="")


class LocalEventException(Base):
    """One occurrence of a repeating local event that is not as its series says.

    Google keeps these on its own side (a cancelled or a changed instance); the
    local calendar keeps them here: ``cancelled`` is a deleted occurrence (an
    EXDATE), otherwise ``changes_json`` holds the fields the occurrence has of
    its own (moved, renamed, someone else's). ``occurrence`` is the original
    start, ``YYYYMMDDTHHMMSS`` in the household's zone, as in the occurrence's id.
    """

    __tablename__ = "local_event_exceptions"
    series_id: Mapped[str] = mapped_column(
        ForeignKey("local_events.id", ondelete="CASCADE"), primary_key=True
    )
    occurrence: Mapped[str] = mapped_column(String, primary_key=True)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    changes_json: Mapped[str] = mapped_column(Text, default="{}")


class Person(Base):
    """Someone in the family — not necessarily an account (see luach.family)."""

    __tablename__ = "people"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True)
    name: Mapped[str] = mapped_column(String)
    #: A Google Calendar event colorId, "1"–"11".
    color: Mapped[str] = mapped_column(String, default="")
    kind: Mapped[str] = mapped_column(String, default="adult")
    email: Mapped[str] = mapped_column(String, default="")
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)


class Task(Base):
    """A to-do (once) or a chore (on weekdays) — see luach.tasks."""

    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    #: A people.key, or "" for whoever gets to it.
    person: Mapped[str] = mapped_column(String, default="")
    #: YYYY-MM-DD, or "" for no particular day.
    due: Mapped[str] = mapped_column(String, default="")
    #: Comma-joined MO…SU for a chore; "" for a to-do.
    days: Mapped[str] = mapped_column(String, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    #: A to-do's tick. Chores keep theirs in task_done, one row per day.
    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    done_on: Mapped[str] = mapped_column(String, default="")
    done_by: Mapped[str] = mapped_column(String, default="")


class TaskDone(Base):
    __tablename__ = "task_done"
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[str] = mapped_column(String, primary_key=True)
    by: Mapped[str] = mapped_column(String, default="")
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Board(Base):
    """A paired screen (see luach.board). Not a member; it holds no session."""

    __tablename__ = "boards"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="House board")
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Whether the screen may add, change and remove, or only show and tick.
    can_edit: Mapped[bool] = mapped_column(Boolean, default=True)
    #: The language the screen speaks: "auto" follows the screen's own browser.
    language: Mapped[str] = mapped_column(String, default="auto")


class BoardPairing(Base):
    __tablename__ = "board_pairings"
    code: Mapped[str] = mapped_column(String, primary_key=True)
    secret_hash: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    #: The board's token between the owner's claim and the screen collecting it.
    token: Mapped[str] = mapped_column(String, default="")


class Thread(Base):
    __tablename__ = "threads"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String, default="")
    door: Mapped[str] = mapped_column(String, default="web")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Turn(Base):
    __tablename__ = "turns"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[str] = mapped_column(ForeignKey("threads.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String)
    content: Mapped[str] = mapped_column(Text)
    events_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ThreadEvent(Base):
    __tablename__ = "thread_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[str] = mapped_column(String)
    event_id: Mapped[str] = mapped_column(String)


class PendingAction(Base):
    __tablename__ = "pending_actions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    #: Who asked. Kept when they leave, as nobody: a decided action is the household's
    #: record, and a member who once had one held could not be removed at all.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    principal: Mapped[str] = mapped_column(String)
    door: Mapped[str] = mapped_column(String, default="web")
    thread_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tool: Mapped[str] = mapped_column(String)
    args_json: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String, default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[str] = mapped_column(String, default="")
    result_json: Mapped[str] = mapped_column(Text, default="")
    #: Where a proposal came from when it was not a person asking: for the email
    #: scan, {"kind": "email", "id", "subject", "from", "when"}. "" otherwise.
    source_json: Mapped[str] = mapped_column(Text, default="")


class AuditRow(Base):
    __tablename__ = "audit_records"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    ts: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String)
    payload_json: Mapped[str] = mapped_column(Text)
    prev_hash: Mapped[str] = mapped_column(String)
    hash: Mapped[str] = mapped_column(String)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(Text, unique=True)
    subscription_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ProcessedMail(Base):
    __tablename__ = "processed_mail"
    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    outcome: Mapped[str] = mapped_column(Text, default="")


class MailScan(Base):
    """A message the email scan has read, per member, whatever it found.

    Keyed by member as well as message: two people can receive the same mail,
    and each is asked about their own copy. A message is read once, so a
    proposal someone turned down is never offered again.
    """

    __tablename__ = "mail_scans"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    message_id: Mapped[str] = mapped_column(String, primary_key=True)
    scanned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    outcome: Mapped[str] = mapped_column(Text, default="")
    proposed: Mapped[int] = mapped_column(Integer, default=0)


class MailConnection(Base):
    """One member's own Gmail, connected by them and searched only for them."""

    __tablename__ = "mail_connections"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    address: Mapped[str] = mapped_column(String, default="")
    #: The refresh token, Fernet-encrypted with mail_accounts' key; never stored plain.
    grant: Mapped[str] = mapped_column(Text)
    connected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BusySource(Base):
    """An iCalendar feed luach reads for busy time only — the work calendar."""

    __tablename__ = "busy_sources"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String, default="Work")
    url: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    show_in_agenda: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fetched: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")
    block_count: Mapped[int] = mapped_column(Integer, default=0)


class BusyBlock(Base):
    """One span of time a feed says is taken. Replaced wholesale on each read."""

    __tablename__ = "busy_blocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("busy_sources.id", ondelete="CASCADE"))
    start: Mapped[str] = mapped_column(String)  # ISO, UTC
    end: Mapped[str] = mapped_column(String)


class Booking(Base):
    """A meeting someone took through a member's booking link."""

    __tablename__ = "bookings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    event_id: Mapped[str] = mapped_column(String)
    calendar_id: Mapped[str] = mapped_column(String, default="")
    day: Mapped[str] = mapped_column(String)  # YYYY-MM-DD in the member's zone
    start: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    #: What the confirmation mail carries, so a visitor can move or call off
    #: their own meeting without an account.
    token_hash: Mapped[str] = mapped_column(String, default="", index=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: The Zoom meeting made for it: moving updates it, cancelling removes it.
    zoom_id: Mapped[str] = mapped_column(String, default="")
    #: The visitor's own timezone, so what they are told reads in their hours
    #: rather than the host's. Empty for bookings taken before this was kept.
    timezone: Mapped[str] = mapped_column(String, default="")


class SentReminder(Base):
    """One reminder already delivered. Stops a restart repeating itself."""

    __tablename__ = "sent_reminders"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class MenuModel(Base):
    """A model on the household's menu (see luach.model_menu). The owner adds,
    edits, orders and enables them in the app; members choose among the enabled
    ones. Health is what luach saw of it answering."""

    __tablename__ = "menu_models"
    #: The id the model server answers to.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    about: Mapped[str] = mapped_column(Text, default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    #: On the members' menu. A model the owner has just added is not, until they say so.
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Runs on the household's own machine: what is asked never leaves the house.
    local: Mapped[bool] = mapped_column(Boolean, default=False)
    #: Who answers, as the privacy page says it ("Google, through OpenRouter"). "" is
    #: worked out from the id.
    provider: Mapped[str] = mapped_column(String, default="")
    #: What the catalogue said of it when it was added: context length, tools, price.
    meta_json: Mapped[str] = mapped_column(Text, default="")
    added_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    #: Failed turns in a row; any answer sets it back to 0.
    failures: Mapped[int] = mapped_column(Integer, default=0)
    #: When it stopped answering, and why; NULL while it answers.
    unhealthy_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    unhealthy_reason: Mapped[str] = mapped_column(Text, default="")
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ModelTrial(Base):
    """One "Try it" run: luach's own eval cases against a model, on a fake calendar
    and a throwaway database (see luach.model_trials)."""

    __tablename__ = "model_trials"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_id: Mapped[str] = mapped_column(String, index=True)
    #: running | done | failed | cancelled
    status: Mapped[str] = mapped_column(String, default="running")
    requested_by: Mapped[str] = mapped_column(String, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: Cases run so far, cases passed, cases in all.
    done: Mapped[int] = mapped_column(Integer, default=0)
    passed: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    #: One {case, about, ok, problems, tools} per case run.
    report_json: Mapped[str] = mapped_column(Text, default="[]")
    error: Mapped[str] = mapped_column(Text, default="")


class CalendarFeed(Base):
    """A member's calendar subscription link (see luach.feed): one at most, off until
    they turn it on. Only the token's hash is kept, so the link is shown once; a
    removed member's goes with them."""

    __tablename__ = "calendar_feeds"
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    token_hash: Mapped[str] = mapped_column(String, unique=True)
    #: household | mine
    scope: Mapped[str] = mapped_column(String, default="household")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    #: When a calendar app last read it; NULL until one has.
    last_read: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# --- engine ---------------------------------------------------------------

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = init_db()
    return _engine


def init_db(url: str | None = None) -> Engine:
    """Open the store and make it the process engine, refusing a schema this
    build does not know: luach-migrate brings it to head first (the compose file's
    migrate service, or an init container), and a store behind the code is a
    deploy that skipped it."""
    global _engine
    from luach import migrate

    engine = migrate.engine(url or config.database_url(), pool_pre_ping=True)
    try:
        migrate.require_current(engine)
    except Exception:
        engine.dispose()
        raise
    if _engine is not None and _engine is not engine:
        _engine.dispose()
    _engine = engine
    return engine


def reset_engine() -> None:
    """Tests: forget the process engine so the next call opens a fresh one."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


@contextmanager
def session() -> Iterator[Session]:
    with Session(get_engine(), expire_on_commit=False) as s:
        yield s
        s.commit()


# --- small helpers used across modules -------------------------------------


def users_exist() -> bool:
    with session() as s:
        return s.execute(select(User.id).limit(1)).first() is not None


def owner_id() -> int | None:
    """The first account is the owner — the one who bootstrapped the box."""
    with session() as s:
        row = s.execute(select(User.id).order_by(User.id.asc()).limit(1)).first()
        return int(row[0]) if row else None


def get_user(user_id: int) -> User | None:
    with session() as s:
        return s.get(User, user_id)


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def loads(raw: str, default: Any = None) -> Any:
    try:
        return json.loads(raw) if raw else default
    except json.JSONDecodeError:
        return default

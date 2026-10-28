from __future__ import annotations

import os
import secrets
from collections.abc import Iterator

import bcrypt
import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from luach import db, memory, migrate, model_catalogue
from luach.agent import control, runtime
from luach.auth import throttle
from luach.calendar import client

_gensalt = bcrypt.gensalt

# Every table the tests may have written, emptied between tests: the models' and the record of
# a copy from SQLite. Not tulip's memory, which a test that wants it sets up itself.
_TABLES = ", ".join([*db.Base.metadata.tables, "sqlite_import"])


def _server() -> str:
    url = os.environ.get("LUACH_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.exit(
            "LUACH_TEST_DATABASE_URL is not set: the tests need a Postgres "
            "(`hatch run pg` starts one; hatch points the tests at it)",
            returncode=2,
        )
    return url


def with_database(url: str, name: str) -> str:
    """The same server, another database, as a URL."""
    return make_url(url).set(database=name).render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def database_url(worker_id: str) -> Iterator[str]:
    """A Postgres database of this worker's own, migrated once, as luach-migrate would.

    One per pytest-xdist worker, so workers never see each other's rows; each
    test empties it (fresh_state) rather than making a new one, which is what
    keeps hundreds of tests that each sign two members up fast.
    """
    server = _server()
    name = f"luach_test_{worker_id}_{secrets.token_hex(3)}"
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(
            f"CREATE DATABASE {name} TEMPLATE template0 ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C'"
        )
    url = with_database(server, name)
    migrate.upgrade(url)
    yield url
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


def _empty(url: str) -> None:
    """Every table emptied: a store as a new household has it."""
    engine = create_engine(migrate.sqlalchemy_url(url))
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_TABLES} RESTART IDENTITY CASCADE"))
    engine.dispose()


@pytest.fixture
def emptied(database_url: str) -> str:
    """This worker's store with nothing in it -- not even the two members every
    test starts with -- and its URL."""
    db.reset_engine()
    _empty(database_url)
    return database_url


@pytest.fixture(autouse=True)
def fresh_state(tmp_path, monkeypatch, database_url):
    # bcrypt's cost is the point in production and only a wait here: every test makes two
    # members, and at the default 12 rounds their hashes were half the suite's time. The
    # lowest cost bcrypt takes still hashes and checks the same way; the cost is in the hash.
    monkeypatch.setattr(bcrypt, "gensalt", lambda rounds=4, prefix=b"2b": _gensalt(rounds, prefix))
    monkeypatch.setenv("LUACH_DATABASE_URL", database_url)
    monkeypatch.setenv("LUACH_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("LUACH_CHECKPOINT_DIR", str(tmp_path / "threads"))
    monkeypatch.setenv("LUACH_CALENDAR", "fake")
    monkeypatch.setenv("LUACH_APP_URL", "https://luach.test")
    monkeypatch.setenv("LUACH_COOKIE_SECURE", "0")
    # luach has no model of its own: every household names its endpoint and model.
    monkeypatch.setenv("LUACH_MODEL", "qwen3.6-35b")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://models.test/v1")
    monkeypatch.delenv("LUACH_MODELS", raising=False)
    monkeypatch.delenv("LUACH_MODEL_CATALOGUE_URL", raising=False)
    monkeypatch.delenv("LUACH_MODEL_CATALOGUE_PREFIX", raising=False)
    monkeypatch.delenv("LUACH_PRIVACY_MODELS", raising=False)
    monkeypatch.delenv("LUACH_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    # No memory database unless a test asks for one: the default should be the
    # shape a fresh household runs in, which is without.
    monkeypatch.delenv("LUACH_MEMORY_DSN", raising=False)
    memory.reset()
    db.reset_engine()
    _empty(database_url)
    db.init_db(database_url)
    control.reset_trail()
    runtime.reset()
    model_catalogue.reset()
    throttle.reset_all()
    client.set_calendar(client.FakeCalendar())
    from luach.auth import users

    users.create_user("robin", "robin@example.com", "correct horse battery", display_name="Robin")
    users.create_user("ana", "ana@example.com", "another good password")
    yield
    client.set_calendar(None)
    memory.reset()
    db.reset_engine()


@pytest.fixture
def two_calendars() -> client.FakeCalendar:
    """A household with two calendars in use and a third it ignores."""
    from luach import household

    fake = client.FakeCalendar(
        [
            client.CalendarInfo(id="home", name="Harper Calendar", color="#f4b942", primary=True),
            client.CalendarInfo(id="work", name="Work", color="#4488ff"),
            client.CalendarInfo(id="school", name="School"),
        ]
    )
    client.set_calendar(fake)
    household.update(calendars=["home", "work"], default_calendar="home")
    return fake


@pytest.fixture
def calendar() -> client.FakeCalendar:
    cal = client.get_calendar()
    assert isinstance(cal, client.FakeCalendar)
    return cal

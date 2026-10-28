"""Bring luach's database to the schema this build expects: `luach-migrate`.

Run before the app starts wherever luach is deployed (the compose file's
`migrate` service, or an init container in a cluster), and by the tests on
their own database. A no-op when the schema is already current.

luach once kept a SQLite file. An install that had one copied it in once, the
first time luach-migrate met an empty store (the `sqlite_import` table records
when); the copy has been removed since.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg.abc import Buffer
from psycopg.types.string import StrBinaryDumper, StrDumperUnknown
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

HERE = Path(__file__).resolve().parent


def sqlalchemy_url(url: str) -> str:
    """The same database through psycopg 3. CloudNativePG's secret, like every
    other tool, says `postgresql://`, which SQLAlchemy reads as psycopg2."""
    if not url:
        raise RuntimeError("no database: set LUACH_DATABASE_URL")
    for scheme in ("postgresql://", "postgres://"):
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url[len(scheme) :]
    return url


class _TextWithoutNul(StrDumperUnknown):
    """psycopg's string dumper (text), minus NUL characters."""

    def dump(self, obj: str) -> Buffer | None:
        return super().dump(obj.replace("\x00", ""))


class _BinaryWithoutNul(StrBinaryDumper):
    """psycopg's string dumper (binary), minus NUL characters."""

    def dump(self, obj: str) -> Buffer | None:
        return super().dump(obj.replace("\x00", ""))


def _no_nul_in_text(dbapi_conn: Any, _record: Any) -> None:
    """Postgres cannot keep a NUL character in text; SQLite kept it. luach stores
    what arrives -- an email's body, a calendar feed, a model's reply -- and a
    NUL in any of them is noise, never meaning, so it is dropped on the way in
    rather than failing the write (a copy of an old SQLite store stopped on one,
    in a mail turn)."""
    dbapi_conn.adapters.register_dumper(str, _TextWithoutNul)
    dbapi_conn.adapters.register_dumper(str, _BinaryWithoutNul)


def engine(url: str, **kwargs: Any) -> Engine:
    """luach's engine on its store: psycopg 3, and text without NUL characters."""
    made = create_engine(sqlalchemy_url(url), **kwargs)
    event.listen(made, "connect", _no_nul_in_text)
    return made


def config(url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(HERE / "migrations"))
    # `%` is ConfigParser's interpolation; a password may hold one.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def head() -> str:
    found = ScriptDirectory.from_config(config("")).get_current_head()
    assert found is not None
    return found


def current(engine: Engine) -> str | None:
    """The revision this database is at, or None for one never migrated."""
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def upgrade(url: str) -> None:
    command.upgrade(config(sqlalchemy_url(url)), "head")


class SchemaBehind(RuntimeError):
    """The database is not at the revision this build was written for."""


def require_current(engine: Engine) -> None:
    """Refuse to serve a schema this build does not know: run luach-migrate."""
    at, want = current(engine), head()
    if at != want:
        raise SchemaBehind(
            f"database at {at or 'nothing'}, this build needs {want}: run luach-migrate"
        )


def main() -> int:
    url = os.environ.get("LUACH_DATABASE_URL", "").strip()
    if not url:
        print("luach-migrate: LUACH_DATABASE_URL is not set", file=sys.stderr)
        return 2
    upgrade(url)
    print(f"luach-migrate: schema at {head()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

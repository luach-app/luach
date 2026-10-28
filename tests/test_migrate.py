"""luach-migrate: the schema brought to head, and text without NUL characters."""

from __future__ import annotations

import psycopg
import pytest
from sqlalchemy import select

from luach import db, migrate
from luach.auth import users


@pytest.fixture
def bare(database_url):
    """A database luach-migrate has never seen, on the tests' server."""
    name = "luach_bare_" + database_url.rsplit("/", 1)[-1][-6:]
    server = database_url.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {name}")
    yield database_url.rsplit("/", 1)[0] + "/" + name
    with psycopg.connect(server, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


class TestTextWithoutNul:
    def test_the_app_writes_it_without_the_nul(self):
        """The same NUL arriving live (a mail body, a feed) is dropped by the
        driver, so the write that holds it does not fail."""
        users.create_user("nul", "nul@example.com", "a long enough password", display_name="A\x00B")
        with db.session() as s:
            name = s.scalars(select(db.User.display_name).where(db.User.username == "nul")).one()
        assert name == "AB"


class TestTheSchema:
    def test_a_store_behind_is_refused_rather_than_half_working(self, bare):
        with pytest.raises(migrate.SchemaBehind, match="run luach-migrate"):
            db.init_db(bare)

    def test_the_command_brings_a_new_database_to_head(self, bare, monkeypatch, capsys):
        monkeypatch.setenv("LUACH_DATABASE_URL", bare)
        assert migrate.main() == 0
        assert migrate.main() == 0  # and again: every deploy runs it
        assert capsys.readouterr().out.count(f"schema at {migrate.head()}") == 2
        db.init_db(bare)

    def test_without_a_database_it_says_so(self, monkeypatch, capsys):
        monkeypatch.delenv("LUACH_DATABASE_URL", raising=False)
        assert migrate.main() == 2
        assert "LUACH_DATABASE_URL" in capsys.readouterr().err
        with pytest.raises(RuntimeError, match="LUACH_DATABASE_URL"):
            migrate.sqlalchemy_url("")

    @pytest.mark.parametrize(
        ("given", "for_sqlalchemy"),
        [
            ("postgresql://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
            ("postgres://u:p@h/d", "postgresql+psycopg://u:p@h/d"),
            ("postgresql+psycopg://u@h/d", "postgresql+psycopg://u@h/d"),
        ],
    )
    def test_cloudnativepgs_url_reaches_psycopg_3(self, given, for_sqlalchemy):
        assert migrate.sqlalchemy_url(given) == for_sqlalchemy

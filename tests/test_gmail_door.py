from __future__ import annotations

import base64
import io
import urllib.error
from datetime import UTC

import pytest
from google.auth.exceptions import TransportError

from luach import config
from luach.ingest import gmail


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def test_message_text_prefers_plain_and_strips_html():
    msg = {
        "snippet": "snip",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Your flight"},
                {"name": "From", "value": "Air <a@b.c>"},
            ],
            "mimeType": "multipart/alternative",
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _b64("<p>Flight <b>AC123</b></p><style>x{}</style>")},
                },
            ],
        },
    }
    subject, sender, body = gmail.message_text(msg)
    assert subject == "Your flight" and sender.startswith("Air")
    assert "AC123" in body and "<b>" not in body and "x{}" not in body
    msg["payload"]["parts"].append({"mimeType": "text/plain", "body": {"data": _b64("Plain wins")}})
    assert gmail.message_text(msg)[2] == "Plain wins"


def test_prompt_asks_for_low_certainty_by_default():
    p = gmail.prompt_for("Dentist", "x@y.z", "See you Tuesday")
    assert 'certainty="low"' in p and "Subject: Dentist" in p


def test_not_configured_without_poll_interval(monkeypatch):
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_CLIENT", "/x")
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_TOKENS", "/y")
    monkeypatch.setenv("LUACH_GMAIL_POLL_MIN", "0")
    assert gmail.configured() is False
    monkeypatch.setenv("LUACH_GMAIL_POLL_MIN", "5")
    assert gmail.configured() is True


class TestWhereTheDoorPoints:
    """dev points the door at a fixture service: one Google account exists, so dev
    either polls the household's real inbox or tests nothing."""

    def test_google_is_the_default(self, monkeypatch):
        monkeypatch.delenv("LUACH_GMAIL_API", raising=False)
        monkeypatch.delenv("LUACH_GOOGLE_TOKEN_URL", raising=False)
        assert config.gmail_api() == "https://gmail.googleapis.com/gmail/v1/users/me"
        assert config.google_token_url() == "https://oauth2.googleapis.com/token"

    def test_an_override_is_honoured_without_a_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("LUACH_GMAIL_API", "http://gmail-fake:8080/gmail/v1/users/me/")
        assert config.gmail_api() == "http://gmail-fake:8080/gmail/v1/users/me"

    def test_requests_are_built_from_the_override(self, monkeypatch):
        monkeypatch.setenv("LUACH_GMAIL_API", "http://gmail-fake:8080/v1")
        monkeypatch.setattr(gmail, "_token", lambda: "t")
        seen: dict[str, str] = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b"{}"

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            return Resp()

        monkeypatch.setattr(gmail.urllib.request, "urlopen", fake_urlopen)
        gmail._api("labels")
        assert seen["url"] == "http://gmail-fake:8080/v1/labels"

    def test_the_token_refresh_follows_the_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LUACH_GOOGLE_TOKEN_URL", "http://gmail-fake:8080/token")
        client = tmp_path / "c.json"
        client.write_text('{"client_id": "i", "client_secret": "s"}')
        tokens = tmp_path / "t.json"
        tokens.write_text('{"refresh_token": "r"}')
        monkeypatch.setenv("LUACH_GOOGLE_OAUTH_CLIENT", str(client))
        monkeypatch.setenv("LUACH_GOOGLE_OAUTH_TOKENS", str(tokens))
        gmail._access.clear()
        seen: dict[str, str] = {}

        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"access_token": "fresh", "expires_in": 3600}'

        def fake_urlopen(req, timeout=0):
            seen["url"] = req.full_url
            return Resp()

        monkeypatch.setattr(gmail.urllib.request, "urlopen", fake_urlopen)
        assert gmail._token() == "fresh"
        assert seen["url"] == "http://gmail-fake:8080/token"
        gmail._access.clear()


class TestABlipIsNotAFailure:
    """Four DNS blips reaching Google in two days each failed a whole pass of the
    email door and the reminders; the next pass always worked."""

    def _grant(self, monkeypatch, tmp_path):
        client = tmp_path / "c.json"
        client.write_text('{"client_id": "i", "client_secret": "s"}')
        tokens = tmp_path / "t.json"
        tokens.write_text('{"refresh_token": "r"}')
        monkeypatch.setenv("LUACH_GOOGLE_OAUTH_CLIENT", str(client))
        monkeypatch.setenv("LUACH_GOOGLE_OAUTH_TOKENS", str(tokens))
        monkeypatch.setattr(gmail.time, "sleep", lambda s: None)
        gmail._access.clear()

    def _urlopen(self, failures: list[Exception]):
        class Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b'{"access_token": "fresh", "expires_in": 3600}'

        calls: list[str] = []

        def fake(req, timeout=0):
            calls.append(req.full_url)
            if failures:
                raise failures.pop(0)
            return Resp()

        return fake, calls

    def test_the_token_refresh_tries_once_more_after_a_dns_blip(self, monkeypatch, tmp_path):
        self._grant(monkeypatch, tmp_path)
        fake, calls = self._urlopen([urllib.error.URLError("Temporary failure in name resolution")])
        monkeypatch.setattr(gmail.urllib.request, "urlopen", fake)
        assert gmail._token() == "fresh" and len(calls) == 2
        gmail._access.clear()

    def test_a_refused_grant_is_not_retried(self, monkeypatch, tmp_path):

        self._grant(monkeypatch, tmp_path)
        refused = urllib.error.HTTPError("u", 400, "invalid_grant", {}, io.BytesIO(b""))  # type: ignore[arg-type]
        fake, calls = self._urlopen([refused])
        monkeypatch.setattr(gmail.urllib.request, "urlopen", fake)
        with pytest.raises(urllib.error.HTTPError):
            gmail._token()
        assert len(calls) == 1
        gmail._access.clear()

    def test_the_calendar_retries_a_google_auth_transport_error(self, monkeypatch):
        from luach.calendar import client

        monkeypatch.setattr(client.time, "sleep", lambda s: None)
        cal = client.GoogleCalendar.__new__(client.GoogleCalendar)
        attempts: list[int] = []

        class Request:
            def execute(self):
                attempts.append(1)
                if len(attempts) == 1:
                    raise TransportError("Unable to find the server at oauth2.googleapis.com")
                return {"ok": True}

        monkeypatch.setattr(cal, "_svc", lambda: object(), raising=False)
        monkeypatch.setattr(cal, "_drop", lambda: None, raising=False)
        assert cal._run(lambda svc: Request()) == {"ok": True}
        assert len(attempts) == 2


def test_an_event_on_two_calendars_is_listed_once(monkeypatch):
    """The family calendar invites a member: Google lists it on both calendars under one
    iCalUID, and luach, reading both, showed it twice."""
    from datetime import datetime

    from luach.calendar import client

    def ev(uid, title, cal, start="2026-10-05T11:45:00-04:00"):
        return client.Event(
            id=f"{cal}-{uid}", title=title, start=start, end=start, calendar_id=cal, ical_uid=uid
        )

    by_cal = {
        "family": [ev("a", "Podiatrist", "family"), ev("b", "Swim", "family")],
        "mine": [
            ev("a", "Podiatrist", "mine"),
            ev("c", "Interview", "mine"),
            ev("a", "Podiatrist", "mine", start="2026-10-12T11:45:00-04:00"),
        ],
    }
    cal = client.GoogleCalendar.__new__(client.GoogleCalendar)
    cal.calendar_id = "family"
    monkeypatch.setattr(cal, "_list_one", lambda cid, s, e, q: by_cal[cid], raising=False)
    monkeypatch.setattr(client.household, "calendar_ids", lambda: ["family", "mine"])
    now = datetime.now(UTC)
    got = [(e.calendar_id, e.title, e.start[:10]) for e in cal.list_events(now, now)]
    assert ("family", "Podiatrist", "2026-10-05") in got
    assert ("mine", "Podiatrist", "2026-10-05") not in got, "the family's copy is kept"
    assert ("mine", "Podiatrist", "2026-10-12") in got, "another occurrence is its own"
    assert len(got) == 4


# --- who really sent it ---------------------------------------------------------

#: Gmail's verdict as it writes it, folded, with the comments it adds.
GMAIL_PASS = (
    "mx.google.com;\r\n       dkim=pass header.i=@school.example header.s=s1 header.b=AbC;\r\n"
    "       spf=pass (google.com: domain of office@school.example designates 192.0.2.1 as "
    "permitted sender) smtp.mailfrom=office@school.example;\r\n"
    "       dmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from=school.example"
)


def _signed(sender: str, *verdicts: str, extra: list[dict] | None = None) -> dict:
    """A message as Gmail hands it over: what Gmail added on top, then the sender's own."""
    headers = [{"name": "Authentication-Results", "value": v} for v in verdicts]
    headers += [{"name": "From", "value": sender}, {"name": "Subject", "value": "Trip"}]
    headers += extra or []
    return {"id": "m1", "payload": {"headers": headers, "mimeType": "text/plain"}}


class TestOnlyGmailsVerdictForTheFromDomainCounts:
    def test_gmails_own_header_passes_the_sender_it_names(self):
        assert gmail.authenticated(_signed("School <office@school.example>", GMAIL_PASS))

    def test_a_pass_the_sender_wrote_below_gmails_fail_is_ignored(self):
        """Gmail puts its verdict on top; a header further down is the sender's own
        words. headers_of kept the last one, so the forged pass won."""
        forged = _signed(
            "Bank <alerts@bank.example>",
            "mx.google.com; dkim=fail header.i=@bank.example; spf=softfail; dmarc=fail "
            "header.from=bank.example",
            "mx.google.com; dkim=pass header.i=@bank.example; dmarc=pass header.from=bank.example",
        )
        assert not gmail.authenticated(forged)
        assert gmail.headers_of(forged)["authentication-results"].startswith(
            "mx.google.com; dkim=fail"
        )

    def test_another_servers_verdict_is_not_gmails(self):
        assert not gmail.authenticated(
            _signed("a@bank.example", "evil.example; dmarc=pass header.from=bank.example")
        )

    def test_an_unaligned_dkim_pass_proves_nothing_about_the_from_domain(self):
        """Anyone can sign their own mail: a pass for evil.example is not bank.example."""
        msg = _signed(
            "Bank <alerts@bank.example>",
            "mx.google.com; dkim=pass header.i=@evil.example; spf=pass "
            "smtp.mailfrom=bounce@evil.example; dmarc=fail header.from=bank.example",
        )
        assert not gmail.authenticated(msg)

    def test_an_aligned_dkim_pass_counts_for_the_domain_and_its_parent(self):
        for signer in ("school.example", "mail.school.example"):
            assert gmail.authenticated(
                _signed("office@school.example", f"mx.google.com; dkim=pass header.i=@{signer}")
            ), signer
        assert gmail.authenticated(
            _signed(
                "office@news.school.example", "mx.google.com; dkim=pass header.d=school.example"
            )
        )
        assert not gmail.authenticated(
            _signed("a@b.school.example", "mx.google.com; dkim=pass header.i=@c.school.example")
        ), "a sibling is not the parent"

    def test_an_aligned_spf_pass_counts(self):
        assert gmail.authenticated(
            _signed(
                "office@school.example", "mx.google.com; spf=pass smtp.mailfrom=b@school.example"
            )
        )
        assert not gmail.authenticated(
            _signed(
                "office@school.example",
                "mx.google.com; spf=pass (google.com: smtp.mailfrom=x@school.example) "
                "smtp.mailfrom=x@evil.example",
            )
        ), "a comment is not a property"

    def test_dmarc_passes_only_for_the_from_domain(self):
        assert gmail.authenticated(
            _signed("a@bank.example", "mx.google.com; dmarc=pass (p=NONE) header.from=bank.example")
        )
        assert not gmail.authenticated(
            _signed("a@bank.example", "mx.google.com; dmarc=pass header.from=evil.example")
        )

    def test_two_from_headers_are_not_judged(self):
        msg = _signed(
            "office@school.example",
            GMAIL_PASS,
            extra=[{"name": "From", "value": "robin@example.com"}],
        )
        assert not gmail.authenticated(msg)

    def test_no_from_or_no_verdict_is_not_a_pass(self):
        assert not gmail.authenticated(_signed("", GMAIL_PASS))
        assert not gmail.authenticated(_signed("office@school.example"))

    def test_devs_gmail_stand_in_passes_the_door(self):
        """dev's door reads fixtures/gmail-fake: its labelled mail carries Gmail's
        verdict, so dev runs the real turn instead of skipping it as forged."""
        import importlib.util
        from pathlib import Path

        path = Path(__file__).parents[1] / "fixtures" / "gmail-fake" / "app.py"
        spec = importlib.util.spec_from_file_location("gmail_fake", path)
        assert spec and spec.loader
        fake = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fake)
        for mid in ("msg-appointment", "msg-newsletter"):
            assert gmail.authenticated(fake.MESSAGES[mid]), mid
        assert not gmail.authenticated(fake.MESSAGES["msg-malformed"])

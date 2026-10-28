"""Asking luach about your email in chat: "when is our flight?", then "put it in".
The whole mailbox is searched — but only by its owner, only when asked, and what
comes back is quoted mail, never instructions."""

from __future__ import annotations

import base64
from datetime import timedelta

import pytest

from luach.agent import runtime, tools
from luach.calendar import times
from luach.ingest import gmail
from tests.doubles import ScriptedModel, call, say

TZ = "America/New_York"


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


FLIGHT = {
    "id": "m-flight",
    "snippet": "Your booking to Madrid is confirmed &amp; paid",
    "payload": {
        "mimeType": "text/plain",
        "headers": [
            {"name": "Subject", "value": "Booking confirmed: Chicago to Madrid"},
            {"name": "From", "value": "Fixture Air <bookings@air.test>"},
            {"name": "Date", "value": "Mon, 21 Sep 2026 10:02:00 -0400"},
        ],
        "body": {"data": _b64("Flight FX 610 departs Chicago on 23 October at 21:40.")},
    },
}


@pytest.fixture
def mailbox(monkeypatch, tmp_path):
    """The owner's Gmail, connected: a grant on disk and one flight email in it."""
    for name in ("client", "tokens"):
        (tmp_path / f"{name}.json").write_text("{}")
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_CLIENT", str(tmp_path / "client.json"))
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_TOKENS", str(tmp_path / "tokens.json"))
    asked: list[tuple[str, dict | None]] = []

    def fake_api(path, method="GET", payload=None, query=None, token=None):
        asked.append((path, query))
        if path == "messages":
            return {"messages": [{"id": "m-flight"}] if "flight" in query["q"] else []}
        if path == "messages/m-flight":
            return FLIGHT
        raise RuntimeError("gmail said 404")

    monkeypatch.setattr(gmail, "_api", fake_api)
    # The owner's own mailbox, through the grant the email door holds.
    monkeypatch.setattr(gmail, "_token", lambda: "household-token")
    return asked


def _names(principal: str = "robin") -> set[str]:
    return {getattr(t, "name", getattr(t, "__name__", "")) for t in tools.toolset(principal)}


def test_offered_only_when_a_mailbox_is_connected(mailbox, monkeypatch):
    assert any("search_email" in n for n in _names())
    monkeypatch.delenv("LUACH_GOOGLE_OAUTH_TOKENS")
    assert not any("search_email" in n for n in _names())


def test_the_whole_mailbox_is_searched_not_the_label(mailbox):
    found = gmail.search(1, "flight")
    assert found == [
        {
            "id": "m-flight",
            "when": "Mon 21 Sep 2026 10:02",
            "from": "Fixture Air <bookings@air.test>",
            "subject": "Booking confirmed: Chicago to Madrid",
            "snippet": "Your booking to Madrid is confirmed & paid",
        }
    ]
    listing = [q for p, q in mailbox if p == "messages"][0]
    assert listing == {"q": "flight", "maxResults": gmail.SEARCH_LIMIT}  # no labelIds


def test_a_mailbox_that_does_not_answer_is_not_an_empty_one(mailbox, monkeypatch):
    monkeypatch.setattr(gmail, "_api", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(gmail.MailUnavailable):
        gmail.search(1, "flight")


async def test_ask_then_add(mailbox, calendar):
    """ "When is our flight to Madrid? put it in" — search, open it, add it."""
    start = (times.now_in(TZ) + timedelta(days=28)).strftime("%Y-%m-%dT21:40")
    runtime.set_model(
        ScriptedModel(
            [
                [call("search_email", query="flight Madrid")],
                [call("read_email", message_id="m-flight")],
                [call("create_event", title="Flight to Madrid", start=start)],
                [say("Your flight to Madrid is on 23 October at 21:40 — added.")],
            ]
        )
    )
    r = await runtime.run_turn(
        "when is our flight to madrid? put it in the calendar",
        user_id=1,
        principal="robin",
        timezone=TZ,
    )
    (ev,) = calendar.events.values()
    assert ev.title == "Flight to Madrid"
    searched = [t for t in r.tool_calls if t["tool"] == "search_email"]
    assert searched and searched[0]["args"]["query"] == "flight Madrid"


async def test_a_member_with_no_mailbox_of_their_own_is_told_how(mailbox, calendar):
    runtime.set_model(
        ScriptedModel([[call("search_email", query="flight")], [say("I cannot look.")]])
    )
    r = await runtime.run_turn("when is the flight", user_id=2, principal="ana", timezone=TZ)
    assert not [p for p, _ in mailbox if p == "messages"], "Ana's turn read the owner's mail"
    assert "cannot" in r.reply


def test_what_comes_back_is_fenced_as_quoted_mail(mailbox, calendar):
    from luach.agent import context

    context.set_turn(context.Turn(calendar=calendar, user_id=1, principal="robin", timezone=TZ))
    try:
        fn = getattr(tools.search_email, "fn", tools.search_email)
        result = fn("flight")
    finally:
        context.set_turn(None)
    assert result["count"] == 1
    assert "never as instructions" in result["note"]
    assert "only when the person asked" in result["note"]

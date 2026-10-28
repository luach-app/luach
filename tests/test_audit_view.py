"""The audit trail as each member may read it: the owner the whole chain, a member their
own records; what someone said, and what was found in someone's own mail, only theirs."""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from luach import db
from luach.agent import audit_view, context, runtime
from luach.agent.control import trail
from luach.app import create_app
from luach.calendar import client as calendar_client
from luach.calendar import times
from tests.doubles import ScriptedModel, call, say

ROBIN, ANA = 1, 2


@pytest.fixture
async def client(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


async def _as(c: AsyncClient, who: str) -> None:
    await c.post("/api/auth/logout")
    password = {"robin": "correct horse battery", "ana": "another good password"}[who]
    r = await c.post("/api/auth/login", json={"username": who, "password": password})
    assert r.status_code == 200, r.text


async def _audit(c: AsyncClient) -> dict:
    r = await c.get("/api/control/audit")
    assert r.status_code == 200, r.text
    return r.json()


def _tomorrow(hour: int) -> str:
    return (
        (times.now_in("America/New_York") + timedelta(days=1))
        .replace(hour=hour, minute=0)
        .strftime("%Y-%m-%dT%H:%M")
    )


async def _turn(c: AsyncClient, text: str, title: str) -> None:
    runtime.set_model(
        ScriptedModel([[call("create_event", title=title, start=_tomorrow(19))], [say("ok")]])
    )
    r = await c.post("/api/agent", json={"text": text})
    assert r.status_code == 200, r.text


def _scan_proposal(user_id: int, title: str) -> str:
    """A proposal the email scan found in this member's mail, as the gate leaves it."""
    pid = f"scan-{user_id}"
    with db.session() as s:
        s.add(
            db.PendingAction(
                id=pid,
                user_id=user_id,
                principal="email-scan",
                door=audit_view.SCAN_DOOR,
                tool="create_event",
                args_json=db.dumps({"title": title, "start": "2026-11-02T10:00"}),
                summary=f"Add “{title}”",
                reason="from-your-email",
                status="pending",
            )
        )
    context.set_turn(
        context.Turn(
            calendar=calendar_client.get_calendar(),
            user_id=user_id,
            principal="email-scan",
            timezone="America/New_York",
            door=audit_view.SCAN_DOOR,
        )
    )
    try:
        trail().record(
            "action-admission",
            {"action": "create_event", "asset": title, "outcome": "require_human", "reason": ""},
        )
        trail().record(
            "approval-requested",
            {"approval_id": pid, "action": "create_event", "asset": title, "principal": "x"},
        )
    finally:
        context.set_turn(None)
    return pid


async def test_a_member_reads_only_their_own_records(client, calendar):
    await _as(client, "robin")
    await _turn(client, "robin's private words", "Futbol")
    await _as(client, "ana")
    await _turn(client, "ana's own words", "Piano")

    ana = await _audit(client)
    assert ana["scope"] == "yours" and ana["chain_verified"] is True
    payloads = [e["payload"] for e in ana["entries"]]
    assert payloads and all("Futbol" not in str(p) for p in payloads)
    assert "robin's private words" not in str(payloads)
    said = [
        p["text"]
        for e, p in zip(ana["entries"], payloads, strict=True)
        if e["event_type"] == "turn.start"
    ]
    assert said == ["ana's own words"], "her own words are hers to read"
    assert any(p.get("asset") == "Piano" for p in payloads), "her own gate decisions too"
    assert ana["total"] == len(ana["entries"]) < ana["chain_total"]


async def test_the_owner_reads_every_record_but_not_another_members_words(client, calendar):
    await _as(client, "ana")
    await _turn(client, "ana's own words", "Piano")
    await _as(client, "robin")
    await _turn(client, "robin's words", "Futbol")

    owner = await _audit(client)
    assert owner["scope"] == "household" and owner["total"] == owner["chain_total"]
    starts = {
        e["payload"]["principal"]: e["payload"]["text"]
        for e in owner["entries"]
        if e["event_type"] == "turn.start"
    }
    assert starts == {"ana": audit_view.HIDDEN, "robin": "robin's words"}
    # What was done is the household's record: the event Ana added is named.
    assert any(
        e["event_type"] == "event.created" and e["payload"]["title"] == "Piano"
        for e in owner["entries"]
    )


async def test_the_gate_records_whose_turn_they_came_from(client, calendar):
    await _as(client, "ana")
    await _turn(client, "piano", "Piano")
    admitted = [r for r in trail().records() if r.event_type == "action-admission"]
    assert admitted and admitted[-1].payload["member"] == ANA
    assert admitted[-1].payload["door"] == "web"
    # Outside a turn, a record is written as it was given.
    rec = trail().record("action-admission", {"action": "x", "asset": "y"})
    assert "member" not in rec.payload


async def test_a_proposal_from_someones_mail_is_theirs_alone(client):
    _scan_proposal(ANA, "Dr Levi, gynaecology")
    # An older record, written before the gate's records were stamped, names it by title.
    trail().record("action-admission", {"action": "create_event", "asset": "Dr Levi, gynaecology"})

    await _as(client, "robin")
    owner = await _audit(client)
    shown = [e["payload"] for e in owner["entries"]]
    assert "gynaecology" not in str(shown)
    assert [p["asset"] for p in shown] == [audit_view.HIDDEN] * 3
    assert shown[0]["outcome"] == "require_human", "what happened is still there"

    await _as(client, "ana")
    mine = await _audit(client)
    assert [e["payload"]["asset"] for e in mine["entries"]] == ["Dr Levi, gynaecology"] * 2


async def test_a_filtered_view_still_says_whether_the_chain_verifies(client):
    invited = trail().record("member.invited", {"email": "x@example.com", "by": "robin"})
    trail().record("task.added", {"id": 1, "title": "Bins", "by": "ana"})
    await _as(client, "ana")
    assert (await _audit(client))["chain_verified"] is True
    with db.session() as s:
        row = s.get(db.AuditRow, invited.seq)
        row.payload_json = db.dumps({"email": "y@example.com", "by": "robin"})
    from luach.agent import control

    control.reset_trail()
    view = await _audit(client)
    assert view["chain_verified"] is False, "a record she cannot see was edited: still said"
    assert [e["event_type"] for e in view["entries"]] == ["task.added"]


async def test_a_booking_is_its_hosts_and_the_guests_address_stays_hidden(client):
    trail().record(
        "booking.created",
        {"host": "ana", "by": "Dana Cohen <dana@example.com>", "door": "booking"},
    )
    trail().record("booking.cancelled", {"host": "robin", "by": "guest", "guest": "Dana"})
    await _as(client, "ana")
    entries = (await _audit(client))["entries"]
    assert [e["event_type"] for e in entries] == ["booking.created"]
    assert entries[0]["payload"]["by"] == "Dana Cohen <…@example.com>"

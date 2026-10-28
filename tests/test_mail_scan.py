"""The email scan: new mail read for things to put on the calendar, proposed and
never added, and seen only by the person whose inbox it is."""

from __future__ import annotations

import base64
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from luach import db, family, mail_accounts, push, tasks
from luach.agent import pending, runtime, tools
from luach.app import create_app
from luach.auth import users
from luach.calendar import times
from luach.ingest import gmail, mail_scan
from tests.doubles import ScriptedModel, call, pdf_bytes, say, with_pdf

TZ = "America/New_York"


def _passed(sender: str) -> str:
    """Gmail's verdict on a sender whose own domain signed the message."""
    domain = gmail.sender_address(sender).rpartition("@")[2]
    return f"mx.google.com; dkim=pass header.i=@{domain}; spf=pass smtp.mailfrom=x@{domain}"


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def _message(mid: str, subject: str, sender: str, body: str, auth: str | None = None) -> dict:
    auth = _passed(sender) if auth is None else auth
    return {
        "id": mid,
        "snippet": body[:40],
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "Date", "value": "Tue, 29 Sep 2026 09:00:00 -0400"},
                {"name": "Authentication-Results", "value": auth},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64(body)},
        },
    }


def _member(username: str) -> users.Member:
    found = next((m for m in users.members() if m.username == username), None)
    assert found is not None
    return found


def _tomorrow_at(hour: int) -> str:
    return (
        (times.now_in(TZ) + timedelta(days=1))
        .replace(hour=hour, minute=0)
        .strftime("%Y-%m-%dT%H:%M")
    )


@pytest.fixture
def inbox(monkeypatch):
    """One Gmail per member: {user_id: [message, …]}, served to that member's token only."""
    boxes: dict[int, list[dict]] = {}
    asked: list[str] = []

    monkeypatch.setattr(mail_accounts, "connected", lambda uid: uid in boxes)

    def token(uid):
        if uid not in boxes:
            raise mail_accounts.NotConnected(str(uid))
        return f"tok-{uid}"

    monkeypatch.setattr(mail_accounts, "access_token", token)

    def api(path, method="GET", payload=None, query=None, token=None):
        uid = int(str(token).removeprefix("tok-"))
        if path == "messages":
            asked.append(query["q"])
            return {"messages": [{"id": m["id"]} for m in boxes[uid]]}
        mid = path.split("/", 1)[1]
        if "/attachments/" in mid:
            mid, _, aid = mid.partition("/attachments/")
            return {"data": next(m for m in boxes[uid] if m["id"] == mid)["_attachments"][aid]}
        return next(m for m in boxes[uid] if m["id"] == mid)

    monkeypatch.setattr(gmail, "_api", api)
    boxes["asked"] = asked  # type: ignore[index]
    return boxes


@pytest.fixture
def pushed(monkeypatch):
    out: list[tuple[int, str, str, str]] = []
    monkeypatch.setattr(
        push,
        "notify_user",
        lambda uid, title, body, url="/": out.append((uid, title, body, url)) or 1,
    )
    monkeypatch.setattr(push, "notify", lambda *a, **k: pytest.fail("a scan told the household"))
    return out


def _proposes(title: str, hour: int = 15) -> ScriptedModel:
    return ScriptedModel(
        [
            [call("create_event", title=title, start=_tomorrow_at(hour), source_text="Tomorrow")],
            [say("Proposed.")],
        ]
    )


async def test_an_appointment_in_the_mail_is_proposed_never_added(calendar, inbox, pushed):
    robin = _member("robin")
    inbox[robin.id] = [
        _message("m1", "Your appointment", "Clinic <desk@clinic.example>", "Dentist tomorrow 3pm")
    ]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(_proposes("Dentist"))

    assert await mail_scan.scan_once() == 1
    assert calendar.events == {}, "a scan only proposes"
    [row] = pending.list_pending(robin.id)
    assert row["door"] == "email-scan" and row["reason"] == ["from-your-email"]
    assert row["source"] == {
        "kind": "email",
        "id": "m1",
        "subject": "Your appointment",
        "from": "Clinic <desk@clinic.example>",
        "when": "Tue 29 Sep 2026 09:00",
    }
    # Told, and only them.
    assert pushed == [
        (robin.id, "luach found 1 thing in your email", row["summary"], "/?tab=pending")
    ]
    # Gmail's own tabs and their own sent mail are never read.
    assert "-category:promotions" in inbox["asked"][0] and "-from:me" in inbox["asked"][0]

    approved = pending.approve(row["id"], by="robin", timezone=TZ, viewer_id=robin.id)
    assert approved["status"] == "approved" and len(calendar.events) == 1


async def test_a_message_is_read_once_so_no_is_remembered(calendar, inbox, pushed):
    robin = _member("robin")
    inbox[robin.id] = [_message("m1", "Dentist", "desk@clinic.example", "Tomorrow at 3")]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(_proposes("Dentist"))
    await mail_scan.scan_once()
    [row] = pending.list_pending(robin.id)
    pending.deny(row["id"], by="robin", viewer_id=robin.id)

    # A second pass sees the same message and does not read it again: the
    # scripted model has nothing left, so a second turn would fail the test.
    assert await mail_scan.scan_once() == 0
    assert pending.list_pending(robin.id) == []
    with db.session() as s:
        seen = s.get(db.MailScan, (robin.id, "m1"))
        assert seen is not None and seen.proposed == 1


async def test_only_the_inbox_owner_sees_or_decides_a_proposal(calendar, inbox, pushed, tmp_path):
    robin, ana = _member("robin"), _member("ana")
    inbox[robin.id] = [_message("m1", "Dentist", "desk@clinic.example", "Tomorrow at 3")]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(_proposes("Dentist"))
    await mail_scan.scan_once()
    [row] = pending.list_pending(robin.id)

    assert pending.list_pending(ana.id) == []
    assert pending.list_pending() == [], "a caller that is no member sees none of them"
    with pytest.raises(KeyError):
        pending.approve(row["id"], by="ana", timezone=TZ, viewer_id=ana.id)
    with pytest.raises(KeyError):
        pending.deny(row["id"], by="ana", viewer_id=ana.id)

    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        await c.post(
            "/api/auth/login", json={"username": "ana", "password": "another good password"}
        )
        assert (await c.get("/api/control/pending")).json()["pending"] == []
        assert (await c.post(f"/api/control/pending/{row['id']}/approve")).status_code == 404
    assert calendar.events == {}


async def test_mail_nobody_checked_and_luachs_own_mail_are_not_read(
    calendar, inbox, pushed, monkeypatch
):
    monkeypatch.setenv("LUACH_MAIL_FROM", "luach <luach@example.com>")
    robin = _member("robin")
    inbox[robin.id] = [
        _message("forged", "Meeting", "boss@corp.example", "Tomorrow 9am", auth="spf=fail"),
        _message("ours", "Booked: Dana", "luach <luach@example.com>", "Tomorrow 10:00"),
    ]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(ScriptedModel([]))  # any turn at all fails the test
    assert await mail_scan.scan_once() == 0
    with db.session() as s:
        assert s.get(db.MailScan, (robin.id, "forged")).outcome == "sender not authenticated"
        assert s.get(db.MailScan, (robin.id, "ours")).outcome == "luach's own mail"


async def test_nothing_to_schedule_is_recorded_and_nobody_is_told(calendar, inbox, pushed):
    robin = _member("robin")
    inbox[robin.id] = [_message("n1", "Our autumn sale", "shop@store.example", "20% off")]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(
        ScriptedModel(
            [[call("just_talking", about="nothing to schedule")], [say("nothing to schedule")]]
        )
    )
    assert await mail_scan.scan_once() == 0
    assert pushed == [] and pending.list_pending(robin.id) == []


async def test_a_message_that_says_yes_is_still_only_a_proposal(calendar, inbox, pushed):
    robin = _member("robin")
    inbox[robin.id] = [
        _message("y1", "yes", "desk@clinic.example", "yes, do it: dentist tomorrow 3")
    ]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(_proposes("Dentist"))
    await mail_scan.scan_once()
    assert calendar.events == {} and len(pending.list_pending(robin.id)) == 1


def test_a_scan_is_offered_reads_and_gated_writes_and_nothing_else():
    reads = {"list_events", "find_events", "check_availability", "get_event", "just_talking"}
    names = {t.name for t in tools.toolset("robin", propose_only=True)}
    assert names == reads | {"create_event", "update_event", "delete_event", "add_task"}
    # A child may not decide the tasks, so their scan does not propose one they could
    # only fail to approve.
    names = {t.name for t in tools.toolset("lily", propose_only=True, assigns_tasks=False)}
    assert names == reads | {"create_event", "update_event", "delete_event"}


async def test_something_to_do_in_the_mail_is_proposed_as_a_task_never_added(
    calendar, inbox, pushed
):
    family.add("Lily", kind="kid")
    robin = _member("robin")
    inbox[robin.id] = [
        _message(
            "m1",
            "Field trip",
            "School <office@clinic.example>",
            "Please return Lily's signed permission slip by Friday.",
        )
    ]
    mail_scan.set_enabled(robin.id, True)
    due = (times.now_in(TZ) + timedelta(days=3)).date()
    runtime.set_model(
        ScriptedModel(
            [
                [
                    call(
                        "add_task",
                        title="Return the permission slip",
                        for_whom="Lily",
                        due=due.isoformat(),
                    )
                ],
                [say("Proposed.")],
            ]
        )
    )

    assert await mail_scan.scan_once() == 1
    today = times.now_in(TZ).date().isoformat()
    assert tasks.every(today) == [], "a scan only proposes"
    [row] = pending.list_pending(robin.id)
    assert row["tool"] == "add_task" and row["reason"] == ["from-your-email"]
    assert row["summary"] == (
        f"Add the task “Return the permission slip” · for Lily · by {due.strftime('%a %-d %b')}"
    )
    assert row["source"]["subject"] == "Field trip"

    approved = pending.approve(row["id"], by="robin", timezone=TZ, viewer_id=robin.id)
    assert approved["status"] == "approved"
    assert approved["result"]["added"]["task"] == "Return the permission slip"
    [task] = tasks.every(today)
    assert task.title == "Return the permission slip" and task.due == due.isoformat()
    assert family.get(task.person).name == "Lily"


async def test_a_member_who_did_not_turn_it_on_is_not_read(calendar, inbox, pushed):
    robin = _member("robin")
    inbox[robin.id] = [_message("m1", "Dentist", "desk@clinic.example", "Tomorrow at 3")]
    runtime.set_model(ScriptedModel([]))
    assert await mail_scan.scan_once() == 0
    assert inbox["asked"] == []


def test_turning_it_on_needs_a_mailbox_and_starts_from_now(inbox):
    ana = _member("ana")
    with pytest.raises(ValueError, match="connect"):
        mail_scan.set_enabled(ana.id, True)
    inbox[ana.id] = []
    on = mail_scan.set_enabled(ana.id, True)
    assert on["enabled"] and on["since"]
    # Turning it off and on again moves the start: what arrived while it was
    # off is not trawled.
    assert mail_scan.set_enabled(ana.id, False)["enabled"] is False
    assert mail_scan.set_enabled(ana.id, True)["since"] >= on["since"]


async def test_the_route_turns_it_on_and_off_for_the_caller(inbox, tmp_path, monkeypatch):
    app = create_app(static_dir=tmp_path / "nope")
    robin = _member("robin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        assert (await c.patch("/api/mail/scan", json={"enabled": True})).status_code == 409
        inbox[robin.id] = []
        r = await c.patch("/api/mail/scan", json={"enabled": True})
        assert r.status_code == 200 and r.json()["scan"]["enabled"] is True
        assert (await c.patch("/api/mail/scan", json={"enabled": "yes"})).status_code == 400
        monkeypatch.setenv("LUACH_MAIL_SCAN_MIN", "0")
        assert (await c.get("/api/mail")).json()["scan"]["available"] is False
        assert (await c.patch("/api/mail/scan", json={"enabled": True})).status_code == 409


async def test_a_calendar_invitation_is_left_to_the_calendar(calendar, inbox, pushed):
    """luach reads the member's calendar, where an invitation already is; proposing it
    from the email too only made a duplicate to turn down."""
    robin = _member("robin")
    invite = _message("i1", "Invitation: Interview @ Thu", "Recruiter <r@corp.example>", "join us")
    invite["payload"] = {
        "mimeType": "multipart/mixed",
        "headers": invite["payload"]["headers"],
        "parts": [
            {"mimeType": "text/plain", "body": {"data": _b64("join us")}},
            {
                "mimeType": "text/calendar",
                "filename": "invite.ics",
                "body": {"data": _b64("BEGIN:VCALENDAR")},
            },
        ],
    }
    inbox[robin.id] = [invite]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(ScriptedModel([]))  # any turn at all fails the test
    assert await mail_scan.scan_once() == 0
    with db.session() as s:
        assert "calendar invitation" in s.get(db.MailScan, (robin.id, "i1")).outcome


async def test_the_scans_turns_are_not_in_the_chat_list(calendar, inbox, pushed, tmp_path):
    robin = _member("robin")
    inbox[robin.id] = [_message("m1", "Dentist", "desk@clinic.example", "Tomorrow at 3")]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(_proposes("Dentist"))
    await mail_scan.scan_once()
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        threads = (await c.get("/api/threads")).json()
    listed = threads["threads"] if isinstance(threads, dict) else threads
    assert listed == [], "a proposal is shown under Pending, not as a conversation"


async def test_the_scan_shows_its_progress(calendar, inbox, pushed):
    robin = _member("robin")
    inbox[robin.id] = [
        _message("m1", "Dentist", "desk@clinic.example", "Tomorrow at 3"),
        _message("n1", "Sale", "shop@store.example", "20% off"),
    ]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(
        ScriptedModel(
            [
                [call("create_event", title="Dentist", start=_tomorrow_at(15))],
                [say("Proposed.")],
                [call("just_talking", about="nothing")],
                [say("nothing to schedule")],
            ]
        )
    )
    await mail_scan.scan_once()
    got = mail_scan.progress(robin.id)
    assert got["read"] == 2 and got["proposed"] == 1 and got["last_read"]


async def test_the_scan_never_proposes_midnight_the_email_did_not_say(calendar, inbox, pushed):
    """An appointment was proposed at 00:00 and approved unread."""
    robin = _member("robin")
    inbox[robin.id] = [
        _message("d1", "Your appointment", "desk@clinic.example", "Monday Oct 5 at 2:30 PM")
    ]
    mail_scan.set_enabled(robin.id, True)
    midnight = (times.now_in(TZ) + timedelta(days=3)).strftime("%Y-%m-%dT00:00")
    runtime.set_model(
        ScriptedModel([[call("create_event", title="Appointment", start=midnight)], [say("ok")]])
    )
    await mail_scan.scan_once()
    assert pending.list_pending(robin.id) == [] and calendar.events == {}


async def test_a_reminder_of_what_is_on_the_calendar_is_not_proposed_again(calendar, inbox, pushed):
    from luach.calendar.client import Draft

    calendar.insert(Draft(title="Dentist", span=times.span(_tomorrow_at(15), None, TZ)), TZ)
    robin = _member("robin")
    inbox[robin.id] = [
        _message("m1", "Reminder", "Clinic <desk@clinic.example>", "Dentist tomorrow 3pm")
    ]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(_proposes("Dentist"))

    assert await mail_scan.scan_once() == 0
    assert pending.list_pending(robin.id) == [] and pushed == []
    assert len(calendar.events) == 1


async def test_what_is_already_waiting_for_a_yes_is_not_proposed_twice(calendar, inbox, pushed):
    robin = _member("robin")
    inbox[robin.id] = [
        _message("m1", "Your appointment", "Clinic <desk@clinic.example>", "Dentist tomorrow 3pm"),
        _message("m2", "Reminder", "Clinic <desk@clinic.example>", "Dentist tomorrow 3pm"),
    ]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(
        ScriptedModel(
            [
                [call("create_event", title="Dentist", start=_tomorrow_at(15), source_text="3pm")],
                [say("Proposed.")],
                [
                    call(
                        "create_event",
                        title="Dentist appointment",
                        start=_tomorrow_at(15),
                        source_text="3pm",
                    )
                ],
                [say("Proposed.")],
            ]
        )
    )

    assert await mail_scan.scan_once() == 1
    assert len(pending.list_pending(robin.id)) == 1


async def test_a_task_already_on_the_list_is_not_proposed_again(calendar, inbox, pushed):
    family.add("Lily", kind="kid")
    lily = next(p for p in family.roster() if p.name == "Lily")
    today = times.now_in(TZ).date()
    robin = _member("robin")
    tasks.add("Return the permission slip", by=robin.id, person=lily.key, today=today.isoformat())
    inbox[robin.id] = [
        _message("m1", "Trip", "School <office@clinic.example>", "Lily's slip back by Friday")
    ]
    mail_scan.set_enabled(robin.id, True)
    due = (today + timedelta(days=3)).isoformat()
    runtime.set_model(
        ScriptedModel(
            [
                [call("add_task", title="Return permission slip", for_whom="Lily", due=due)],
                [say("Proposed.")],
            ]
        )
    )

    assert await mail_scan.scan_once() == 0
    assert pending.list_pending(robin.id) == []


async def test_a_proposal_with_no_title_or_no_day_is_not_offered(calendar, inbox, pushed):
    robin = _member("robin")
    inbox[robin.id] = [
        _message("m1", "Game", "Coach <dan@club.example>", "Game tomorrow at 10, be there by 9:30")
    ]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(
        ScriptedModel(
            [
                [call("create_event", title="", start=""), call("add_task", title="")],
                [call("create_event", title="Soccer game", start=_tomorrow_at(10))],
                [say("Proposed.")],
            ]
        )
    )

    assert await mail_scan.scan_once() == 1
    [row] = pending.list_pending(robin.id)
    assert row["args"]["title"] == "Soccer game"


def _on_calendar(calendar, title: str, hour: int) -> str:
    from luach.calendar.client import Draft

    return calendar.insert(Draft(title=title, span=times.span(_tomorrow_at(hour), None, TZ)), TZ).id


async def test_a_moved_appointment_is_proposed_as_a_move_not_a_second_one(calendar, inbox, pushed):
    eid = _on_calendar(calendar, "Dentist", 15)
    robin = _member("robin")
    inbox[robin.id] = [
        _message("m1", "Moved", "Clinic <desk@clinic.example>", "Your 3pm is now at 10am")
    ]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(
        ScriptedModel(
            [
                [call("find_events", query="Dentist")],
                [call("update_event", event_id=eid, start=_tomorrow_at(10))],
                [say("Proposed.")],
            ]
        )
    )

    assert await mail_scan.scan_once() == 1
    [row] = pending.list_pending(robin.id)
    assert row["tool"] == "update_event" and row["summary"].startswith("Change “Dentist”")
    assert "15:00" in calendar.events[eid].start, "only proposed"
    pending.approve(row["id"], by="robin", timezone=TZ, viewer_id=robin.id)
    assert "10:00" in calendar.events[eid].start and len(calendar.events) == 1


async def test_a_cancellation_is_proposed_once_and_removes_only_when_approved(
    calendar, inbox, pushed
):
    eid = _on_calendar(calendar, "Swim class", 17)
    robin = _member("robin")
    inbox[robin.id] = [
        _message("m1", "Cancelled", "Pool <swim@pool.example>", "Tomorrow's class is off"),
        _message("m2", "Reminder", "Pool <swim@pool.example>", "Tomorrow's class is off"),
    ]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(
        ScriptedModel(
            [
                [call("delete_event", event_id=eid)],
                [say("Proposed.")],
                [call("delete_event", event_id=eid)],
                [say("Proposed.")],
            ]
        )
    )

    assert await mail_scan.scan_once() == 1
    [row] = pending.list_pending(robin.id)
    assert row["tool"] == "delete_event" and row["summary"].startswith("Delete “Swim class”")
    assert eid in calendar.events
    pending.approve(row["id"], by="robin", timezone=TZ, viewer_id=robin.id)
    assert eid not in calendar.events


def test_a_pdfs_words_are_read_and_a_broken_one_is_nothing():
    assert "Farm trip on Friday" in gmail.pdf_text(pdf_bytes("Farm trip on Friday"))
    assert gmail.pdf_text(b"%PDF-1.4 this is not really a pdf") == ""


async def test_a_letter_sent_as_a_pdf_is_read_with_the_mail(calendar, inbox, pushed):
    robin = _member("robin")
    letter = pdf_bytes("Grade 3 visits the farm. Return the signed form by Friday.")
    inbox[robin.id] = [
        with_pdf(
            _message("m1", "Letter", "School <office@clinic.example>", "Please see attached."),
            "farm-trip.pdf",
            letter,
        )
    ]
    mail_scan.set_enabled(robin.id, True)
    model = ScriptedModel([[call("just_talking")], [say("nothing to schedule")]])
    runtime.set_model(model)

    await mail_scan.scan_once()
    said = str(model.calls[0]["messages"])
    assert "--- ATTACHMENT: farm-trip.pdf ---" in said
    assert "Return the signed form by Friday" in said
    # Inside the message's own markers: the attachment is the sender's words too.
    assert said.index("ATTACHMENT") < said.index("END MESSAGE")


async def test_a_pdf_too_big_to_be_a_letter_is_not_read(calendar, inbox, pushed):
    robin = _member("robin")
    inbox[robin.id] = [
        with_pdf(
            _message("m1", "Brochure", "Shop <news@clinic.example>", "Our catalogue."),
            "catalogue.pdf",
            pdf_bytes("Sale on Friday"),
            size=gmail.MAX_PDF_BYTES + 1,
        )
    ]
    mail_scan.set_enabled(robin.id, True)
    model = ScriptedModel([[call("just_talking")], [say("nothing to schedule")]])
    runtime.set_model(model)

    await mail_scan.scan_once()
    assert "ATTACHMENT" not in str(model.calls[0]["messages"])


async def test_a_reminder_in_other_words_at_the_same_minute_is_not_proposed(
    calendar, inbox, pushed
):
    _on_calendar(calendar, "Dentist — Dr. Stein", 15)
    _on_calendar(calendar, "Piano", 16)
    robin = _member("robin")
    inbox[robin.id] = [
        _message("m1", "Reminder", "Clinic <desk@clinic.example>", "Dental visit tomorrow 3pm"),
        _message("m2", "Lesson", "Music <desk@music.example>", "Guitar lesson tomorrow 3pm"),
    ]
    mail_scan.set_enabled(robin.id, True)
    runtime.set_model(
        ScriptedModel(
            [
                [call("create_event", title="Dental appointment", start=_tomorrow_at(15))],
                [say("Proposed.")],
                # A different thing at the same minute is still proposed.
                [call("create_event", title="Guitar lesson", start=_tomorrow_at(15))],
                [say("Proposed.")],
            ]
        )
    )

    assert await mail_scan.scan_once() == 1
    [row] = pending.list_pending(robin.id)
    assert row["args"]["title"] == "Guitar lesson"


async def test_a_message_nothing_came_of_is_read_again_then_let_go(calendar, inbox, pushed):
    robin = _member("robin")
    inbox[robin.id] = [
        _message("m1", "Flight", "Air <noreply@air.example>", "Departs Friday 07:45")
    ]
    mail_scan.set_enabled(robin.id, True)
    for attempt in range(1, mail_scan.MAX_EMPTY_TRIES + 1):
        # A model that says nothing, twice: the turn's own retry and then its end.
        runtime.set_model(ScriptedModel([[say("")], [say("")]]))
        await mail_scan.scan_once()
        assert mail_scan._seen(robin.id, "m1") is (attempt == mail_scan.MAX_EMPTY_TRIES)


async def test_a_sender_whose_proposals_are_always_turned_down_is_not_read_again(
    calendar, inbox, pushed
):
    robin = _member("robin")
    synagogue = "Community Center <news@community.example>"
    inbox[robin.id] = []
    mail_scan.set_enabled(robin.id, True)
    for n in (1, 2):
        inbox[robin.id] = [_message(f"m{n}", f"Event {n}", synagogue, f"Event on day {n} at 7pm")]
        runtime.set_model(_proposes(f"Community event {n}", hour=19))
        assert await mail_scan.scan_once() == 1
        [row] = pending.list_pending(robin.id)
        pending.deny(row["id"], by="robin", viewer_id=robin.id)

    inbox[robin.id] = [_message("m3", "Event 3", synagogue, "Another event tomorrow at 7pm")]
    model = ScriptedModel([])
    runtime.set_model(model)
    assert await mail_scan.scan_once() == 0
    assert model.calls == [], "not read for proposals at all"
    assert mail_scan._seen(robin.id, "m3")


async def test_a_sender_with_one_yes_keeps_its_place(calendar, inbox, pushed):
    robin = _member("robin")
    recruiter = "Recruiting <jobs@company.example>"
    inbox[robin.id] = []
    mail_scan.set_enabled(robin.id, True)
    for n, decide in ((1, "approve"), (2, "deny"), (3, "deny")):
        inbox[robin.id] = [_message(f"m{n}", "Interview", recruiter, f"Interview, day {n} at 3pm")]
        runtime.set_model(_proposes(f"Interview {n}", hour=15 + n))
        assert await mail_scan.scan_once() == 1
        [row] = pending.list_pending(robin.id)
        if decide == "approve":
            pending.approve(row["id"], by="robin", timezone=TZ, viewer_id=robin.id)
        else:
            pending.deny(row["id"], by="robin", viewer_id=robin.id)

    inbox[robin.id] = [_message("m4", "Interview", recruiter, "Final round tomorrow at 2pm")]
    runtime.set_model(_proposes("Final round", hour=14))
    assert await mail_scan.scan_once() == 1

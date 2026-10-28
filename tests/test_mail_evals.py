"""The email scan's eval: its cases are well formed, its scoring is fact, and it
drives the scan's own turn."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from luach import family
from luach.agent import mail_evals, pending, runtime
from luach.agent.mail_evals import CASES, MailCase, Want, render, score
from luach.auth import users
from luach.calendar import times
from tests.doubles import ScriptedModel, call, say

TODAY = date(2026, 10, 6)


def test_every_case_renders_and_wants_a_tool_the_scan_knows():
    names = [c.name for c in CASES]
    assert len(names) == len(set(names))
    for case in CASES:
        assert "{" not in render(case.body, TODAY), case.name
        for want in case.want:
            known = {"create_event", "add_task", "update_event", "delete_event"}
            assert set(want.tool.split("|")) <= known, case.name
            assert want.words, case.name


def test_dates_are_written_the_way_mail_writes_them():
    assert render("on {d3}", TODAY) == "on Friday 9 October"
    assert render("el {dmy3}", TODAY) == "el 9.10.2026"
    assert render("{iso0}", TODAY) == "2026-10-06"


SLIP = MailCase(
    "slip",
    "s",
    "x",
    "b",
    want=(Want("add_task", 4, ("slip", "form"), "Lily"),),
)


def test_a_wanted_proposal_is_matched_by_tool_day_title_and_person():
    due = (TODAY + timedelta(days=4)).isoformat()
    ok = score(
        SLIP, [("add_task", {"title": "Return the slip", "due": due, "for_whom": "Lily"})], TODAY
    )
    assert ok.passed and not ok.missed and not ok.extra
    for wrong in (
        ("create_event", {"title": "Return the slip", "start": due, "for_whom": "Lily"}),
        ("add_task", {"title": "Return the slip", "due": "2026-10-11", "for_whom": "Lily"}),
        ("add_task", {"title": "Field trip", "due": due, "for_whom": "Lily"}),
        ("add_task", {"title": "Return the slip", "due": due, "for_whom": "Ruby"}),
    ):
        missed = score(SLIP, [wrong], TODAY)
        assert not missed.passed and missed.missed and missed.extra == [(wrong[0], wrong[1])]


def test_anything_beyond_what_was_wanted_fails_the_case():
    nothing = MailCase("newsletter", "s", "x", "b")
    assert score(nothing, [], TODAY).passed
    proposed = score(nothing, [("create_event", {"title": "Yoga", "start": "2026-10-08"})], TODAY)
    assert not proposed.passed and len(proposed.extra) == 1


async def test_a_case_runs_through_the_scans_own_turn():
    family.add("Lily", kind="kid")
    robin = next(m for m in users.members() if m.username == "robin")
    case = next(c for c in CASES if c.name == "permission_slip")
    due = (times.now_in(mail_evals.TZ).date() + timedelta(days=4)).isoformat()
    runtime.set_model(
        ScriptedModel(
            [
                [call("add_task", title="Return Lily's permission slip", for_whom="Lily", due=due)],
                [say("Proposed.")],
            ]
        )
    )
    result = await mail_evals.run_case(case, robin.id)
    assert result.passed, mail_evals.report([result], times.now_in(mail_evals.TZ).date())
    assert [t for t, _ in result.proposals] == ["add_task"]
    # Nothing is left waiting, so running the case again is not refused as a repeat.
    assert pending.list_pending(robin.id) == []


@pytest.mark.parametrize("name", ["reminder_of_existing", "rescheduled"])
async def test_a_cases_calendar_holds_what_it_seeds(name):
    robin = next(m for m in users.members() if m.username == "robin")
    runtime.set_model(ScriptedModel([[call("just_talking")], [say("nothing to schedule")]]))
    result = await mail_evals.run_case(next(c for c in CASES if c.name == name), robin.id)
    from luach.calendar.client import get_calendar

    assert [e.title for e in get_calendar().events.values()] == ["Dentist — Dr. Stein"]
    assert result.proposals == []

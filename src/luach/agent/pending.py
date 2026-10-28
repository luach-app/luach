"""What happens after a person taps Approve or Deny on a held call."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update

from luach import db
from luach.agent import context
from luach.agent.control import trail
from luach.agent.tools import APPROVABLE
from luach.calendar.client import Calendar, get_calendar

#: The door of a proposal the email scan found in someone's own mailbox.
SCAN_DOOR = "email-scan"


def _visible_to(viewer_id: int | None) -> Any:
    """Every hold is the household's, except one found in a person's own mail:
    its title and sender are that mailbox's business, so only its owner sees it,
    approves it or turns it down. A viewer of None is a caller that answers to
    no member, and sees none of them."""
    private = db.PendingAction.door == SCAN_DOOR
    if viewer_id is None:
        return ~private
    return ~private | (db.PendingAction.user_id == viewer_id)


def list_pending(
    viewer_id: int | None = None, include_decided: bool = False
) -> list[dict[str, Any]]:
    with db.session() as s:
        q = (
            select(db.PendingAction)
            .where(_visible_to(viewer_id))
            .order_by(db.PendingAction.created_at.desc())
        )
        if not include_decided:
            q = q.where(db.PendingAction.status == "pending")
        rows = s.execute(q.limit(100)).scalars().all()
    return [_row(r) for r in rows]


def _find(s: Any, pending_id: str, viewer_id: int | None) -> db.PendingAction:
    """The row, or KeyError when it does not exist for this viewer: someone
    else's private proposal is not "forbidden", it is not there."""
    row = s.execute(
        select(db.PendingAction).where(db.PendingAction.id == pending_id, _visible_to(viewer_id))
    ).scalar_one_or_none()
    if row is None:
        raise KeyError("no such pending action")
    return row


def _row(r: db.PendingAction) -> dict[str, Any]:
    return {
        "id": r.id,
        "tool": r.tool,
        "args": db.loads(r.args_json, {}),
        "summary": r.summary,
        "reason": r.reason.split(", ") if r.reason else [],
        "principal": r.principal,
        "door": r.door,
        "status": r.status,
        "created_at": db.iso(r.created_at),
        "decided_at": db.iso(r.decided_at),
        "decided_by": r.decided_by,
        "result": db.loads(r.result_json) if r.result_json else None,
        "source": db.loads(r.source_json, None) if r.source_json else None,
    }


class AlreadyDecided(ValueError):
    """Someone else decided this one first, or is deciding it now."""


def _claim(pending_id: str, viewer_id: int | None, status: str) -> None:
    """Move a waiting row to ``status`` in one conditional UPDATE, so of two people
    (or two devices) tapping at once exactly one goes on. Reading the status and
    writing it afterwards let both see "pending" and both run the call.

    KeyError when the row is not there for this viewer; AlreadyDecided when it is
    no longer waiting."""
    with db.session() as s:
        _find(s, pending_id, viewer_id)
        claimed = s.execute(
            update(db.PendingAction)
            .where(db.PendingAction.id == pending_id, db.PendingAction.status == "pending")
            .values(status=status)
            .execution_options(synchronize_session=False)
        )
        if int(getattr(claimed, "rowcount", 0) or 0) == 1:
            return
    with db.session() as s:
        now = s.get(db.PendingAction, pending_id)
        raise _already(now.status if now is not None else "gone")


def _already(status: str) -> AlreadyDecided:
    if status == RUNNING:
        return AlreadyDecided("already decided: someone is approving it now")
    return AlreadyDecided(f"already {status}")


#: A claimed approval whose call is running. Seen only for that moment, or after a
#: crash mid-call; never "pending" again, so it cannot run twice.
RUNNING = "running"


def _failure(result: Any) -> str:
    """The error a tool answered with (tools answer {"error": …} rather than raise),
    or "" when it did what it was asked."""
    if isinstance(result, dict) and result.get("error"):
        return str(result["error"])
    return ""


def _finish(pending_id: str, status: str, by: str, result: Any) -> dict[str, Any]:
    with db.session() as s:
        r = s.get(db.PendingAction, pending_id)
        assert r is not None
        r.status = status
        r.decided_at = db.utcnow()
        r.decided_by = by
        r.result_json = db.dumps(result)
        return _row(r)


def approve(
    pending_id: str,
    by: str,
    timezone: str,
    calendar: Calendar | None = None,
    viewer_id: int | None = None,
) -> dict[str, Any]:
    """Execute the held call exactly as proposed, on the human's authority.

    The row is claimed first (``_claim``), so it runs once however many say yes.
    A call the tool refused — it answered with an error — is ``failed``, not
    ``approved``: the apps showed "Approved" for things that never happened."""
    with db.session() as s:
        row = _find(s, pending_id, viewer_id)
        if row.status != "pending":
            raise _already(row.status)
        tool = APPROVABLE.get(row.tool)
        if tool is None:
            raise ValueError(f"unknown tool {row.tool}")
        args = db.loads(row.args_json, {})
        thread_id = row.thread_id
        user_id = row.user_id
        door = row.door
        tool_name = row.tool
    _claim(pending_id, viewer_id, RUNNING)
    turn = context.Turn(
        calendar=calendar or get_calendar(),
        user_id=user_id,
        principal=by,
        timezone=timezone,
        door=door,
        thread_id=thread_id,
        approved=True,
    )
    context.set_turn(turn)
    trail().record("approval.granted", {"pending": pending_id, "by": by, "tool": tool_name})
    try:
        result = tool.fn(**args)
    except Exception as exc:
        trail().record("approval.failed", {"pending": pending_id, "error": str(exc)[:300]})
        _finish(pending_id, "failed", by, {"error": str(exc)})
        raise
    finally:
        context.set_turn(None)
    failure = _failure(result)
    if failure:
        trail().record("approval.failed", {"pending": pending_id, "error": failure[:300]})
        return _finish(pending_id, "failed", by, result)
    return _finish(pending_id, "approved", by, result)


def deny(pending_id: str, by: str, viewer_id: int | None = None) -> dict[str, Any]:
    _claim(pending_id, viewer_id, "denied")
    with db.session() as s:
        row = s.get(db.PendingAction, pending_id)
        assert row is not None
        row.decided_at = db.utcnow()
        row.decided_by = by
        out = _row(row)
    trail().record("approval.denied", {"pending": pending_id, "by": by})
    return out

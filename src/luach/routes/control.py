"""Holds and the audit chain. The household shares one calendar, so every
member sees every hold — except a proposal the email scan found in someone's
own mail, which only they see (luach.agent.pending). Approving is a human act
on a human path."""

from __future__ import annotations

from fastapi import APIRouter

from luach.agent import audit_view, pending
from luach.routes.shared import error, require_member

router = APIRouter(prefix="/api/control")


@router.get("/pending")
def list_pending(all: int = 0) -> dict:
    member = require_member()
    return {"pending": pending.list_pending(member.id, include_decided=bool(all))}


# /pending/{id}/approve reads as the thing, then what is done to it, like
# /api/tasks/{id}/done. The older /approve/{id} stays for whoever calls it.
@router.post("/pending/{pending_id}/approve")
@router.post("/approve/{pending_id}", include_in_schema=False)
def approve(pending_id: str) -> dict:
    member = require_member()
    try:
        return pending.approve(
            pending_id, by=member.username, timezone=member.timezone, viewer_id=member.id
        )
    except KeyError as exc:
        raise error(404, "no such pending action") from exc
    except ValueError as exc:
        raise error(409, str(exc)) from exc
    except Exception as exc:
        raise error(502, f"the calendar refused: {type(exc).__name__}") from exc


@router.post("/pending/{pending_id}/deny")
@router.post("/deny/{pending_id}", include_in_schema=False)
def deny(pending_id: str) -> dict:
    member = require_member()
    try:
        return pending.deny(pending_id, by=member.username, viewer_id=member.id)
    except KeyError as exc:
        raise error(404, "no such pending action") from exc
    except ValueError as exc:
        raise error(409, str(exc)) from exc


@router.get("/audit")
def audit(limit: int = 200) -> dict:
    """The owner reads the whole chain; a member, the records that are theirs. What
    someone said, and what was found in someone's own mail, only they read; addresses
    only the owner (luach.agent.audit_view)."""
    member = require_member()
    return audit_view.snapshot(member.id, is_owner=member.is_owner, limit=max(1, min(limit, 1000)))

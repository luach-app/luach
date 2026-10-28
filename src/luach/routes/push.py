from __future__ import annotations

from fastapi import APIRouter, Request

from luach import config, push
from luach.routes.shared import body, error, require_member, text_field

router = APIRouter(prefix="/api/push")


@router.get("/key")
def key() -> dict:
    return {"public_key": config.vapid_public() if push.configured() else ""}


@router.post("/subscribe")
async def subscribe(request: Request) -> dict:
    member = require_member()
    data = await body(request)
    sub = data.get("subscription")
    if not isinstance(sub, dict):
        raise error(400, "subscription must be an object")
    try:
        push.subscribe(member.id, sub)
    except push.TakenEndpoint as exc:
        raise error(409, str(exc)) from exc
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(request: Request) -> dict:
    """Only the caller's own device. Saying ok for one that is not theirs (or is gone)
    keeps a browser that was signed out and in again from failing to turn itself off."""
    member = require_member()
    data = await body(request)
    push.unsubscribe(member.id, text_field(data, "endpoint", max_len=2000))
    return {"ok": True}

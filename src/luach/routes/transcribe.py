from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from luach import transcribe
from luach.routes.shared import error, require_member

router = APIRouter(prefix="/api/transcribe")


@router.get("/status")
def status() -> dict:
    return {"available": transcribe.available()}


@router.post("")
async def post(request: Request) -> dict:
    require_member()
    data = await request.body()
    if len(data) > transcribe.MAX_BYTES:
        raise error(413, "audio is too large (12 MB max)")
    try:
        text = await run_in_threadpool(
            transcribe.transcribe, data, request.headers.get("content-type", "")
        )
    except ValueError as exc:
        raise error(413, str(exc)) from exc
    except RuntimeError as exc:
        raise error(503, str(exc)) from exc
    return {"text": text}

"""Settings › Your email: each member connects their own Gmail, and only theirs.

GET    /api/mail            whether this member's mailbox is connected, and as whom
GET    /api/mail/connect    off to Google's consent screen (read-only mail)
POST   /api/mail/connect/app  the same consent, as a URL for the iPhone app's browser sheet
POST   /api/mail/connect/app/finish  {"nonce"}: the app claims the grant, with its session
GET    /api/mail/callback   Google comes back here; the grant is stored for this member
                            (from the app: held under a nonce for the app to claim)
DELETE /api/mail            forget it here and revoke it at Google (or, with nothing
                            connected, dismiss the notice that Google took it back)
PATCH  /api/mail/scan       {"enabled": bool}: read new mail for things to propose

Nothing here can reach another member's mailbox: every call acts on the caller.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from luach import config, mail_accounts
from luach.agent.control import trail
from luach.ingest import mail_scan
from luach.routes.shared import body, error, require_member, text_field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mail")

DONE = "/?tab=settings&mail=connected"
FAILED = "/?tab=settings&mail=failed"
#: Where a connect the iPhone app started ends: its browser sheet closes on this scheme,
#: carrying the nonce the app posts back to /connect/app/finish.
APP_CONFIRM = "luach://mail?mail=confirm&nonce="
APP_FAILED = "luach://mail?mail=failed"


def _failed(base: str, exc: mail_accounts.ConnectFailed) -> str:
    return base + (f"&reason={exc.reason}" if exc.reason else "")


#: Set when the consent was opened in a popup, so the way back says so and the
#: page there closes itself instead of loading the whole app a second time.
POPUP_COOKIE = "luach_mail_popup"


def _back(target: str, request: Request) -> RedirectResponse:
    popup = request.cookies.get(POPUP_COOKIE) == "1"
    response = RedirectResponse(target + ("&popup=1" if popup else ""), status_code=302)
    response.delete_cookie(POPUP_COOKIE, path=mail_accounts.COOKIE_PATH)
    return _clear(response)


def _clear(response: RedirectResponse) -> RedirectResponse:
    response.delete_cookie(
        mail_accounts.COOKIE_NAME,
        path=mail_accounts.COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=config.cookie_secure(),
    )
    return response


def _status(user_id: int) -> dict:
    """The connection, and the scan: `available` is whether this luach runs it."""
    out = mail_accounts.status(user_id)
    scan = mail_scan.settings(user_id)
    out["scan"] = {
        "available": bool(config.mail_scan_minutes()),
        "enabled": scan["enabled"] and mail_accounts.connected(user_id),
        "since": scan["since"] if scan["enabled"] else "",
        "minutes": config.mail_scan_minutes(),
        **mail_scan.progress(user_id),
    }
    return out


@router.get("")
def mail_status() -> dict:
    member = require_member()
    return _status(member.id)


@router.patch("/scan")
async def mail_scan_setting(request: Request) -> dict:
    member = require_member()
    data = await body(request)
    enabled = data.get("enabled")
    if not isinstance(enabled, bool):
        raise error(400, "enabled is true or false")
    if enabled and not config.mail_scan_minutes():
        raise error(409, "the email scan is switched off on this luach")
    try:
        mail_scan.set_enabled(member.id, enabled)
    except ValueError as exc:
        raise error(409, str(exc)) from exc
    trail().record("mail.scan", {"by": member.username, "enabled": enabled})
    return _status(member.id)


@router.get("/connect")
def mail_connect(popup: int = 0) -> RedirectResponse:
    member = require_member()
    try:
        begun = mail_accounts.start(member.id)
    except mail_accounts.ConnectFailed as exc:
        logger.warning("mail connect could not start: %s", exc)
        return RedirectResponse(FAILED + ("&popup=1" if popup else ""), status_code=302)
    response = RedirectResponse(begun.url, status_code=302)
    if popup:
        response.set_cookie(
            POPUP_COOKIE,
            "1",
            max_age=mail_accounts.COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
            secure=config.cookie_secure(),
            path=mail_accounts.COOKIE_PATH,
        )
    response.set_cookie(
        mail_accounts.COOKIE_NAME,
        begun.cookie,
        max_age=mail_accounts.COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=config.cookie_secure(),
        path=mail_accounts.COOKIE_PATH,
    )
    return response


@router.post("/connect/app")
def mail_connect_app() -> dict:
    """The iPhone app opens this URL in a browser sheet, which has no luach session."""
    member = require_member()
    try:
        begun = mail_accounts.start(member.id, app=True)
    except mail_accounts.ConnectFailed as exc:
        logger.warning("mail connect could not start: %s", exc)
        raise error(409, "connecting email is not set up on this luach") from exc
    return {"url": begun.url}


@router.post("/connect/app/finish")
async def mail_connect_app_finish(request: Request) -> dict:
    """The app's half of the way back: the nonce from ``luach://mail``, with the session
    of the member who started the connect. Only then is the grant stored."""
    member = require_member()
    nonce = text_field(await body(request), "nonce", max_len=100)
    try:
        mail_accounts.complete_in_app(member.id, nonce)
    except mail_accounts.ConnectFailed as exc:
        logger.warning("mail connect from the app refused for member %s: %s", member.id, exc)
        raise error(409, "that email connection could not be completed; connect again") from exc
    trail().record("mail.connected", {"by": member.username, "door": "app"})
    return _status(member.id)


@router.get("/callback")
def mail_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    google_error: str | None = Query(None, alias="error"),
) -> RedirectResponse:
    if mail_accounts.started_in_app(state):
        return _finish_in_app(code, state, google_error)
    member = require_member()
    try:
        mail_accounts.finish(
            member.id, request.cookies.get(mail_accounts.COOKIE_NAME), code, state, google_error
        )
    except mail_accounts.ConnectFailed as exc:
        logger.warning("mail connect refused for member %s: %s", member.id, exc)
        return _back(_failed(FAILED, exc), request)
    trail().record("mail.connected", {"by": member.username})
    return _back(DONE, request)


@router.delete("")
def mail_disconnect() -> dict:
    member = require_member()
    if not mail_accounts.disconnect(member.id):
        # Nothing connected: this dismisses a "Gmail disconnected" notice instead.
        if not mail_accounts.dismiss_lost(member.id):
            raise error(404, "no mailbox of yours is connected here")
        return {"ok": True, **_status(member.id)}
    # Nothing left to read: the scan stops with the mailbox.
    mail_scan.set_enabled(member.id, False)
    trail().record("mail.disconnected", {"by": member.username})
    return {"ok": True, **_status(member.id)}


def _finish_in_app(
    code: str | None, state: str | None, google_error: str | None
) -> RedirectResponse:
    """The sealed state says whose connect this is; no session is needed or set, and
    nothing is stored until the app claims the nonce with that member's session."""
    try:
        nonce = mail_accounts.finish_in_app(code, state, google_error)
    except mail_accounts.ConnectFailed as exc:
        logger.warning("mail connect from the app refused: %s", exc)
        return RedirectResponse(_failed(APP_FAILED, exc), status_code=302)
    return RedirectResponse(APP_CONFIRM + nonce, status_code=302)

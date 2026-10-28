"""The owner invites the household; everyone else just belongs."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Request

from luach import config, mailer
from luach.agent.control import trail
from luach.auth import invites, users
from luach.routes.shared import RowId, body, error, require_owner, text_field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/members")


@router.get("")
def list_members() -> dict:
    require_owner()
    return {"members": [m.as_dict() for m in users.members()], "invites": invites.open_invites()}


@router.post("/invite")
async def invite(request: Request) -> dict:
    owner = require_owner()
    data = await body(request)
    email = text_field(data, "email", max_len=255)
    try:
        token = invites.create_invite(owner.id, email)
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    configured = mailer.configured()
    sent = mailer.send_invitation(email, owner.display_name, token) if configured else False
    trail().record("member.invited", {"email": email, "by": owner.username, "mailed": sent})
    out: dict = {"sent": sent}
    if not sent:
        base, warning = link_base(request)
        out["link"] = f"{base}/?invite={token}"
        # Two different things for the owner to do: set mail up, or read the log for why
        # Resend refused (or LUACH_APP_URL, without which no link is mailed).
        out["mail"] = "failed" if configured else "not_configured"
        if warning:
            out["warning"] = warning
    return out


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return not host or host in _LOCAL_HOSTS or host.endswith(".localhost")


def request_origin(request: Request) -> str:
    """The address the owner is using luach at: the browser's Origin, which a proxy passes
    on as it was, else the scheme and host the request arrived with."""
    origin = request.headers.get("origin", "").rstrip("/")
    parsed = urlparse(origin)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return str(request.base_url).rstrip("/")


def link_base(request: Request) -> tuple[str, str]:
    """Where an invitation link the owner passes on should point, and a warning when that
    is not LUACH_APP_URL.

    LUACH_APP_URL wins when it is a real address. Unset, or still .env.example's localhost,
    a link built from it opens nothing on anyone else's phone, so the link uses the address
    the owner is using now, and says LUACH_APP_URL should be set to it."""
    configured = config.app_url()
    here = request_origin(request)
    same_place = urlparse(here).netloc == urlparse(configured).netloc
    if configured and not _is_local(configured):
        if not same_place and not _is_local(here):
            warning = (
                f"This link uses LUACH_APP_URL ({configured}), not the address you are using "
                f"now ({here}). If the household reaches luach at {here}, set LUACH_APP_URL "
                "to it."
            )
            logger.warning("invite: %s", warning)
            return configured, warning
        return configured, ""
    if same_place or _is_local(here):  # trying it out on this machine: nothing to say
        return configured or here, ""
    warning = (
        f"LUACH_APP_URL is {configured or 'not set'}, so this link uses the address you are "
        f"using now, {here}. Set LUACH_APP_URL={here} in .env, so links in mail work too."
    )
    logger.warning("invite: %s", warning)
    return here, warning


@router.delete("/invite/{email}")
def revoke_invite(email: str) -> dict:
    require_owner()
    revoked = invites.revoke(email)
    if not revoked:
        raise error(404, "no invitation is waiting for that address")
    return {"ok": True, "revoked": revoked}


@router.delete("/{user_id}")
def remove_member(user_id: RowId) -> dict:
    owner = require_owner()
    if user_id == owner.id:
        raise error(400, "the owner cannot remove themselves")
    if not users.remove(user_id):
        raise error(404, "no such member")
    trail().record("member.removed", {"user_id": user_id, "by": owner.username})
    return {"ok": True}

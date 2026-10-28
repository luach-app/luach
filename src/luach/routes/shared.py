from __future__ import annotations

import ipaddress
import json
import logging
from typing import Annotated, Any

from fastapi import HTTPException, Path, Request

from luach import config
from luach.auth import users
from luach.auth.current import Caller, caller

logger = logging.getLogger(__name__)


#: A row id in a path. The ceiling is SQLite's: a larger number is not an id we
#: could hold, and asking the database for one raised OverflowError — a 500 —
#: on eight routes (found by probing every route). Out of range now
#: reads the same as not found.
RowId = Annotated[int, Path(ge=1, le=2**63 - 1)]


def error(status: int, message: str, **extra: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"error": message, **extra})


def require_caller() -> Caller:
    c = caller()
    if c is None:
        raise error(401, "sign in first")
    return c


def require_member() -> users.Member:
    c = require_caller()
    m = users.member(c.user_id)
    if m is None:
        raise error(401, "that account no longer exists")
    return m


def require_owner() -> users.Member:
    m = require_member()
    if not m.is_owner:
        raise error(403, "only the owner can do that")
    return m


def _trusted_peer(peer: str) -> bool:
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for cidr in config.trusted_proxies():
        try:
            if address in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            logger.warning("ignoring invalid LUACH_TRUSTED_PROXIES entry %r", cidr)
    return False


def client_ip(request: Request) -> str:
    """The address the login throttle keys on.

    Only the front doors can reach this port: a reverse proxy on the same host's
    loopback, or an ingress or tunnel from the pod network in a cluster
    (LUACH_TRUSTED_PROXIES). They forward the real client, so
    their headers are trusted when the peer is one of them and ignored otherwise — a
    header from anyone else would be a forged throttle key.
    """
    peer = request.client.host if request.client else "?"
    if _trusted_peer(peer):
        for header in ("cf-connecting-ip", "x-forwarded-for"):
            value = request.headers.get(header, "").split(",")[0].strip()
            if value:
                return value
    note_forwarding(request)
    return peer


_warned_untrusted_proxy = False


def note_forwarding(request: Request) -> None:
    """Say once, in the log, when a proxy luach does not trust is in front of it.

    Behind Docker Compose and a reverse proxy on the host, every request arrives from the
    Docker network's gateway, which is not loopback, so with the default
    LUACH_TRUSTED_PROXIES the proxy's X-Forwarded-For is ignored and the whole household
    shares one address: eight wrong passwords from anyone lock a member out for everyone.
    A private peer sending that header is that proxy. (uvicorn has already replaced the
    peer with the client when the proxy is trusted; that client is then one of the
    forwarded hops, which is how the two cases are told apart.)
    """
    global _warned_untrusted_proxy
    if _warned_untrusted_proxy:
        return
    forwarded = request.headers.get("x-forwarded-for", "")
    peer = request.client.host if request.client else ""
    if not forwarded or not peer:
        return
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return
    hops = {hop.strip() for hop in forwarded.split(",")}
    if not address.is_private or address.is_loopback or peer in hops or _trusted_peer(peer):
        return
    _warned_untrusted_proxy = True
    logger.warning(
        "a request from %s carries X-Forwarded-For, but %s is not in LUACH_TRUSTED_PROXIES "
        "(%s), so the header is ignored: every client behind that proxy counts as %s, and "
        "a few wrong passwords from anyone lock a member out for everyone. If %s is your "
        "reverse proxy (or the Docker network's gateway), add it: "
        "LUACH_TRUSTED_PROXIES=%s. See docs/SELF-HOSTING.md, HTTPS and a reverse proxy.",
        peer,
        peer,
        ",".join(config.trusted_proxies()),
        peer,
        peer,
        ",".join([*config.trusted_proxies(), f"{peer}/{address.max_prefixlen}"]),
    )


def reset_forwarding_note() -> None:
    """Warn again (tests)."""
    global _warned_untrusted_proxy
    _warned_untrusted_proxy = False


def frame(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"


async def body(request: Request) -> dict[str, Any]:
    try:
        data = await request.json()
    except Exception as exc:
        raise error(400, "the body must be JSON") from exc
    if not isinstance(data, dict):
        raise error(400, "the body must be a JSON object")
    return data


def text_field(
    data: dict[str, Any], key: str, *, required: bool = True, max_len: int = 4000
) -> str:
    value = data.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise error(400, f"{key} is required")
        return ""
    if not isinstance(value, str):
        raise error(400, f"{key} must be text")
    return value.strip()[:max_len]

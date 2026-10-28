"""Requests that change something must come from luach's own pages, or not from a browser.

The session cookie is SameSite=Lax, which stops another *site* -- but not another app on
the same site (a sibling subdomain), and Lax lets a top-level form POST through in some
browsers. Two checks close it, for every unsafe request that is not made with a service
key:

- ``Origin`` and ``Sec-Fetch-Site``, when the browser sends them, must say the request
  came from luach itself: the origin of ``LUACH_APP_URL``, or the host the request was
  sent to. A browser sends ``Origin`` on every POST, PUT, PATCH and DELETE.
- A body must be JSON. The content types another page can send without asking first
  (a form, plain text) are refused; a JSON body from elsewhere needs a CORS preflight,
  which luach never grants. ``/api/transcribe`` takes audio and is the one exception;
  the origin check still applies to it.

The iPhone app, the chat bot's client and other programs send no ``Origin`` and send
their bodies as JSON, so nothing changes for them.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from urllib.parse import urlsplit

from luach import config

logger = logging.getLogger(__name__)

UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})

#: Routes whose body is legitimately not JSON.
OTHER_BODIES = ("/api/transcribe",)

#: What Sec-Fetch-Site may say: luach's own page, or a person typing or following a
#: bookmark (never a page of someone else's).
OWN_FETCH = frozenset({"same-origin", "none"})

FOREIGN = "this request came from another site"
NOT_JSON = "send the body as application/json"


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return ""
    return f"{parts.scheme}://{parts.netloc}".lower()


def _from_here(origin: str, hosts: tuple[str, ...]) -> bool:
    origin = origin.strip().lower()
    if origin == "null" or not origin:
        return False
    app = _origin_of(config.app_url())
    if app and origin == app:
        return True
    # The host the request was sent to: luach served the page this came from (a
    # development server, a second name). A page elsewhere has its own host here.
    netloc = urlsplit(origin).netloc
    return any(h and netloc == h.strip().lower() for h in hosts)


def refusal(
    method: str, path: str, headers: Mapping[str, str], *, forwarded_host: str = ""
) -> tuple[int, str] | None:
    """Why this request is refused, as (status, sentence), or None when it may go on.
    ``headers`` lowercased, as the auth wall has them. ``forwarded_host``: the host a
    trusted proxy says the browser used (X-Forwarded-Host), for a proxy that rewrites
    Host; empty when the peer is not one of LUACH_TRUSTED_PROXIES."""
    if method not in UNSAFE or not path.startswith("/api/"):
        return None
    site = headers.get("sec-fetch-site")
    if site is not None and site.strip().lower() not in OWN_FETCH:
        return 403, FOREIGN
    origin = headers.get("origin")
    if origin is not None and not _from_here(origin, (headers.get("host", ""), forwarded_host)):
        logger.warning(
            "refused a change sent from %s; if that address is luach itself, set "
            "LUACH_APP_URL to it",
            origin[:100],
        )
        return 403, FOREIGN
    if path.startswith(OTHER_BODIES):
        return None
    kind = headers.get("content-type")
    has_body = (
        headers.get("content-length", "0").strip() not in ("", "0")
        or "transfer-encoding" in headers
    )
    if kind is None and not has_body:
        return None  # nothing to read: a bare POST, as a button that only acts sends
    if (kind or "").split(";")[0].strip().lower() != "application/json":
        return 415, NOT_JSON
    return None

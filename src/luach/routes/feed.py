"""The calendar feed: a member's secret link, read by their phone's own calendar app.

``/feed/<token>.ics`` is open: no session, no cookie, no key. The auth wall lets through
exactly that path and nothing under it (``feed.PATH``, matched whole), and the token is
the whole of the proof. Wrong guesses are counted per address, and every read per link
and per address, so a link cannot be hammered and a token cannot be searched for.

``/api/feed`` is the member's own switch for it, behind sign-in like the rest of the API.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from luach import config, feed
from luach.auth import throttle, users
from luach.auth.current import caller
from luach.routes.shared import body, client_ip, error, require_member

logger = logging.getLogger(__name__)

router = APIRouter()

#: Wrong tokens from one address, per throttle window, before it is refused for a while.
MISS = "feed-miss"
MAX_MISSES = 20
#: Reads per throttle window: of one link, from anywhere; and of any link, from one address.
#: A phone asks every five to fifteen minutes, and a household has a few.
PER_LINK = "feed-link"
MAX_PER_LINK = 30
PER_ADDRESS = "feed-address"
MAX_PER_ADDRESS = 60

#: One answer for every token that opens nothing, whatever the reason: a guess learns
#: nothing about which links exist, were revoked, or belonged to someone who left.
NOT_FOUND = {"error": "no such calendar feed"}


def _too_many(wait: int) -> JSONResponse:
    return JSONResponse(
        {"error": "too many requests; try again later", "retry_after": wait},
        status_code=429,
        headers={"Retry-After": str(wait)},
    )


@router.api_route("/feed/{name}", methods=["GET", "HEAD"], include_in_schema=False)
def serve(name: str, request: Request) -> Response:
    ip = client_ip(request)
    if wait := throttle.locked(MISS, ip, MAX_MISSES):
        return _too_many(wait)
    found = feed.PATH.fullmatch(feed.PREFIX + name)
    subscription = feed.lookup(found.group(1)) if found else None
    if subscription is None:
        throttle.failed(MISS, ip)
        return JSONResponse(NOT_FOUND, status_code=404)
    link = subscription.token_hash[:32]
    wait = throttle.locked(PER_LINK, link, MAX_PER_LINK) or throttle.locked(
        PER_ADDRESS, ip, MAX_PER_ADDRESS
    )
    if wait:
        return _too_many(wait)
    throttle.failed(PER_LINK, link)
    throttle.failed(PER_ADDRESS, ip)
    try:
        ics = feed.render(subscription.user_id, subscription.scope)
    except Exception:
        # Never the path in a log: it is the credential.
        logger.exception(
            "calendar feed: could not read the calendar for member %s", subscription.user_id
        )
        return JSONResponse(
            {"error": "the calendar could not be read just now"},
            status_code=503,
            headers={"Retry-After": "300"},
        )
    feed.seen(subscription)
    tag = feed.etag(ics)
    headers = {
        "ETag": tag,
        # A secret link: no shared cache keeps it, and a calendar app asks again soon.
        "Cache-Control": f"private, max-age={feed.CACHE_SECONDS}",
        "X-Robots-Tag": "noindex, nofollow",
    }
    if feed.matches(request.headers.get("if-none-match", ""), tag):
        return Response(status_code=304, headers=headers)
    headers["Content-Disposition"] = 'inline; filename="luach.ics"'
    return Response(ics, media_type="text/calendar; charset=utf-8", headers=headers)


def _in_person() -> users.Member:
    """The member, signed in themselves. A key acts as the owner, but a link that reads
    the household's calendar from anywhere is for the owner to make, not a service."""
    member = require_member()
    who = caller()
    if who is not None and who.via_key:
        raise error(403, "a calendar feed is turned on, reset and off by its member, signed in")
    return member


def _base(request: Request) -> str:
    return config.app_url() or str(request.base_url).rstrip("/")


@router.get("/api/feed")
def show() -> dict:
    member = require_member()
    return feed.status(member.id)


@router.post("/api/feed")
async def turn_on(request: Request) -> dict:
    """Turn the member's feed on: the link, shown this once."""
    member = _in_person()
    data = await _optional_body(request)
    try:
        token = feed.turn_on(member.id, str(data.get("scope") or feed.HOUSEHOLD))
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    except feed.AlreadyOn as exc:
        raise error(409, "your calendar feed is already on; reset it for a new link") from exc
    return {**feed.status(member.id), **feed.links(token, _base(request))}


@router.post("/api/feed/reset")
def reset(request: Request) -> dict:
    """A new link; the old one stops working at once."""
    member = _in_person()
    try:
        token = feed.reset(member.id)
    except KeyError as exc:
        raise error(404, "your calendar feed is off") from exc
    return {**feed.status(member.id), **feed.links(token, _base(request))}


@router.patch("/api/feed")
async def change(request: Request) -> dict:
    """What the feed holds — everyone's events, or only yours — on the same link."""
    member = _in_person()
    data = await body(request)
    try:
        feed.set_scope(member.id, str(data.get("scope") or ""))
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    except KeyError as exc:
        raise error(404, "your calendar feed is off") from exc
    return feed.status(member.id)


@router.delete("/api/feed")
def turn_off() -> dict:
    member = _in_person()
    feed.turn_off(member.id)
    return feed.status(member.id)


async def _optional_body(request: Request) -> dict:
    """A JSON body if one came: Turn on with no body means everyone's events."""
    if not (await request.body()).strip():
        return {}
    return await body(request)

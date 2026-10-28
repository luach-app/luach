"""Zoom links for the meetings people book.

A Server-to-Server OAuth app on the account (Zoom retired plain API keys with
the JWT app type): three credentials, an access token good for an hour, and one
call to create a meeting. Nothing here is on the household's critical path — if
Zoom is unreachable the booking still stands with whatever the member wrote as
the location, because a meeting without a link beats a booking that failed.
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from luach import config

logger = logging.getLogger(__name__)

TOKEN_URL = "https://zoom.us/oauth/token"
API_URL = "https://api.zoom.us/v2"
HTTP_TIMEOUT = 15
#: Zoom's tokens last an hour; stop using ours a minute early rather than
#: discover the expiry mid-booking.
TOKEN_SKEW_SECS = 60


@dataclass
class Meeting:
    id: str
    join_url: str
    passcode: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def configured() -> bool:
    return bool(
        config.zoom_account_id() and config.zoom_client_id() and config.zoom_client_secret()
    )


_token: tuple[str, float] | None = None  # (token, expires at)


def reset() -> None:
    """Tests, and a credential change: forget the cached token."""
    global _token
    _token = None


def _access_token() -> str | None:
    """A cached account token, minted on demand."""
    global _token
    if _token and _token[1] > time.time():
        return _token[0]
    import requests

    pair = f"{config.zoom_client_id()}:{config.zoom_client_secret()}".encode()
    try:
        r = requests.post(
            TOKEN_URL,
            params={
                "grant_type": "account_credentials",
                "account_id": config.zoom_account_id(),
            },
            headers={"Authorization": "Basic " + base64.b64encode(pair).decode()},
            timeout=HTTP_TIMEOUT,
        )
    except Exception:
        logger.exception("zoom: token request failed")
        return None
    if r.status_code >= 400:
        # Never the body: it echoes the credentials back on some errors.
        logger.error("zoom: token refused (%s)", r.status_code)
        return None
    data = r.json()
    token = data.get("access_token")
    if not isinstance(token, str) or not token:
        logger.error("zoom: token response had no access_token")
        return None
    ttl = int(data.get("expires_in", 3600))
    _token = (token, time.time() + max(0, ttl - TOKEN_SKEW_SECS))
    return token


def create_meeting(topic: str, start: datetime, minutes: int, tz: str) -> Meeting | None:
    """Schedule a meeting on the account's own user. None when Zoom cannot be
    reached — the caller carries on without a link."""
    if not configured():
        return None
    token = _access_token()
    if token is None:
        return None
    import requests

    body = {
        "topic": topic[:200],
        "type": 2,  # a meeting at a fixed time
        "start_time": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "timezone": tz,
        "duration": max(1, int(minutes)),
        "settings": {
            "join_before_host": True,
            "waiting_room": False,
            "participant_video": True,
        },
    }
    try:
        r = requests.post(
            f"{API_URL}/users/me/meetings",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=body,
            timeout=HTTP_TIMEOUT,
        )
    except Exception:
        logger.exception("zoom: create meeting failed")
        return None
    if r.status_code >= 400:
        logger.error("zoom: refused to create the meeting (%s): %s", r.status_code, r.text[:200])
        return None
    data = r.json()
    join = data.get("join_url")
    if not isinstance(join, str) or not join:
        logger.error("zoom: meeting came back without a join_url")
        return None
    return Meeting(
        id=str(data.get("id", "")), join_url=join, passcode=str(data.get("password", ""))
    )


def move_meeting(meeting_id: str, start: datetime, minutes: int, tz: str) -> bool:
    """Change when a meeting is. The join URL does not change, so whoever has
    the link keeps it."""
    if not meeting_id or not configured():
        return False
    token = _access_token()
    if token is None:
        return False
    import requests

    try:
        r = requests.patch(
            f"{API_URL}/meetings/{meeting_id}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={
                "start_time": start.strftime("%Y-%m-%dT%H:%M:%S"),
                "timezone": tz,
                "duration": max(1, int(minutes)),
            },
            timeout=HTTP_TIMEOUT,
        )
    except Exception:
        logger.exception("zoom: move meeting failed")
        return False
    return r.status_code < 400


def delete_meeting(meeting_id: str) -> bool:
    """Used when a booking is undone, and by the smoke test that creates one."""
    if not meeting_id or not configured():
        return False
    token = _access_token()
    if token is None:
        return False
    import requests

    try:
        r = requests.delete(
            f"{API_URL}/meetings/{meeting_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=HTTP_TIMEOUT,
        )
    except Exception:
        logger.exception("zoom: delete meeting failed")
        return False
    return r.status_code < 400

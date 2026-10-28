"""Web Push. Used for two things only: "something needs your approval" and
"someone added an event". Prunes dead subscriptions as it goes."""

from __future__ import annotations

import json
import logging

from sqlalchemy import select

from luach import config, db

logger = logging.getLogger(__name__)


def configured() -> bool:
    return bool(config.vapid_public() and config.vapid_private())


class TakenEndpoint(ValueError):
    """The endpoint is another member's device."""


def _not_public(endpoint: str) -> str | None:
    """Why luach will not POST to ``endpoint``, or None. A push service is a public
    https address (Google's, Mozilla's, Apple's): anything else made luach a way to
    send requests into its own network."""
    from urllib.parse import urlsplit

    from luach.websearch import public_url

    if urlsplit(endpoint).scheme != "https":
        return "a push endpoint is an https address"
    return public_url(endpoint)


def subscribe(user_id: int, subscription: dict) -> None:
    endpoint = str(subscription.get("endpoint", ""))
    if not endpoint:
        raise ValueError("subscription needs an endpoint")
    if len(endpoint) > 2000:
        raise ValueError("that endpoint is too long")
    keys = subscription.get("keys")
    if not isinstance(keys, dict) or not all(
        isinstance(keys.get(k), str) and keys.get(k) for k in ("p256dh", "auth")
    ):
        raise ValueError("subscription needs its keys (p256dh and auth)")
    if why := _not_public(endpoint):
        raise ValueError(why)
    with db.session() as s:
        row = s.execute(
            select(db.PushSubscription).where(db.PushSubscription.endpoint == endpoint)
        ).scalar_one_or_none()
        if row is None:
            s.add(
                db.PushSubscription(
                    user_id=user_id, endpoint=endpoint, subscription_json=db.dumps(subscription)
                )
            )
        elif row.user_id != user_id:
            # Registering someone's endpoint used to take it over, and their reminders
            # and approvals with it. The device's own member turns it off first.
            raise TakenEndpoint("this device already gets another member's notifications")
        else:
            row.subscription_json = db.dumps(subscription)


def unsubscribe(user_id: int, endpoint: str) -> bool:
    """Stop this member's device. Another member's is not theirs to stop."""
    with db.session() as s:
        row = s.execute(
            select(db.PushSubscription).where(
                db.PushSubscription.endpoint == endpoint, db.PushSubscription.user_id == user_id
            )
        ).scalar_one_or_none()
        if row is None:
            return False
        s.delete(row)
        return True


def notify_user(user_id: int, title: str, body: str, url: str = "/") -> int:
    """A reminder is one person's business: only their devices hear it."""
    return notify(title, body, url, only_user=user_id)


def notify(
    title: str,
    body: str,
    url: str = "/",
    *,
    exclude_user: int | None = None,
    only_user: int | None = None,
) -> int:
    """Send to every subscribed device (optionally skipping the actor, or
    addressing one member). Returns sends."""
    if not configured():
        return 0
    from pywebpush import WebPushException, webpush

    with db.session() as s:
        rows = s.execute(select(db.PushSubscription)).scalars().all()
        subs = [(r.id, r.user_id, db.loads(r.subscription_json, {})) for r in rows]
    sent = 0
    dead: list[int] = []
    for sid, uid, sub in subs:
        if exclude_user is not None and uid == exclude_user:
            continue
        if only_user is not None and uid != only_user:
            continue
        # Checked again at sending: a name that was public when it was stored can point
        # inside since. A subscription stored before the check is skipped the same way.
        if _not_public(str(sub.get("endpoint", ""))):
            logger.warning("push: skipped a subscription whose endpoint is not public")
            continue
        try:
            webpush(
                subscription_info=sub,
                data=json.dumps({"title": title, "body": body, "url": url}),
                vapid_private_key=config.vapid_private(),
                vapid_claims={"sub": config.vapid_subject()},
                timeout=10,
            )
            sent += 1
        except WebPushException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status in (404, 410):
                dead.append(sid)
            else:
                logger.warning("push failed: %s", exc)
        except Exception:
            logger.exception("push failed")
    if dead:
        with db.session() as s:
            for sid in dead:
                row = s.get(db.PushSubscription, sid)
                if row is not None:
                    s.delete(row)
    return sent

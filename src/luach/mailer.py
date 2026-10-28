"""Outbound mail through Resend. Never raises: a household calendar must not
500 because an email provider is unreachable."""

from __future__ import annotations

import logging

from luach import config, mail_templates

logger = logging.getLogger(__name__)

API_URL = "https://api.resend.com/emails"
DEFAULT_FROM = "onboarding@resend.dev"


def configured() -> bool:
    return bool(config.resend_key())


#: How the person who runs luach sets a password without mail (luach.passwd).
OFFLINE_RESET = "docker compose exec luach python -m luach.passwd <username>"


def sender_status() -> dict:
    """What mail can do here, for the sign-in screen (open) and Members. ``limitation`` is
    a sentence for people, "" when mail works as it should."""
    sender = config.mail_from()
    limits = []
    if not configured():
        limits.append(
            "This luach does not send email (RESEND_API_KEY is not set), so a password "
            "reset link cannot be mailed. Whoever runs the server can set a new password: "
            f"{OFFLINE_RESET}."
        )
    else:
        if not sender:
            limits.append(
                "Using Resend's shared sender, which only delivers to the Resend account "
                "owner. Set LUACH_MAIL_FROM to a verified domain to mail anyone else."
            )
        if not config.app_url():
            limits.append(
                "LUACH_APP_URL is not set, so invitations, password resets and address "
                "confirmations are not sent: their links would lead nowhere."
            )
    return {
        "enabled": configured(),
        "sender": sender or DEFAULT_FROM,
        "own_domain": bool(sender),
        "limitation": " ".join(limits),
        "offline_reset": OFFLINE_RESET,
    }


def link(path: str) -> str:
    """An absolute link into the app, or "" when luach does not know its own
    address. A relative link in a mail opens nothing, so a mail whose point is
    its link is not sent without one."""
    home = config.app_url()
    if not home:
        logger.error("mailer: LUACH_APP_URL is not set; a mail that needs a link was not sent")
        return ""
    return f"{home}{path}"


def send(to: str, subject: str, text: str, html: str | None = None) -> bool:
    import requests

    key = config.resend_key()
    if not key:
        logger.warning("mailer: no RESEND_API_KEY; dropping message to %s", to)
        return False
    payload: dict = {
        "from": config.mail_from() or DEFAULT_FROM,
        "to": [to],
        "subject": subject,
        "text": text,
    }
    # Mail from luach is transactional — an invitation, a confirmation link, a
    # booking. There is no list to leave, and the one-click header
    # (List-Unsubscribe-Post) promised an endpoint that never existed: a POST to
    # the SPA answered 405, which reads as a broken sender. The plain mailto
    # form stays, because replying reaches a person.
    reply_to = config.mail_reply_to()
    if reply_to:
        payload["reply_to"] = reply_to
        payload["headers"] = {"List-Unsubscribe": f"<mailto:{reply_to}?subject=unsubscribe>"}
    if html:
        payload["html"] = html
    try:
        # Resend sits behind Cloudflare, which 403s Python's default User-Agent.
        r = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {key}", "User-Agent": config.user_agent()},
            json=payload,
            timeout=15,
        )
    except Exception:
        logger.exception("mailer: send to %s failed", to)
        return False
    if r.status_code >= 400:
        logger.error("mailer: resend refused (%s): %s", r.status_code, r.text[:300])
        return False
    return True


def send_invitation(to: str, inviter: str, token: str) -> bool:
    from luach.auth.invites import INVITE_TTL_HOURS

    url = link(f"/?invite={token}")
    if not url:
        return False
    text, html = mail_templates.invitation(inviter, url, INVITE_TTL_HOURS)
    return send(to, mail_templates.invitation_subject(inviter), text, html)


def send_recovery(to: str, username: str, token: str) -> bool:
    from luach.auth.recovery import RESET_TTL_MINUTES

    url = link(f"/?reset={token}")
    if not url:
        return False
    text, html = mail_templates.recovery(username, url, RESET_TTL_MINUTES)
    return send(to, "Getting you back into luach", text, html)


def send_verification(to: str, who: str, token: str, kind: str) -> bool:
    from luach.auth.users import VERIFY_TTL_HOURS

    url = link(f"/?verify={token}")
    if not url:
        return False
    text, html = mail_templates.verification(who, url, kind, VERIFY_TTL_HOURS)
    return send(to, "Confirm this address for luach", text, html)


def send_digest(to: str, subject: str, lines: list[str]) -> bool:
    text, html = mail_templates.digest(subject, lines)
    return send(to, subject, text, html)

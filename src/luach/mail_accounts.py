"""Each member's own mailbox: connected by them, searched only for them.

A household where everyone talks to luach is a household where one person's mail
must not answer another person's question. So there is no shared mailbox and no
owner's override: a member connects their own Gmail (read-only) from Settings, and
the chat's email tools reach that mailbox and no other.

The one grandfathered case is the owner's mailbox that the email door already reads
through the household's Google grant: it counts as the owner's own connection until
they connect one here, because it is theirs.

The grant is a refresh token, stored Fernet-encrypted with a key that lives outside
the database (LUACH_MAIL_KEY, or a mail.key file beside it that is not in the
backups). Connecting is authorization code + PKCE, with the state bound to the member
who started it: a callback finished by anyone else is refused. And the mailbox Google
signed in to must be one of that member's confirmed addresses, so nobody can attach
someone else's Gmail to their account by sending them a consent link.

A connect the iPhone app started comes back to a browser sheet with no luach session.
Its grant is held for a moment under a one-time nonce that only the app's ``luach://``
callback carries, and stored when the app posts the nonce back with its own session
(``complete_in_app``): a link finished on someone else's phone stores nothing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from luach import config, db

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
COOKIE_NAME = "luach_mail"
COOKIE_PATH = "/api/mail"
COOKIE_MAX_AGE = 600
#: Opens a state the iPhone app started: the member and the verifier, sealed (see start).
APP_STATE = "app1."

_lock = threading.Lock()
_access: dict[int, tuple[str, float]] = {}


@dataclass(frozen=True)
class _Held:
    """A grant from a connect the app started, waiting for the app to claim it."""

    user_id: int
    refresh: str
    address: str
    until: float


#: Grants waiting for the app, by nonce. In memory: a restart in those few seconds
#: costs a second try, and a grant never sits unclaimed on disk.
_held: dict[str, _Held] = {}


class NotConnected(Exception):
    """This member has not connected a mailbox."""


class ConnectFailed(Exception):
    """A reason safe to log: never a token, code, secret or address.

    ``reason`` is a short word the way back may carry, so the member is told what to do
    (``not-yours``: the mailbox is not one of their addresses here)."""

    def __init__(self, message: str, reason: str = "") -> None:
        super().__init__(message)
        self.reason = reason


#: How the way back names a mailbox that is not one of the member's addresses.
NOT_YOURS = "not-yours"


@dataclass(frozen=True)
class Start:
    url: str
    cookie: str


# --- the client and the key ------------------------------------------------------


def _client() -> dict[str, str] | None:
    path = config.mail_oauth_client()
    if not path:
        return None
    try:
        with open(path) as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return None
    # Google's downloaded JSON nests it under "web"/"installed"; a hand-written one may be flat.
    found = raw.get("web") or raw.get("installed") or raw
    if not found.get("client_id") or not found.get("client_secret"):
        return None
    return {"client_id": found["client_id"], "client_secret": found["client_secret"]}


def can_connect() -> bool:
    """Whether a member could connect a mailbox here at all."""
    return _client() is not None and bool(config.app_url())


def redirect_uri() -> str:
    return f"{config.app_url()}/api/mail/callback"


def _fernet() -> Fernet:
    key = config.mail_key()
    if not key:
        path = config.state_dir() / "mail.key"
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(Fernet.generate_key())
        key = path.read_text().strip()
    return Fernet(key.encode())


# --- connecting ------------------------------------------------------------------


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _address_on(user_id: int, domain: str) -> str:
    """This member's confirmed address on the household's domain, if they have one."""
    from luach.auth import users

    member = users.member(user_id)
    if member is None:
        return ""
    return next((e for e in member.emails if e.lower().endswith("@" + domain.lower())), "")


def start(user_id: int, *, app: bool = False) -> Start:
    """Google's consent URL, and the cookie that must come back with it.

    `app`: started from the iPhone app, whose browser sheet has neither the luach
    session nor a cookie of ours. The member and the verifier then travel inside the
    state itself, sealed with the mail key and good for COOKIE_MAX_AGE: Google hands
    it back untouched, a forged one does not open, and there is no cookie.
    """
    client = _client()
    if client is None or not config.app_url():
        raise ConnectFailed("no Google client configured for connecting mail")
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    if app:
        state = APP_STATE + _fernet().encrypt(f"{user_id}.{verifier}".encode()).decode()
    params = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        # Always ask, both which account and for consent: a second connect must hand
        # back a refresh token too, and without the chooser Google quietly used the
        # account the browser was signed in to — a personal Gmail, which an Internal
        # app refuses with org_internal.
        "prompt": "select_account consent",
        "include_granted_scopes": "false",
        "state": state,
        "code_challenge": _challenge(verifier),
        "code_challenge_method": "S256",
    }
    domain = config.mail_domain()
    if domain:
        # Offer only the household's accounts, and put this member's own first.
        params["hd"] = domain
        hint = _address_on(user_id, domain)
        if hint:
            params["login_hint"] = hint
    query = urllib.parse.urlencode(params)
    return Start(
        url=f"{config.google_auth_url()}?{query}",
        cookie="" if app else f"{user_id}.{state}.{verifier}",
    )


def _post(url: str, fields: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(url, data=urllib.parse.urlencode(fields).encode())
    with urllib.request.urlopen(req, timeout=30) as resp:
        return dict(json.load(resp))


def _gmail_get(path: str, token: str) -> dict[str, Any]:
    req = urllib.request.Request(f"{config.gmail_api()}/{path}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return dict(json.load(resp))


def finish(
    user_id: int,
    cookie: str | None,
    code: str | None,
    state: str | None,
    google_error: str | None = None,
) -> str:
    """Store the member's grant. Returns the address that was connected."""
    if google_error:
        raise ConnectFailed(f"google said {google_error[:40]}")
    try:
        started_by, expected, verifier = (cookie or "").split(".", 2)
    except ValueError as exc:
        raise ConnectFailed("no connect in progress") from exc
    if started_by != str(user_id):
        # Started by one member, finished in another's session: refused, so no one
        # can attach their mailbox to someone else's account, or the reverse.
        raise ConnectFailed("finished by a different member than started it")
    if not state or not hmac.compare_digest(expected.encode(), state.encode()):
        raise ConnectFailed("state mismatch")
    return _exchange(user_id, verifier, code)


def started_in_app(state: str | None) -> bool:
    return bool(state) and str(state).startswith(APP_STATE)


def finish_in_app(code: str | None, state: str | None, google_error: str | None = None) -> str:
    """Trade the code for a connect the app started, and hold the grant under a
    one-time nonce for ``complete_in_app``. Returns the nonce. Nothing is stored yet:
    the browser that got here has no session, and need not be the member's."""
    if google_error:
        raise ConnectFailed(f"google said {google_error[:40]}")
    try:
        sealed = (
            _fernet().decrypt(str(state)[len(APP_STATE) :].encode(), ttl=COOKIE_MAX_AGE).decode()
        )
        started_by, verifier = sealed.split(".", 1)
        user_id = int(started_by)
    except (InvalidToken, ValueError) as exc:
        raise ConnectFailed(
            "the app's state did not open (forged, or over ten minutes old)"
        ) from exc
    from luach.auth import users

    if users.member(user_id) is None:
        raise ConnectFailed("started by someone who is no longer a member")
    refresh, address = _obtain(user_id, verifier, code)
    nonce = secrets.token_urlsafe(32)
    now = time.time()
    with _lock:
        for gone in [n for n, h in _held.items() if h.until <= now]:
            del _held[gone]
        _held[nonce] = _Held(user_id, refresh, address, now + COOKIE_MAX_AGE)
    return nonce


def complete_in_app(user_id: int, nonce: str) -> str:
    """Store the grant held under ``nonce``, for the signed-in member who started it.
    The nonce works once. Returns the address that was connected."""
    with _lock:
        held = _held.pop(nonce, None) if nonce else None
    if held is None or held.until <= time.time():
        raise ConnectFailed("no connect is waiting under that nonce (used, or too old)")
    if held.user_id != user_id:
        # The consent was given for one member and claimed from another's app: the
        # grant goes back to Google rather than into either account.
        _revoke(held.refresh)
        raise ConnectFailed("claimed by a different member than started it")
    _store(user_id, held.refresh, held.address)
    return held.address


def _exchange(user_id: int, verifier: str, code: str | None) -> str:
    """Trade Google's code for the member's grant and keep it, encrypted."""
    refresh, address = _obtain(user_id, verifier, code)
    _store(user_id, refresh, address)
    return address


def _revoke(refresh: str) -> None:
    try:
        _post(config.google_revoke_url(), {"token": refresh})
    except Exception as exc:  # best effort: it is not kept here either way
        logger.warning("mail: revoking a refused grant at Google failed (%s)", type(exc).__name__)


def _obtain(user_id: int, verifier: str, code: str | None) -> tuple[str, str]:
    """Google's code, traded for (refresh token, mailbox address), if the mailbox
    is the member's own. A grant for anyone else's is revoked and refused."""
    from luach.auth import users

    if not code:
        raise ConnectFailed("no code")
    client = _client()
    if client is None:
        raise ConnectFailed("no Google client configured for connecting mail")
    try:
        tokens = _post(
            config.google_token_url(),
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(),
                "code_verifier": verifier,
                **client,
            },
        )
    except Exception as exc:
        raise ConnectFailed(f"the code exchange failed ({type(exc).__name__})") from exc
    refresh = tokens.get("refresh_token")
    if not refresh:
        raise ConnectFailed("google returned no refresh token")
    if SCOPE not in str(tokens.get("scope", SCOPE)).split():
        raise ConnectFailed("read access to mail was not granted")
    try:
        address = str(_gmail_get("profile", tokens["access_token"]).get("emailAddress", ""))
    except Exception:
        address = ""
    member = users.member(user_id)
    mine = {e.lower() for e in member.emails} if member is not None else set()
    if not address or address.lower() not in mine:
        # Whoever signed in at Google, it was not this member as luach knows them: a
        # consent link sent to someone else must not attach their mailbox here. The
        # member can add and confirm the address under their addresses, then connect.
        _revoke(refresh)
        if not address:
            raise ConnectFailed("Gmail did not say which mailbox this is")
        raise ConnectFailed("the mailbox is not one of the member's confirmed addresses", NOT_YOURS)
    return str(refresh), address


def _store(user_id: int, refresh: str, address: str) -> None:
    with db.session() as s:
        row = s.get(db.MailConnection, user_id)
        if row is None:
            row = db.MailConnection(user_id=user_id, grant="")
            s.add(row)
        row.address = address.lower()
        row.grant = _fernet().encrypt(refresh.encode()).decode()
        row.connected_at = db.utcnow()
    with _lock:
        _access.pop(user_id, None)
    _clear_lost(LOST.format(user_id=user_id))
    logger.info("mail: member %s connected their mailbox", user_id)


def disconnect(user_id: int) -> bool:
    """Forget the member's grant here, and ask Google to revoke it. True if there was one."""
    with db.session() as s:
        row = s.get(db.MailConnection, user_id)
        if row is None:
            return False
        grant = row.grant
        s.delete(row)
    with _lock:
        _access.pop(user_id, None)
    try:
        refresh = _fernet().decrypt(grant.encode()).decode()
        _post(config.google_revoke_url(), {"token": refresh})
    except Exception as exc:  # gone here already; Google's side is best effort
        logger.warning("mail: revoking member %s's grant at Google failed (%s)", user_id, exc)
    logger.info("mail: member %s disconnected their mailbox", user_id)
    return True


# --- using it --------------------------------------------------------------------


def _household_grant_is(user_id: int | None) -> bool:
    """The door's grant counts as the owner's own mailbox, and only the owner's."""
    from luach.ingest import gmail

    return user_id is not None and user_id == db.owner_id() and gmail.can_read()


#: The household grant's address, asked of Google once: (address, when asked).
_household: tuple[str, float] | None = None
#: How long a failed ask waits before the next; a found address is kept.
HOUSEHOLD_RETRY_SECONDS = 600


def household_address() -> str:
    """Which mailbox the household grant reads. "Connected — the household mailbox"
    left the owner guessing whose it was; this asks Gmail, once."""
    global _household
    if _household is not None and (
        _household[0] or time.time() - _household[1] < HOUSEHOLD_RETRY_SECONDS
    ):
        return _household[0]
    from luach.ingest import gmail

    try:
        address = str(_gmail_get("profile", gmail._token()).get("emailAddress") or "")
    except Exception as exc:  # the card still works without the name
        logger.info("mail: could not ask Gmail whose the household grant is (%s)", exc)
        address = ""
    _household = (address, time.time())
    return address


def status(user_id: int) -> dict[str, Any]:
    """Whether this member's mailbox is connected, and — when Google took a grant back —
    `lost`: which mailbox, and since when, so Settings (and the iPhone) can say
    "reconnect" instead of quietly showing a scan that has stopped."""
    with db.session() as s:
        row = s.get(db.MailConnection, user_id)
        own = (row.address, row.connected_at.isoformat()) if row is not None else None
    if own is not None:
        return {
            "connected": True,
            "address": own[0],
            "via": "own",
            "can_connect": can_connect(),
            "lost": None,
        }
    mine = lost(user_id)
    if _household_grant_is(user_id):
        door = lost(None)
        if door is not None:
            # The household grant is there but Google refuses it: not connected, whatever
            # the files say, and the owner is told why.
            return {
                "connected": False,
                "address": "",
                "via": "",
                "can_connect": can_connect(),
                "lost": door,
            }
        # can_connect still says whether the owner could connect their own instead:
        # once they do, their own grant is the one every read uses.
        return {
            "connected": True,
            "address": household_address(),
            "via": "household",
            "can_connect": can_connect(),
            "lost": mine,
        }
    return {
        "connected": False,
        "address": "",
        "via": "",
        "can_connect": can_connect(),
        "lost": mine,
    }


def connected(user_id: int | None) -> bool:
    return user_id is not None and bool(status(user_id)["connected"])


#: What Google's token endpoint answers when a grant will never work again.
GONE = frozenset({"invalid_grant", "unauthorized_client", "org_internal"})


def _refusal(exc: urllib.error.HTTPError) -> str | None:
    """The reason, when Google refused the grant itself; None for anything else."""
    if exc.code not in (400, 401, 403):
        return None
    try:
        body = json.loads(exc.read() or b"{}")
    except ValueError:
        return None
    reason = str(body.get("error") or "")
    return reason if reason in GONE else None


# --- a grant Google took back ---------------------------------------------------
#
# A personal Gmail connected through an app in Google's "testing" mode is refused after
# seven days; a revoke at myaccount or a password change does the same. Until this, the
# grant was dropped with a line in the log and the scan simply stopped. Now the member is
# told once — a push and, when luach sends mail, an email — and Settings says
# "reconnect" until they do (or dismiss it).

#: Settings key of a member's lost grant; the household door's is HOUSEHOLD_LOST.
LOST = "mail_lost:{user_id}"
HOUSEHOLD_LOST = "mail_lost:household"
#: Where the member reconnects.
RECONNECT_PATH = "/?tab=settings"


def _lost_key(user_id: int | None) -> str:
    return HOUSEHOLD_LOST if user_id is None else LOST.format(user_id=user_id)


def lost(user_id: int | None) -> dict[str, Any] | None:
    """The member's grant Google refused (None: the household door's), unless dismissed."""
    with db.session() as s:
        row = s.get(db.Setting, _lost_key(user_id))
        found = db.loads(row.value, {}) if row is not None else {}
    if not isinstance(found, dict) or not found or found.get("dismissed"):
        return None
    return {
        "address": str(found.get("address") or ""),
        "since": str(found.get("since") or ""),
        "via": "household" if user_id is None else "own",
    }


def _mark_lost(key: str, address: str, reason: str) -> bool:
    """Record the loss. True only the first time, so the member is told once."""
    with db.session() as s:
        row = s.get(db.Setting, key)
        if row is not None:
            return False
        value = {"address": address, "reason": reason, "since": db.utcnow().isoformat()}
        s.add(db.Setting(key=key, value=db.dumps(value)))
    return True


def _clear_lost(key: str) -> None:
    with db.session() as s:
        row = s.get(db.Setting, key)
        if row is not None:
            s.delete(row)


def dismiss_lost(user_id: int) -> bool:
    """The member saw the banner and does not want to reconnect. True if there was one.

    The household door's is kept, marked dismissed: it is still refused, and deleting it
    would tell the owner again on the next pass."""
    dismissed = False
    keys = [LOST.format(user_id=user_id)]
    if user_id == db.owner_id():
        keys.append(HOUSEHOLD_LOST)
    with db.session() as s:
        for key in keys:
            row = s.get(db.Setting, key)
            if row is None:
                continue
            value = db.loads(row.value, {})
            if not isinstance(value, dict) or value.get("dismissed"):
                continue
            if key == HOUSEHOLD_LOST:
                row.value = db.dumps({**value, "dismissed": True})
            else:
                s.delete(row)
            dismissed = True
    return dismissed


def _tell(user_id: int, address: str) -> None:
    """A push to the member's devices, and an email when luach sends mail. Never raises:
    the scan pass that noticed carries on either way."""
    from luach import mail_templates, mailer, push
    from luach.auth import users

    which = address or "your Gmail"
    title = "Gmail disconnected — reconnect"
    body = f"Google stopped luach reading {which}. Reconnect it in Settings to keep it going."
    try:
        push.notify_user(user_id, title, body, RECONNECT_PATH)
    except Exception:
        logger.exception("mail: could not push the lost grant to member %s", user_id)
    member = users.member(user_id)
    if member is None or not member.email or not mailer.configured():
        return
    home = config.app_url()
    text, html = mail_templates.mail_lost(address, f"{home}{RECONNECT_PATH}" if home else None)
    try:
        mailer.send(member.email, title, text, html)
    except Exception:
        logger.exception("mail: could not mail the lost grant to member %s", user_id)


def _forget(user_id: int, reason: str) -> None:
    from luach.agent.control import trail

    address = ""
    with db.session() as s:
        row = s.get(db.MailConnection, user_id)
        if row is not None:
            address = row.address
            s.delete(row)
    with _lock:
        _access.pop(user_id, None)
    logger.warning("mail: Google refused member %s's grant (%s); it is forgotten", user_id, reason)
    trail().record("mail.lost", {"member": user_id, "reason": reason})
    if _mark_lost(LOST.format(user_id=user_id), address, reason):
        _tell(user_id, address)


def household_refused(exc: urllib.error.HTTPError) -> None:
    """The email door's refresh was refused. When Google refused the grant itself, the
    owner — whose mailbox it reads — is told once; a passing error is left alone."""
    from luach.agent.control import trail

    reason = _refusal(exc)
    if reason is None:
        return
    owner = db.owner_id()
    address = _household[0] if _household is not None else ""
    if not _mark_lost(HOUSEHOLD_LOST, address, reason):
        return
    logger.warning("mail: Google refused the household grant (%s)", reason)
    trail().record("mail.lost", {"member": owner, "reason": reason, "via": "household"})
    if owner is not None:
        _tell(owner, address)


def household_working() -> None:
    """The household grant refreshed: whatever was lost is back (new tokens on disk)."""
    _clear_lost(HOUSEHOLD_LOST)


def access_token(user_id: int | None) -> str:
    """A token for this member's own mailbox — never anyone else's."""
    if user_id is None:
        raise NotConnected("nobody is asking")
    with db.session() as s:
        row = s.get(db.MailConnection, user_id)
        grant = row.grant if row is not None else None
    if grant is None:
        if _household_grant_is(user_id):
            from luach.ingest import gmail

            return gmail._token()
        raise NotConnected(str(user_id))
    with _lock:
        hit = _access.get(user_id)
        if hit and hit[1] > time.time() + 60:
            return hit[0]
    client = _client()
    if client is None:
        raise NotConnected("no Google client configured")
    try:
        refresh = _fernet().decrypt(grant.encode()).decode()
    except InvalidToken as exc:
        # The key changed (a restore without mail.key): the grant cannot be read, so
        # the member connects again rather than luach reading anyone's by mistake.
        raise NotConnected("the stored grant can no longer be read; connect again") from exc
    try:
        fresh = _post(
            config.google_token_url(),
            {"grant_type": "refresh_token", "refresh_token": refresh, **client},
        )
    except urllib.error.HTTPError as exc:
        reason = _refusal(exc)
        if reason is None:
            raise
        # Google has said no for good: revoked at myaccount, a password change, or an
        # account the app no longer admits (made Internal to the Workspace domain). Asking
        # again every pass changes nothing, so the grant is forgotten and the member is simply
        # not connected — and the owner reads the household mailbox again.
        _forget(user_id, reason)
        if _household_grant_is(user_id):
            from luach.ingest import gmail

            return gmail._token()
        raise NotConnected(
            f"Google no longer accepts this connection ({reason}); connect again"
        ) from exc
    token = str(fresh["access_token"])
    with _lock:
        _access[user_id] = (token, time.time() + int(fresh.get("expires_in", 3600)))
    return token

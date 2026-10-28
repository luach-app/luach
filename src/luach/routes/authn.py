"""Sign-in, sign-up by invitation, recovery, profile."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from luach import config, db, family, mail_accounts, mailer, memory
from luach.agent import runtime
from luach.agent.control import trail
from luach.auth import invites, oidc, passkeys, recovery, sessions, setup, throttle, users
from luach.auth.current import caller
from luach.routes.shared import (
    body,
    client_ip,
    error,
    note_forwarding,
    require_member,
    text_field,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth")


def set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        sessions.COOKIE_NAME,
        token,
        max_age=sessions.SESSION_TTL_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=config.cookie_secure(),
        path="/",
    )


def _sso_status() -> dict:
    cfg = config.oidc_settings()
    return {"enabled": cfg.enabled, "label": cfg.label}


@router.get("/status")
def status(request: Request) -> dict:
    # The first thing every page load asks: where a proxy that luach does not trust shows
    # up in the log, before anyone is locked out by it.
    note_forwarding(request)
    c = caller()
    member = users.member(c.user_id) if c else None
    return {
        "users_exist": db.users_exist(),
        "authenticated": member is not None,
        "member": member.as_dict() if member else None,
        "mail": mailer.sender_status(),
        "sso": _sso_status(),
        # The sign-in screen names the household before anyone has signed in.
        "household": config.household_name(),
    }


OWNER_EXISTS = "the owner already exists; ask them for an invitation"


@router.post("/register")
async def register(request: Request, response: Response) -> dict:
    """The first account, the owner. It needs the setup code the server printed to its log
    (auth/setup.py); once it exists, registration is closed and the code is spent."""
    if db.users_exist():
        raise error(403, OWNER_EXISTS)
    data = await body(request)
    ip = client_ip(request)
    wait = throttle.locked("setup", ip)
    if wait:
        raise error(429, "too many attempts; try again later", retry_after=wait)
    given = text_field(data, "setup_code", required=False, max_len=64)
    if not setup.matches(given):
        if not setup.current():
            setup.ensure()  # none made yet (it is made at startup): make it and log it now
        throttle.failed("setup", ip)
        raise error(
            403,
            ("that setup code is wrong" if given else "the setup code is required")
            + "; luach prints it to its log when it starts: docker compose logs luach",
        )
    try:
        member = users.create_user(
            text_field(data, "username", max_len=64),
            text_field(data, "email", max_len=255),
            text_field(data, "password", max_len=200),
            display_name=text_field(data, "display_name", required=False, max_len=128),
            timezone=text_field(data, "timezone", required=False, max_len=64) or None,
            first=True,
        )
    except users.OwnerExists as exc:
        raise error(403, OWNER_EXISTS) from exc
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    setup.spent()
    throttle.clear("setup", ip)
    logger.info("setup: %s set up the household and is its owner", member.username)
    family.welcome(member.id, member.display_name or member.username)
    set_cookie(response, sessions.mint_session(member.id))
    return member.as_dict()


@router.post("/login")
async def login(request: Request, response: Response) -> dict:
    data = await body(request)
    username = text_field(data, "username", max_len=255)
    password = text_field(data, "password", max_len=200)
    ip = client_ip(request)
    wait = throttle.locked(username, ip) or throttle.account_locked(username)
    if wait:
        raise error(429, "too many attempts; try again later", retry_after=wait)
    member = users.check_login(username, password)
    if member is None:
        throttle.failed(username, ip)
        throttle.account_failed(username)
        raise error(401, "wrong username or password")
    throttle.clear(username, ip)
    set_cookie(response, sessions.mint_session(member.id))
    return member.as_dict()


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    sessions.logout(request.cookies.get(sessions.COOKIE_NAME))
    response.delete_cookie(sessions.COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me() -> dict:
    return require_member().as_dict()


@router.patch("/me")
async def update_me(request: Request) -> dict:
    member = require_member()
    data = await body(request)
    fields = {
        k: text_field(data, k, required=False, max_len=255)
        for k in ("display_name", "timezone", "language", "email", "model")
        if k in data
    }
    try:
        if "notify_emails" in data:
            raw = data["notify_emails"]
            if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
                raise error(400, "notify_emails must be a list of emails")
            member = users.set_notify_emails(member.id, raw)
        if not fields:
            return member.as_dict()
        return users.update_profile(member.id, **fields).as_dict()
    except ValueError as exc:
        raise error(400, str(exc)) from exc


@router.post("/password")
async def change_password(request: Request) -> dict:
    member = require_member()
    data = await body(request)
    current = text_field(data, "current", max_len=200)
    new = text_field(data, "new", max_len=200)
    if users.check_login(member.username, current) is None:
        raise error(401, "the current password is wrong")
    try:
        users.set_password(member.id, new)
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    # A password is changed because it may be known: every other device signed in with
    # it is signed out. This one stays, since it just proved the current password.
    sessions.revoke_others(member.id, request.cookies.get(sessions.COOKIE_NAME))
    return {"ok": True}


DELETE_REFUSED_OWNER = (
    "you own this household, so your account cannot go while others belong to it: "
    "remove the other members first (Settings › Members)"
)


@router.delete("/me")
async def delete_me(request: Request, response: Response) -> dict:
    """A member deletes their own account, after typing their password again (App Store
    guideline 5.1.1(v), and anyone's right to leave). Their sessions, addresses, passkeys,
    conversations, reminders, busy feeds, booking page and Gmail connection go with it, and
    what luach remembered about them. Holds they caused stay, as nobody's; their family entry
    stays for the owner to keep or remove. The owner cannot go while anyone else belongs."""
    member = require_member()
    data = await body(request)
    password = text_field(data, "password", max_len=200)
    ip = client_ip(request)
    attempt = f"delete:{member.username}"
    wait = throttle.locked(attempt, ip) or throttle.account_locked(member.username)
    if wait:
        raise error(429, "too many attempts; try again later", retry_after=wait)
    if users.check_login(member.username, password) is None:
        # A wrong password here counts against the account as a sign-in does: a stolen
        # session must not become a way to guess the password.
        throttle.failed(attempt, ip)
        throttle.account_failed(member.username)
        raise error(401, "the password is wrong")
    throttle.clear(attempt, ip)
    if users.owner_has_members(member.id):
        raise error(409, DELETE_REFUSED_OWNER)
    with db.session() as s:
        threads = list(
            s.execute(select(db.Thread.id).where(db.Thread.user_id == member.id)).scalars()
        )
    # Google is asked to revoke the grant while luach still holds it; the row would go
    # with the account anyway, and with it the means to revoke.
    mail_accounts.disconnect(member.id)
    try:
        if not users.remove_self(member.id):
            raise error(404, "no such member")
    except users.OwnerHasMembers as exc:
        raise error(409, DELETE_REFUSED_OWNER) from exc
    for thread_id in threads:
        await runtime.forget_thread(thread_id)
    try:
        await memory.forget_member(member.id)
    except memory.MemoryUnavailable:
        logger.warning("delete account: member %s's memory could not be cleared", member.id)
    trail().record("member.deleted_own_account", {"user_id": member.id})
    logger.info("member %s deleted their own account", member.id)
    response.delete_cookie(sessions.COOKIE_NAME, path="/")
    return {"ok": True}


@router.post("/forgot")
async def forgot(request: Request) -> dict:
    data = await body(request)
    email = text_field(data, "email", max_len=255)
    ip = client_ip(request)
    if throttle.locked(f"forgot:{email}", ip):
        return {"ok": True}
    throttle.failed(f"forgot:{email}", ip)
    started = recovery.start(email)
    if started:
        member, token = started
        mailer.send_recovery(member.email, member.username, token)
    return {"ok": True}


@router.post("/reset")
async def reset(request: Request, response: Response) -> dict:
    data = await body(request)
    try:
        token = recovery.finish(
            text_field(data, "token", max_len=200), text_field(data, "password", max_len=200)
        )
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    set_cookie(response, token)
    user_id = sessions.authenticate(token)
    member = users.member(user_id) if user_id else None
    return member.as_dict() if member else {"ok": True}


@router.get("/invite/{token}")
def invite_peek(token: str) -> dict:
    info = invites.peek(token)
    if info is None:
        raise error(404, "this invitation is no longer valid")
    return info


@router.post("/accept")
async def accept(request: Request, response: Response) -> dict:
    data = await body(request)
    try:
        token = invites.accept(
            text_field(data, "token", max_len=200),
            text_field(data, "username", max_len=64),
            text_field(data, "password", max_len=200),
            text_field(data, "display_name", required=False, max_len=128),
            timezone=text_field(data, "timezone", required=False, max_len=64) or None,
        )
    except ValueError as exc:
        raise error(400, str(exc)) from exc
    set_cookie(response, token)
    user_id = sessions.authenticate(token)
    member = users.member(user_id) if user_id else None
    return member.as_dict() if member else {"ok": True}


@router.get("/emails")
def emails() -> dict:
    return users.emails_listing(require_member().id)


@router.post("/emails")
async def add_email(request: Request) -> dict:
    member = require_member()
    data = await body(request)
    try:
        return users.add_email(member.id, text_field(data, "email", max_len=255))
    except ValueError as exc:
        raise error(400, str(exc)) from exc


@router.delete("/emails/{email}")
def remove_email(email: str) -> dict:
    member = require_member()
    try:
        return {"ok": True, **users.remove_email(member.id, email)}
    except ValueError as exc:
        # Someone else's address, or none at all, is not found; the primary is
        # there but may not go.
        raise error(404 if "not yours" in str(exc) else 400, str(exc)) from exc


@router.post("/emails/resend")
async def resend_verification(request: Request) -> dict:
    member = require_member()
    data = await body(request)
    try:
        return users.resend_verification(member.id, text_field(data, "email", max_len=255))
    except ValueError as exc:
        raise error(400, str(exc)) from exc


@router.post("/verify")
async def verify_email(request: Request) -> dict:
    """Following a confirmation link. Open: the link is the proof, and the person
    reading it may be on the device that never signed in."""
    data = await body(request)
    try:
        return users.verify_address(text_field(data, "token", max_len=200))
    except ValueError as exc:
        raise error(400, str(exc)) from exc


@router.post("/emails/primary")
async def primary_email(request: Request) -> dict:
    member = require_member()
    data = await body(request)
    try:
        return users.make_primary(member.id, text_field(data, "email", max_len=255))
    except ValueError as exc:
        raise error(400, str(exc)) from exc


# --- passkeys ---------------------------------------------------------------


@router.get("/passkeys")
def list_passkeys() -> dict:
    return passkeys.listing(require_member().id)


@router.post("/passkeys/register/options")
def passkey_register_options() -> dict:
    return passkeys.registration_options(require_member().id)


@router.post("/passkeys/register/verify")
async def passkey_register_verify(request: Request) -> dict:
    member = require_member()
    data = await body(request)
    credential = data.get("credential")
    if not isinstance(credential, dict):
        raise error(400, "credential must be the browser's PublicKeyCredential JSON")
    try:
        return passkeys.register(
            member.id,
            text_field(data, "challenge_id", max_len=64),
            credential,
            text_field(data, "name", required=False, max_len=80),
        )
    except ValueError as exc:
        raise error(400, str(exc)) from exc


@router.delete("/passkeys/{passkey_id}")
def passkey_remove(passkey_id: str) -> dict:
    member = require_member()
    try:
        return {"ok": True, **passkeys.remove(member.id, passkey_id)}
    except ValueError as exc:
        raise error(404, str(exc)) from exc


@router.post("/passkeys/login/options")
def passkey_login_options(request: Request) -> dict:
    ip = client_ip(request)
    if throttle.locked("passkey", ip):
        raise error(
            429, "too many attempts; try again later", retry_after=throttle.locked("passkey", ip)
        )
    return passkeys.login_options()


@router.post("/passkeys/login/verify")
async def passkey_login_verify(request: Request, response: Response) -> dict:
    data = await body(request)
    credential = data.get("credential")
    if not isinstance(credential, dict):
        raise error(400, "credential must be the browser's PublicKeyCredential JSON")
    ip = client_ip(request)
    try:
        member = passkeys.login(text_field(data, "challenge_id", max_len=64), credential)
    except ValueError as exc:
        throttle.failed("passkey", ip)
        raise error(401, str(exc)) from exc
    throttle.clear("passkey", ip)
    set_cookie(response, sessions.mint_session(member.id))
    return member.as_dict()


# --- single sign-on (OIDC) ---------------------------------------------------

SSO_FAILED = "/?sso=failed"


def _oidc() -> config.OidcSettings:
    cfg = config.oidc_settings()
    if not cfg.enabled:
        raise error(404, "not found")
    return cfg


@router.get("/oidc/config")
def oidc_config() -> dict:
    return _sso_status()


@router.get("/oidc/start")
def oidc_start() -> RedirectResponse:
    cfg = _oidc()
    try:
        begun = oidc.start(cfg)
    except oidc.SignInFailed as exc:
        logger.warning("sso start failed: %s", exc)
        return RedirectResponse(SSO_FAILED, status_code=302)
    response = RedirectResponse(begun.url, status_code=302)
    response.set_cookie(
        oidc.COOKIE_NAME,
        begun.cookie,
        max_age=oidc.COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=config.cookie_secure(),
        path=oidc.COOKIE_PATH,
    )
    return response


@router.get("/oidc/callback")
def oidc_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    idp_error: str | None = Query(None, alias="error"),
) -> RedirectResponse:
    cfg = _oidc()
    try:
        member = oidc.finish(cfg, request.cookies.get(oidc.COOKIE_NAME), code, state, idp_error)
    except oidc.SignInFailed as exc:
        logger.warning("sso sign-in refused: %s", exc)
        response = RedirectResponse(SSO_FAILED, status_code=302)
    else:
        logger.info("sso sign-in for member %s", member.id)
        response = RedirectResponse("/", status_code=302)
        set_cookie(response, sessions.mint_session(member.id))
    response.delete_cookie(
        oidc.COOKIE_NAME,
        path=oidc.COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=config.cookie_secure(),
    )
    return response

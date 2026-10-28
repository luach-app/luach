"""Single sign-on through an OpenID Connect provider: authorization code + PKCE.

Additive to passwords and passkeys. It never creates an account: the provider's
email claim must already belong to a member, and the member must be in the
required group on the provider. The client secret, codes and tokens are never
logged. Every knob is a ``LUACH_OIDC_*`` setting; see ``config.oidc_settings``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import requests

from luach.auth import users
from luach.config import OidcSettings

COOKIE_NAME = "luach_oidc"
COOKIE_PATH = "/api/auth/oidc"
COOKIE_MAX_AGE = 600
DISCOVERY_TTL = 300

_lock = threading.Lock()
_discovery: dict[str, tuple[float, dict[str, Any]]] = {}


class SignInFailed(Exception):
    """A reason safe to log: never a token, code or secret."""


@dataclass(frozen=True)
class Start:
    url: str
    cookie: str


def reset_cache() -> None:
    with _lock:
        _discovery.clear()


def discover(cfg: OidcSettings) -> dict[str, Any]:
    now = time.monotonic()
    with _lock:
        hit = _discovery.get(cfg.issuer)
        if hit and now - hit[0] < DISCOVERY_TTL:
            return hit[1]
    try:
        resp = requests.get(
            f"{cfg.issuer}.well-known/openid-configuration", timeout=cfg.http_timeout
        )
    except requests.RequestException as exc:
        raise SignInFailed(f"discovery unreachable: {type(exc).__name__}") from exc
    if resp.status_code != 200:
        raise SignInFailed(f"discovery returned {resp.status_code}")
    try:
        doc = resp.json()
    except ValueError as exc:
        raise SignInFailed("discovery is not JSON") from exc
    if not isinstance(doc, dict) or doc.get("issuer") != cfg.issuer:
        raise SignInFailed("discovery issuer does not match the configured issuer")
    for key in ("authorization_endpoint", "token_endpoint", "userinfo_endpoint"):
        if not isinstance(doc.get(key), str) or not doc[key]:
            raise SignInFailed(f"discovery lacks {key}")
    with _lock:
        _discovery[cfg.issuer] = (now, doc)
    return doc


def _challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def start(cfg: OidcSettings) -> Start:
    endpoint = discover(cfg)["authorization_endpoint"]
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": cfg.client_id,
            "redirect_uri": cfg.redirect_uri,
            "scope": cfg.scopes,
            "state": state,
            "code_challenge": _challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    sep = "&" if "?" in endpoint else "?"
    return Start(url=f"{endpoint}{sep}{query}", cookie=f"{state}.{verifier}")


def _json(resp: requests.Response, what: str) -> dict[str, Any]:
    if resp.status_code != 200:
        raise SignInFailed(f"{what} returned {resp.status_code}")
    try:
        data = resp.json()
    except ValueError as exc:
        raise SignInFailed(f"{what} is not JSON") from exc
    if not isinstance(data, dict):
        raise SignInFailed(f"{what} is not a JSON object")
    return data


def finish(
    cfg: OidcSettings,
    cookie: str | None,
    code: str | None,
    state: str | None,
    idp_error: str | None,
) -> users.Member:
    """Exchange the code and resolve the member, or raise SignInFailed."""
    if idp_error:
        raise SignInFailed("provider returned an error")
    if not cookie:
        raise SignInFailed("no sign-in cookie")
    expected, _, verifier = cookie.partition(".")
    if not expected or not verifier:
        raise SignInFailed("malformed sign-in cookie")
    if not state or not hmac.compare_digest(expected.encode(), state.encode()):
        raise SignInFailed("state mismatch")
    if not code:
        raise SignInFailed("no authorization code")
    doc = discover(cfg)
    try:
        token_resp = requests.post(
            doc["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": cfg.redirect_uri,
                "code_verifier": verifier,
            },
            auth=(cfg.client_id, cfg.client_secret),
            headers={"Accept": "application/json"},
            timeout=cfg.http_timeout,
        )
    except requests.RequestException as exc:
        raise SignInFailed(f"token endpoint unreachable: {type(exc).__name__}") from exc
    access = _json(token_resp, "token endpoint").get("access_token")
    if not isinstance(access, str) or not access:
        raise SignInFailed("token response lacks an access token")
    try:
        info_resp = requests.get(
            doc["userinfo_endpoint"],
            headers={"Authorization": f"Bearer {access}", "Accept": "application/json"},
            timeout=cfg.http_timeout,
        )
    except requests.RequestException as exc:
        raise SignInFailed(f"userinfo unreachable: {type(exc).__name__}") from exc
    info = _json(info_resp, "userinfo")
    groups = info.get(cfg.groups_claim)
    if not isinstance(groups, list) or cfg.required_group not in groups:
        raise SignInFailed(f"not in the required group {cfg.required_group!r}")
    email = info.get(cfg.email_claim)
    if not isinstance(email, str) or "@" not in email:
        raise SignInFailed(f"userinfo has no {cfg.email_claim!r} claim")
    # An identity provider that lets a person edit their own profile can hand us
    # someone else's address; only take one it says it checked. Saying nothing is not
    # saying it checked.
    if info.get("email_verified") is not True:
        raise SignInFailed("the identity provider has not verified that address")
    subject = info.get("sub")
    if not isinstance(subject, str) or not subject:
        raise SignInFailed("userinfo has no subject")
    return _member_for(str(doc.get("issuer") or cfg.issuer), subject, email)


def _member_for(issuer: str, subject: str, email: str) -> users.Member:
    """The member this provider account is. The first sign-in links the account's
    subject to the member whose confirmed address it shows; after that the subject
    decides, so an account that comes to show someone else's address stays itself, and a
    member already linked to one account is not signed in to by another."""
    from sqlalchemy import select

    from luach import db

    with db.session() as s:
        linked = s.get(db.OidcLink, (issuer, subject))
        if linked is not None:
            member = users.member(linked.user_id)
            if member is None:
                raise SignInFailed("the linked member no longer exists")
            return member
        member = users.member_by_email(email)
        if member is None:
            raise SignInFailed("no member has that email")
        other = s.execute(
            select(db.OidcLink).where(
                db.OidcLink.issuer == issuer, db.OidcLink.user_id == member.id
            )
        ).scalar_one_or_none()
        if other is not None:
            raise SignInFailed("that member signs in with a different provider account")
        s.add(db.OidcLink(issuer=issuer, subject=subject, user_id=member.id))
    return member

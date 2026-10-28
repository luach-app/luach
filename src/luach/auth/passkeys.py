"""Passkeys (WebAuthn) — a second way in, beside the password.

Registration and login both run in two steps: options (a challenge the
browser signs) and verify (the signed response). The challenge lives in
the database for five minutes and is consumed on first use, so a response
can never be replayed. Login uses discoverable credentials: the browser
finds the passkey itself, so no username is typed.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from luach import config, db
from luach.auth import users

CHALLENGE_TTL = timedelta(minutes=5)
RP_NAME = "luach"


def _store_challenge(kind: str, challenge: bytes, user_id: int | None) -> str:
    cid = uuid.uuid4().hex
    with db.session() as s:
        s.add(
            db.Challenge(
                id=cid,
                kind=kind,
                user_id=user_id,
                challenge=bytes_to_base64url(challenge),
                expires_at=db.utcnow() + CHALLENGE_TTL,
            )
        )
    return cid


def _take_challenge(cid: str, kind: str) -> tuple[bytes, int | None]:
    """Return (challenge, user_id) and burn the row; ValueError if unusable."""
    with db.session() as s:
        row = s.get(db.Challenge, cid)
        if row is None or row.kind != kind:
            raise ValueError("start again — that challenge is unknown")
        challenge, user_id, expires_at = row.challenge, row.user_id, row.expires_at
        s.delete(row)  # burnt on the way out, whatever the verdict below
    if expires_at <= db.utcnow():
        raise ValueError("start again — that challenge expired")
    return base64url_to_bytes(challenge), user_id


def purge_expired() -> int:
    with db.session() as s:
        rows = (
            s.execute(select(db.Challenge).where(db.Challenge.expires_at <= db.utcnow()))
            .scalars()
            .all()
        )
        for r in rows:
            s.delete(r)
        return len(rows)


def listing(user_id: int) -> dict[str, Any]:
    with db.session() as s:
        rows = (
            s.execute(
                select(db.Passkey)
                .where(db.Passkey.user_id == user_id)
                .order_by(db.Passkey.created_at)
            )
            .scalars()
            .all()
        )
        return {
            "passkeys": [
                {
                    "id": r.id,
                    "name": r.name,
                    "created_at": db.iso(r.created_at),
                    "last_used": db.iso(r.last_used),
                }
                for r in rows
            ]
        }


def registration_options(user_id: int) -> dict[str, Any]:
    member = users.member(user_id)
    if member is None:
        raise ValueError("no such member")
    with db.session() as s:
        existing = (
            s.execute(select(db.Passkey.id).where(db.Passkey.user_id == user_id)).scalars().all()
        )
    options = generate_registration_options(
        rp_id=config.rp_id(),
        rp_name=RP_NAME,
        user_id=str(user_id).encode(),
        user_name=member.username,
        user_display_name=member.display_name,
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(i)) for i in existing
        ],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            # A passkey that signs in must prove the person (a face, a fingerprint, a PIN),
            # so one that cannot is not registered only to fail at the next sign-in.
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    import json

    return {
        "challenge_id": _store_challenge("register", options.challenge, user_id),
        "options": json.loads(options_to_json(options)),
    }


def register(user_id: int, challenge_id: str, credential: Any, name: str = "") -> dict[str, Any]:
    challenge, owner = _take_challenge(challenge_id, "register")
    if owner != user_id:
        raise ValueError("that challenge belongs to someone else")
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=config.rp_id(),
            expected_origin=config.rp_origins(),
            require_user_verification=True,
        )
    except Exception as exc:
        raise ValueError(f"the passkey could not be verified ({type(exc).__name__})") from exc
    cred_id = bytes_to_base64url(verified.credential_id)
    transports = ""
    if isinstance(credential, dict):
        transports = ",".join(credential.get("response", {}).get("transports", []) or [])
    with db.session() as s:
        if s.get(db.Passkey, cred_id) is not None:
            raise ValueError("that passkey is already registered")
        s.add(
            db.Passkey(
                id=cred_id,
                user_id=user_id,
                public_key=bytes_to_base64url(verified.credential_public_key),
                sign_count=verified.sign_count,
                transports=transports,
                name=(name or "passkey").strip()[:80],
            )
        )
    return listing(user_id)


def remove(user_id: int, passkey_id: str) -> dict[str, Any]:
    with db.session() as s:
        row = s.get(db.Passkey, passkey_id)
        if row is None or row.user_id != user_id:
            raise ValueError("that passkey is not yours")
        s.delete(row)
    return listing(user_id)


def login_options() -> dict[str, Any]:
    options = generate_authentication_options(
        rp_id=config.rp_id(),
        allow_credentials=[],  # discoverable: the authenticator picks
        # Holding the device is not enough: the person must unlock it (face, fingerprint,
        # PIN), or a phone left on the table signs whoever picks it up in.
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    import json

    return {
        "challenge_id": _store_challenge("login", options.challenge, None),
        "options": json.loads(options_to_json(options)),
    }


def login(challenge_id: str, credential: Any) -> users.Member:
    """Verify a signed assertion and return the member it belongs to."""
    challenge, _ = _take_challenge(challenge_id, "login")
    raw_id = credential.get("id") if isinstance(credential, dict) else None
    if not raw_id:
        raise ValueError("the response names no credential")
    with db.session() as s:
        row = s.get(db.Passkey, raw_id)
        if row is None:
            raise ValueError("unknown passkey")
        public_key = base64url_to_bytes(row.public_key)
        count = row.sign_count
        user_id = row.user_id
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=config.rp_id(),
            expected_origin=config.rp_origins(),
            credential_public_key=public_key,
            credential_current_sign_count=count,
            require_user_verification=True,
        )
    except Exception as exc:
        raise ValueError(f"the passkey could not be verified ({type(exc).__name__})") from exc
    with db.session() as s:
        row = s.get(db.Passkey, raw_id)
        if row is not None:
            row.sign_count = verified.new_sign_count
            row.last_used = db.utcnow()
    member = users.member(user_id)
    if member is None:
        raise ValueError("that account no longer exists")
    return member

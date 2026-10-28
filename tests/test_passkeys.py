from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from webauthn.helpers import bytes_to_base64url

from luach import db
from luach.app import create_app
from luach.auth import passkeys


@pytest.fixture
async def client(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://luach.test") as c:
        yield c


async def login(c, username="robin", password="correct horse battery"):
    r = await c.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _fake_registration(monkeypatch, cred_id=b"cred-1", public_key=b"pk", count=0):
    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **kw: SimpleNamespace(
            credential_id=cred_id, credential_public_key=public_key, sign_count=count
        ),
    )


def test_relying_party_comes_from_the_app_url(monkeypatch):
    from luach import config

    monkeypatch.setenv("LUACH_APP_URL", "https://luach.example.com")
    assert config.rp_id() == "luach.example.com"
    assert config.rp_origins() == ["https://luach.example.com"]
    monkeypatch.setenv("LUACH_EXTRA_ORIGINS", "https://luach.local, ")
    assert config.rp_origins()[1] == "https://luach.local"
    monkeypatch.setenv("LUACH_RP_ID", "example.org")
    assert config.rp_id() == "example.org"


def test_registration_options_carry_a_stored_challenge_and_exclude_existing():
    opts = passkeys.registration_options(1)
    assert opts["options"]["rp"]["id"] == "luach.test"
    assert opts["options"]["user"]["name"] == "robin"
    assert opts["options"]["authenticatorSelection"]["residentKey"] == "required"
    with db.session() as s:
        row = s.get(db.Challenge, opts["challenge_id"])
        assert row is not None and row.kind == "register" and row.user_id == 1
    with pytest.raises(ValueError):
        passkeys.registration_options(999)


def test_register_and_remove_with_a_faked_verifier(monkeypatch):
    _fake_registration(monkeypatch)
    opts = passkeys.registration_options(1)
    cred = {"id": "x", "response": {"transports": ["internal", "hybrid"]}}
    listing = passkeys.register(1, opts["challenge_id"], cred, name="iPhone")
    assert listing["passkeys"][0]["name"] == "iPhone"
    pk_id = listing["passkeys"][0]["id"]
    assert pk_id == bytes_to_base64url(b"cred-1")
    with db.session() as s:
        assert s.get(db.Passkey, pk_id).transports == "internal,hybrid"
        assert s.get(db.Challenge, opts["challenge_id"]) is None  # burnt
    # the same challenge cannot be replayed
    with pytest.raises(ValueError):
        passkeys.register(1, opts["challenge_id"], cred)
    # a second registration of the same credential is refused
    opts2 = passkeys.registration_options(1)
    assert opts2["options"]["excludeCredentials"][0]["id"] == pk_id
    with pytest.raises(ValueError):
        passkeys.register(1, opts2["challenge_id"], cred)
    # someone else's challenge
    opts3 = passkeys.registration_options(2)
    with pytest.raises(ValueError):
        passkeys.register(1, opts3["challenge_id"], cred)
    with pytest.raises(ValueError):
        passkeys.remove(2, pk_id)
    assert passkeys.remove(1, pk_id) == {"passkeys": []}


def test_register_failure_is_a_sentence(monkeypatch):
    def boom(**kw):
        raise RuntimeError("bad attestation")

    monkeypatch.setattr(passkeys, "verify_registration_response", boom)
    opts = passkeys.registration_options(1)
    with pytest.raises(ValueError, match="could not be verified"):
        passkeys.register(1, opts["challenge_id"], {"id": "x"})


def test_expired_challenges_are_refused_and_purged():
    opts = passkeys.login_options()
    with db.session() as s:
        s.get(db.Challenge, opts["challenge_id"]).expires_at = db.utcnow() - timedelta(seconds=1)
    with pytest.raises(ValueError, match="expired"):
        passkeys.login(opts["challenge_id"], {"id": "x"})
    opts = passkeys.login_options()
    with db.session() as s:
        s.get(db.Challenge, opts["challenge_id"]).expires_at = db.utcnow() - timedelta(seconds=1)
    assert passkeys.purge_expired() == 1
    with pytest.raises(ValueError, match="unknown"):
        passkeys.login("nope", {"id": "x"})
    with pytest.raises(ValueError, match="unknown passkey"):
        passkeys.login(passkeys.login_options()["challenge_id"], {"id": "never-registered"})
    with pytest.raises(ValueError, match="names no credential"):
        passkeys.login(passkeys.login_options()["challenge_id"], {})


def test_login_with_a_faked_verifier_updates_the_counter(monkeypatch):
    _fake_registration(monkeypatch, cred_id=b"cred-2", count=3)
    opts = passkeys.registration_options(2)
    pk_id = passkeys.register(2, opts["challenge_id"], {"id": "x"})["passkeys"][0]["id"]
    monkeypatch.setattr(
        passkeys, "verify_authentication_response", lambda **kw: SimpleNamespace(new_sign_count=4)
    )
    member = passkeys.login(passkeys.login_options()["challenge_id"], {"id": pk_id})
    assert member.username == "ana"
    with db.session() as s:
        row = s.get(db.Passkey, pk_id)
        assert row.sign_count == 4 and row.last_used is not None

    def bad(**kw):
        raise RuntimeError("signature")

    monkeypatch.setattr(passkeys, "verify_authentication_response", bad)
    with pytest.raises(ValueError, match="could not be verified"):
        passkeys.login(passkeys.login_options()["challenge_id"], {"id": pk_id})


async def test_passkey_routes(client, monkeypatch):
    # login endpoints are open, the rest need a session
    assert (await client.get("/api/auth/passkeys")).status_code == 401
    r = await client.post("/api/auth/passkeys/login/options", json={})
    assert r.status_code == 200 and "challenge" in r.json()["options"]
    r = await client.post(
        "/api/auth/passkeys/login/verify",
        json={"challenge_id": r.json()["challenge_id"], "credential": {"id": "nope"}},
    )
    assert r.status_code == 401
    assert (
        await client.post(
            "/api/auth/passkeys/login/verify", json={"challenge_id": "x", "credential": "str"}
        )
    ).status_code == 400
    await login(client)
    assert (await client.get("/api/auth/passkeys")).json() == {"passkeys": []}
    r = await client.post("/api/auth/passkeys/register/options", json={})
    assert r.status_code == 200
    cid = r.json()["challenge_id"]
    assert (
        await client.post(
            "/api/auth/passkeys/register/verify", json={"challenge_id": cid, "credential": "nope"}
        )
    ).status_code == 400
    _fake_registration(monkeypatch, cred_id=b"cred-3")
    r = await client.post(
        "/api/auth/passkeys/register/verify",
        json={"challenge_id": cid, "credential": {"id": "x"}, "name": "Mac"},
    )
    assert r.status_code == 200 and r.json()["passkeys"][0]["name"] == "Mac"
    pk_id = r.json()["passkeys"][0]["id"]
    # sign in with it on a fresh client
    await client.post("/api/auth/logout")
    monkeypatch.setattr(
        passkeys, "verify_authentication_response", lambda **kw: SimpleNamespace(new_sign_count=1)
    )
    opts = (await client.post("/api/auth/passkeys/login/options", json={})).json()
    r = await client.post(
        "/api/auth/passkeys/login/verify",
        json={"challenge_id": opts["challenge_id"], "credential": {"id": pk_id}},
    )
    assert r.status_code == 200 and r.json()["username"] == "robin"
    assert (await client.get("/api/auth/me")).status_code == 200
    assert (await client.delete("/api/auth/passkeys/other")).status_code == 404
    assert (await client.delete(f"/api/auth/passkeys/{pk_id}")).json() == {
        "ok": True,
        "passkeys": [],
    }


async def test_passkey_login_is_throttled_per_client(client):
    for _ in range(8):
        opts = (await client.post("/api/auth/passkeys/login/options", json={})).json()
        r = await client.post(
            "/api/auth/passkeys/login/verify",
            json={"challenge_id": opts["challenge_id"], "credential": {"id": "nope"}},
        )
        assert r.status_code == 401
    assert (await client.post("/api/auth/passkeys/login/options", json={})).status_code == 429


async def test_client_ip_trusts_only_loopback_front_doors(client, monkeypatch):
    from luach.auth import throttle

    seen: list[str] = []
    monkeypatch.setattr(throttle, "failed", lambda name, ip: seen.append(ip))
    await client.post(
        "/api/auth/login",
        json={"username": "robin", "password": "wrong"},
        headers={"cf-connecting-ip": "203.0.113.9"},
    )
    await client.post(
        "/api/auth/login",
        json={"username": "robin", "password": "wrong"},
        headers={"x-forwarded-for": "198.51.100.4, 10.0.0.1"},
    )
    await client.post("/api/auth/login", json={"username": "robin", "password": "wrong"})
    assert seen == ["203.0.113.9", "198.51.100.4", "127.0.0.1"]


async def test_client_ip_follows_trusted_proxies(client, monkeypatch):
    from luach.auth import throttle
    from luach.routes import shared

    seen: list[str] = []
    monkeypatch.setattr(throttle, "failed", lambda name, ip: seen.append(ip))
    headers = {"cf-connecting-ip": "203.0.113.9"}
    body = {"username": "robin", "password": "wrong"}
    # The test client connects from 127.0.0.1: outside a pod-network-only list, the
    # header is ignored; inside a wider list, it is believed; junk entries are skipped.
    monkeypatch.setenv("LUACH_TRUSTED_PROXIES", "10.42.0.0/16")
    await client.post("/api/auth/login", json=body, headers=headers)
    monkeypatch.setenv("LUACH_TRUSTED_PROXIES", "not-a-network,127.0.0.0/8")
    await client.post("/api/auth/login", json=body, headers=headers)
    assert seen == ["127.0.0.1", "203.0.113.9"]
    assert shared._trusted_peer("?") is False


def test_passwd_cli(monkeypatch, capsys):
    from luach import passwd
    from luach.auth import users

    answers = iter(["a brand new password", "a brand new password"])
    monkeypatch.setattr(passwd.getpass, "getpass", lambda prompt: next(answers))
    assert passwd.main(["robin"]) == 0
    assert users.check_login("robin", "a brand new password") is not None
    assert passwd.main(["nobody"]) == 1 and passwd.main([]) == 2
    answers = iter(["one", "two"])
    monkeypatch.setattr(passwd.getpass, "getpass", lambda prompt: next(answers))
    assert passwd.main(["robin"]) == 1
    answers = iter(["short", "short"])
    monkeypatch.setattr(passwd.getpass, "getpass", lambda prompt: next(answers))
    assert passwd.main(["robin"]) == 1


def _signed_assertion(challenge: bytes, *, verified_user: bool) -> tuple[dict, str]:
    """A real WebAuthn assertion from a real key, its user-verified flag as asked, and the
    key as luach stores it. Only the authenticator is played here; luach checks it all."""
    import hashlib
    import json

    import cbor2
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from webauthn.helpers import bytes_to_base64url

    from luach import config

    key = ec.generate_private_key(ec.SECP256R1())
    nums = key.public_key().public_numbers()
    cose = cbor2.dumps(
        {1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")}
    )
    flags = 0x01 | (0x04 if verified_user else 0)  # user present, and maybe verified
    auth_data = (
        hashlib.sha256(config.rp_id().encode()).digest() + bytes([flags]) + (5).to_bytes(4, "big")
    )
    client_data = json.dumps(
        {
            "type": "webauthn.get",
            "challenge": bytes_to_base64url(challenge),
            "origin": config.rp_origins()[0],
            "crossOrigin": False,
        }
    ).encode()
    signature = key.sign(
        auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
    )
    cred_id = bytes_to_base64url(b"real-cred")
    return (
        {
            "id": cred_id,
            "rawId": cred_id,
            "type": "public-key",
            "response": {
                "authenticatorData": bytes_to_base64url(auth_data),
                "clientDataJSON": bytes_to_base64url(client_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": bytes_to_base64url(b"1"),
            },
        },
        bytes_to_base64url(cose),
    )


@pytest.mark.parametrize("verified_user", [True, False])
def test_signing_in_needs_the_person_not_only_the_device(verified_user):
    """A passkey assertion whose authenticator did not verify the person (no face,
    fingerprint or PIN: whoever holds the phone) does not sign in."""
    from webauthn.helpers import base64url_to_bytes

    opts = passkeys.login_options()
    assert opts["options"]["userVerification"] == "required"
    challenge = base64url_to_bytes(opts["options"]["challenge"])
    credential, public_key = _signed_assertion(challenge, verified_user=verified_user)
    with db.session() as s:
        s.add(
            db.Passkey(
                id=credential["id"],
                user_id=1,
                public_key=public_key,
                sign_count=0,
                transports="",
                name="phone",
            )
        )
    if verified_user:
        assert passkeys.login(opts["challenge_id"], credential).username == "robin"
    else:
        with pytest.raises(ValueError, match="could not be verified"):
            passkeys.login(opts["challenge_id"], credential)


def test_registering_asks_for_a_passkey_that_verifies_the_person(monkeypatch):
    seen: dict = {}

    def verifier(**kw):
        seen.update(kw)
        return SimpleNamespace(credential_id=b"c", credential_public_key=b"pk", sign_count=0)

    monkeypatch.setattr(passkeys, "verify_registration_response", verifier)
    opts = passkeys.registration_options(1)
    assert opts["options"]["authenticatorSelection"]["userVerification"] == "required"
    passkeys.register(1, opts["challenge_id"], {"id": "x"})
    assert seen["require_user_verification"] is True

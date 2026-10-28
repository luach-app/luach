"""Single sign-on through an OpenID provider, with the provider mocked at the HTTP calls."""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from httpx import ASGITransport, AsyncClient

from luach import config, db
from luach.app import create_app
from luach.auth import oidc, users

ISSUER = "https://auth.harper.test/application/o/luach-signin/"
AUTHZ = "https://auth.harper.test/application/o/authorize/"
TOKEN = "https://auth.harper.test/application/o/token/"
USERINFO = "https://auth.harper.test/application/o/userinfo/"


class FakeResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status_code = status
        self._payload = payload

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeIdP:
    def __init__(self) -> None:
        self.issuer = ISSUER
        self.discovery_status = 200
        self.token_status = 200
        self.token_payload: object = {"access_token": "at-123", "token_type": "Bearer"}
        self.userinfo_status = 200
        self.userinfo: object = {"email": "Robin@Example.com", "groups": ["admins"]}
        self.raise_on: str | None = None
        #: Fill in email_verified and sub when a test's userinfo leaves them out.
        self.complete = True
        self.discovery_calls = 0
        self.token_requests: list[dict] = []
        self.userinfo_requests: list[dict] = []

    def get(self, url: str, **kw: object) -> FakeResponse:
        if url == f"{ISSUER}.well-known/openid-configuration":
            self.discovery_calls += 1
            if self.raise_on == "discovery":
                raise requests.ConnectionError("down")
            return FakeResponse(
                self.discovery_status,
                {
                    "issuer": self.issuer,
                    "authorization_endpoint": AUTHZ,
                    "token_endpoint": TOKEN,
                    "userinfo_endpoint": USERINFO,
                },
            )
        if url == USERINFO:
            self.userinfo_requests.append(kw)
            if self.raise_on == "userinfo":
                raise requests.Timeout("slow")
            info = self.userinfo
            if isinstance(info, dict) and self.complete:
                # As the owner's provider answers: the address asserted verified, and a
                # subject per account (here, one per address unless a test says otherwise).
                email = str(info.get("email") or info.get("mail") or "")
                info = {"email_verified": True, "sub": f"sub:{email.lower()}", **info}
            return FakeResponse(self.userinfo_status, info)
        raise AssertionError(f"unexpected GET {url}")

    def post(self, url: str, **kw: object) -> FakeResponse:
        assert url == TOKEN
        self.token_requests.append(kw)
        if self.raise_on == "token":
            raise requests.ConnectionError("down")
        return FakeResponse(self.token_status, self.token_payload)


@pytest.fixture
def idp(monkeypatch) -> FakeIdP:
    fake = FakeIdP()
    monkeypatch.setattr(oidc.requests, "get", fake.get)
    monkeypatch.setattr(oidc.requests, "post", fake.post)
    oidc.reset_cache()
    yield fake
    oidc.reset_cache()


@pytest.fixture
def enabled(monkeypatch, idp) -> FakeIdP:
    monkeypatch.setenv("LUACH_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("LUACH_OIDC_CLIENT_ID", "luach-client")
    monkeypatch.setenv("LUACH_OIDC_CLIENT_SECRET", "s3cret")
    monkeypatch.delenv("LUACH_OIDC_REQUIRED_GROUP", raising=False)
    return idp


@pytest.fixture
async def client(tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://luach.test") as c:
        yield c


async def _start(c: AsyncClient) -> dict[str, str]:
    r = await c.get("/api/auth/oidc/start")
    assert r.status_code == 302
    return {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}


async def _signin(c: AsyncClient) -> object:
    q = await _start(c)
    return await c.get(f"/api/auth/oidc/callback?code=the-code&state={q['state']}")


def _failed(r: object) -> bool:
    return r.status_code == 302 and r.headers["location"] == "/?sso=failed"  # type: ignore[attr-defined]


def _session_count() -> int:
    with db.session() as s:
        return s.query(db.SessionRow).count()


async def test_disabled_hides_everything(client, monkeypatch, idp):
    for name in ("LUACH_OIDC_ISSUER", "LUACH_OIDC_CLIENT_ID", "LUACH_OIDC_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LUACH_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("LUACH_OIDC_CLIENT_ID", "luach-client")  # no secret: still off
    assert (await client.get("/api/auth/oidc/start")).status_code == 404
    assert (await client.get("/api/auth/oidc/callback?code=x&state=y")).status_code == 404
    assert (await client.get("/api/auth/oidc/config")).json()["enabled"] is False
    status = (await client.get("/api/auth/status")).json()
    assert status["sso"]["enabled"] is False
    assert idp.discovery_calls == 0


async def test_config_and_status_report_enabled(client, enabled):
    assert (await client.get("/api/auth/oidc/config")).json() == {
        "enabled": True,
        "label": "Sign in with single sign-on",
    }
    sso = (await client.get("/api/auth/status")).json()["sso"]
    assert sso == {"enabled": True, "label": "Sign in with single sign-on"}


async def test_start_redirects_with_pkce_state_and_cookie(client, enabled):
    r = await client.get("/api/auth/oidc/start")
    assert r.status_code == 302
    url = urlsplit(r.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == AUTHZ
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert q["response_type"] == "code"
    assert q["client_id"] == "luach-client"
    assert q["redirect_uri"] == "https://luach.test/api/auth/oidc/callback"
    assert q["scope"] == "openid email profile groups"
    assert q["code_challenge_method"] == "S256"
    set_cookie = r.headers["set-cookie"]
    assert set_cookie.startswith("luach_oidc=")
    lowered = set_cookie.lower()
    assert "httponly" in lowered and "samesite=lax" in lowered
    assert "path=/api/auth/oidc" in lowered and "max-age=600" in lowered
    assert "secure" not in lowered  # LUACH_COOKIE_SECURE=0 in tests
    state, _, verifier = client.cookies.get("luach_oidc", path="/api/auth/oidc").partition(".")
    assert state == q["state"] and len(state) >= 43
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=")
    assert q["code_challenge"] == digest.decode()


async def test_secure_cookie_follows_config(client, enabled, monkeypatch):
    monkeypatch.setenv("LUACH_COOKIE_SECURE", "1")
    r = await client.get("/api/auth/oidc/start")
    assert "secure" in r.headers["set-cookie"].lower()


async def test_success_signs_in_the_member(client, enabled):
    r = await _signin(client)
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert "luach_session=" in r.headers.get_list("set-cookie")[0] or any(
        h.startswith("luach_session=") for h in r.headers.get_list("set-cookie")
    )
    assert any(
        h.startswith("luach_oidc=") and "max-age=0" in h.lower()
        for h in r.headers.get_list("set-cookie")
    )
    me = await client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "robin"
    token_call = enabled.token_requests[0]
    assert token_call["auth"] == ("luach-client", "s3cret")
    assert token_call["timeout"] == 10
    data = token_call["data"]
    assert data["grant_type"] == "authorization_code" and data["code"] == "the-code"
    assert data["redirect_uri"] == "https://luach.test/api/auth/oidc/callback"
    assert data["code_verifier"]
    assert enabled.userinfo_requests[0]["headers"]["Authorization"] == "Bearer at-123"
    assert enabled.discovery_calls == 1  # cached between start and callback


async def test_secondary_email_matches(client, enabled):
    ana = users.member_by_email("ana@example.com")
    assert ana is not None
    users.add_email(ana.id, "ana.work@example.com")
    enabled.userinfo = {"email": "ANA.work@example.com", "groups": ["admins", "family"]}
    # An address nobody has confirmed names nobody: otherwise anyone who can edit
    # their own address at the identity provider signs in as whoever claimed it.
    assert _failed(await _signin(client))
    users.verify_address(users.start_verification(ana.id, "ana.work@example.com", "alias"))
    r = await _signin(client)
    assert r.headers["location"] == "/"
    assert (await client.get("/api/auth/me")).json()["username"] == "ana"


async def test_an_address_the_provider_has_not_verified_is_refused(client, enabled):
    enabled.userinfo = {
        "email": "ana@example.com",
        "email_verified": False,
        "groups": ["admins", "family"],
    }
    assert _failed(await _signin(client))


async def test_callback_without_cookie_fails(client, enabled):
    r = await client.get("/api/auth/oidc/callback?code=c&state=s")
    assert _failed(r) and _session_count() == 0
    assert enabled.token_requests == []


async def test_state_mismatch_fails(client, enabled):
    await _start(client)
    r = await client.get("/api/auth/oidc/callback?code=c&state=forged")
    assert _failed(r) and _session_count() == 0
    assert enabled.token_requests == []
    assert (await client.get("/api/auth/me")).status_code == 401
    # the cookie is gone, so a replay with the right state cannot follow
    assert client.cookies.get("luach_oidc", path="/api/auth/oidc") is None


async def test_malformed_cookie_and_missing_code_fail(client, enabled):
    client.cookies.set("luach_oidc", "nodot", domain="luach.test", path="/api/auth/oidc")
    assert _failed(await client.get("/api/auth/oidc/callback?code=c&state=nodot"))
    q = await _start(client)
    assert _failed(await client.get(f"/api/auth/oidc/callback?state={q['state']}"))
    assert _session_count() == 0


async def test_provider_error_fails(client, enabled):
    q = await _start(client)
    r = await client.get(f"/api/auth/oidc/callback?error=access_denied&state={q['state']}")
    assert _failed(r) and _session_count() == 0


async def test_token_endpoint_non_200_fails(client, enabled):
    enabled.token_status = 400
    assert _failed(await _signin(client))
    assert _session_count() == 0


@pytest.mark.parametrize(
    "tweak",
    [
        lambda idp: setattr(idp, "raise_on", "token"),
        lambda idp: setattr(idp, "raise_on", "userinfo"),
        lambda idp: setattr(idp, "token_payload", ValueError("not json")),
        lambda idp: setattr(idp, "token_payload", {"token_type": "Bearer"}),
        lambda idp: setattr(idp, "userinfo_status", 401),
        lambda idp: setattr(idp, "userinfo", ValueError("not json")),
        lambda idp: setattr(idp, "userinfo", ["not", "a", "dict"]),
        lambda idp: setattr(idp, "userinfo", {"groups": ["admins"]}),
    ],
)
async def test_provider_misbehaviour_fails(client, enabled, tweak):
    tweak(enabled)
    assert _failed(await _signin(client))
    assert _session_count() == 0


async def test_issuer_mismatch_fails(client, enabled):
    enabled.issuer = "https://evil.test/application/o/luach-signin/"
    r = await client.get("/api/auth/oidc/start")
    assert _failed(r)
    assert "luach_oidc" not in r.headers.get("set-cookie", "")
    # and a callback carrying a valid-looking cookie also refuses at discovery
    client.cookies.set("luach_oidc", "st.ver", domain="luach.test", path="/api/auth/oidc")
    assert _failed(await client.get("/api/auth/oidc/callback?code=c&state=st"))
    assert enabled.token_requests == [] and _session_count() == 0


@pytest.mark.parametrize(
    "tweak",
    [
        lambda idp: setattr(idp, "discovery_status", 500),
        lambda idp: setattr(idp, "raise_on", "discovery"),
    ],
)
async def test_discovery_failure_fails(client, enabled, tweak):
    tweak(enabled)
    assert _failed(await client.get("/api/auth/oidc/start"))


async def test_discovery_must_be_a_complete_json_document(client, enabled, monkeypatch):
    monkeypatch.setattr(
        oidc.requests, "get", lambda url, **kw: FakeResponse(200, ValueError("html"))
    )
    assert _failed(await client.get("/api/auth/oidc/start"))
    monkeypatch.setattr(
        oidc.requests, "get", lambda url, **kw: FakeResponse(200, {"issuer": ISSUER})
    )
    assert _failed(await client.get("/api/auth/oidc/start"))


async def test_not_in_required_group_fails(client, enabled, monkeypatch):
    enabled.userinfo = {"email": "robin@example.com", "groups": ["family"]}
    assert _failed(await _signin(client))
    enabled.userinfo = {"email": "robin@example.com"}
    assert _failed(await _signin(client))
    monkeypatch.setenv("LUACH_OIDC_REQUIRED_GROUP", "family")
    enabled.userinfo = {"email": "robin@example.com", "groups": ["family"]}
    assert (await _signin(client)).headers["location"] == "/"


async def test_unknown_email_fails_and_creates_nobody(client, enabled):
    with db.session() as s:
        before = s.query(db.User).count()
    enabled.userinfo = {"email": "stranger@example.com", "groups": ["admins"]}
    assert _failed(await _signin(client))
    with db.session() as s:
        assert s.query(db.User).count() == before
    assert _session_count() == 0


async def test_password_login_still_works_with_sso_enabled(client, enabled):
    r = await client.post(
        "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
    )
    assert r.status_code == 200
    assert (await client.get("/api/auth/me")).json()["username"] == "robin"


async def test_failures_never_log_secrets(client, enabled, caplog):
    enabled.token_status = 401
    caplog.set_level("DEBUG")
    assert _failed(await _signin(client))
    enabled.token_status = 200
    enabled.userinfo = {"email": "stranger@example.com", "groups": ["admins"]}
    assert _failed(await _signin(client))
    ours = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("luach"))
    assert "sso sign-in refused" in ours
    for secret in ("s3cret", "the-code", "at-123"):
        assert secret not in ours


OIDC_VARS = (
    "LUACH_OIDC_ISSUER",
    "LUACH_OIDC_CLIENT_ID",
    "LUACH_OIDC_CLIENT_SECRET",
    "LUACH_OIDC_REQUIRED_GROUP",
    "LUACH_OIDC_LABEL",
    "LUACH_OIDC_SCOPES",
    "LUACH_OIDC_GROUPS_CLAIM",
    "LUACH_OIDC_EMAIL_CLAIM",
    "LUACH_OIDC_REDIRECT_URI",
    "LUACH_OIDC_HTTP_TIMEOUT",
)


def test_settings_defaults(monkeypatch):
    for name in OIDC_VARS:
        monkeypatch.delenv(name, raising=False)
    cfg = config.oidc_settings()
    assert cfg.enabled is False
    assert cfg.required_group == "admins"
    assert cfg.label == "Sign in with single sign-on"
    assert cfg.scopes == "openid email profile groups"
    assert cfg.groups_claim == "groups" and cfg.email_claim == "email"
    assert cfg.redirect_uri == "https://luach.test/api/auth/oidc/callback"
    assert cfg.http_timeout == 10


def test_settings_redirect_uri_drops_the_app_url_trailing_slash(monkeypatch):
    monkeypatch.setenv("LUACH_APP_URL", "https://luach.test/")
    monkeypatch.delenv("LUACH_OIDC_REDIRECT_URI", raising=False)
    assert config.oidc_settings().redirect_uri == "https://luach.test/api/auth/oidc/callback"


def test_settings_overrides(monkeypatch):
    values = {
        "LUACH_OIDC_ISSUER": ISSUER,
        "LUACH_OIDC_CLIENT_ID": "cid",
        "LUACH_OIDC_CLIENT_SECRET": "sec",
        "LUACH_OIDC_REQUIRED_GROUP": "owners",
        "LUACH_OIDC_LABEL": "Use the house key",
        "LUACH_OIDC_SCOPES": "openid email roles",
        "LUACH_OIDC_GROUPS_CLAIM": "roles",
        "LUACH_OIDC_EMAIL_CLAIM": "mail",
        "LUACH_OIDC_REDIRECT_URI": "https://other.test/cb",
        "LUACH_OIDC_HTTP_TIMEOUT": "2.5",
    }
    for k, v in values.items():
        monkeypatch.setenv(k, v)
    cfg = config.oidc_settings()
    assert cfg.enabled is True
    assert (cfg.issuer, cfg.client_id, cfg.client_secret) == (ISSUER, "cid", "sec")
    assert cfg.required_group == "owners" and cfg.label == "Use the house key"
    assert cfg.scopes == "openid email roles"
    assert (cfg.groups_claim, cfg.email_claim) == ("roles", "mail")
    assert cfg.redirect_uri == "https://other.test/cb" and cfg.http_timeout == 2.5


@pytest.mark.parametrize("raw", ["soon", "0", "-3"])
def test_settings_bad_timeout_falls_back(monkeypatch, raw):
    monkeypatch.setenv("LUACH_OIDC_HTTP_TIMEOUT", raw)
    assert config.oidc_settings().http_timeout == 10


async def test_empty_required_group_disables_and_warns(client, enabled, monkeypatch, caplog):
    monkeypatch.setenv("LUACH_OIDC_REQUIRED_GROUP", "  ")
    caplog.set_level("WARNING")
    assert (await client.get("/api/auth/oidc/start")).status_code == 404
    assert (await client.get("/api/auth/oidc/callback?code=c&state=s")).status_code == 404
    assert (await client.get("/api/auth/status")).json()["sso"]["enabled"] is False
    assert "LUACH_OIDC_REQUIRED_GROUP is empty" in caplog.text
    assert enabled.discovery_calls == 0


async def test_overrides_drive_the_flow(client, enabled, monkeypatch):
    monkeypatch.setenv("LUACH_OIDC_LABEL", "Use the house key")
    monkeypatch.setenv("LUACH_OIDC_SCOPES", "openid email roles")
    monkeypatch.setenv("LUACH_OIDC_GROUPS_CLAIM", "roles")
    monkeypatch.setenv("LUACH_OIDC_EMAIL_CLAIM", "mail")
    monkeypatch.setenv("LUACH_OIDC_REQUIRED_GROUP", "owners")
    monkeypatch.setenv("LUACH_OIDC_REDIRECT_URI", "https://front.test/sso/cb")
    monkeypatch.setenv("LUACH_OIDC_HTTP_TIMEOUT", "3")
    assert (await client.get("/api/auth/status")).json()["sso"]["label"] == "Use the house key"
    q = await _start(client)
    assert q["scope"] == "openid email roles"
    assert q["redirect_uri"] == "https://front.test/sso/cb"
    enabled.userinfo = {"mail": "robin@example.com", "roles": ["owners"], "groups": []}
    r = await client.get(f"/api/auth/oidc/callback?code=the-code&state={q['state']}")
    assert r.headers["location"] == "/"
    call = enabled.token_requests[0]
    assert call["timeout"] == 3 and call["data"]["redirect_uri"] == "https://front.test/sso/cb"
    assert enabled.userinfo_requests[0]["timeout"] == 3
    # the default claim names are no longer consulted
    enabled.userinfo = {"email": "robin@example.com", "groups": ["owners"]}
    assert _failed(await _signin(client))


async def test_an_address_the_provider_does_not_say_it_verified_is_refused(client, enabled):
    enabled.complete = False
    enabled.userinfo = {"email": "robin@example.com", "sub": "u1", "groups": ["admins"]}
    assert _failed(await _signin(client))
    enabled.userinfo = {**enabled.userinfo, "email_verified": "true"}  # a string is not True
    assert _failed(await _signin(client))
    enabled.userinfo = {**enabled.userinfo, "email_verified": True}
    assert (await _signin(client)).headers["location"] == "/"


async def test_a_userinfo_without_a_subject_is_refused(client, enabled):
    enabled.complete = False
    enabled.userinfo = {"email": "robin@example.com", "email_verified": True, "groups": ["admins"]}
    assert _failed(await _signin(client))


async def test_after_the_first_sign_in_the_subject_decides(client, enabled):
    """An account at the provider that comes to show a member's address (changed there)
    does not become that member; the member's own account stays theirs whatever its
    address says."""
    enabled.complete = False
    robin = {"sub": "robin-at-idp", "email_verified": True, "groups": ["admins"]}
    enabled.userinfo = {**robin, "email": "robin@example.com"}
    assert (await _signin(client)).headers["location"] == "/"
    with db.session() as s:
        link = s.get(db.OidcLink, (ISSUER, "robin-at-idp"))
        assert link is not None and link.user_id == 1
    await client.post("/api/auth/logout")

    # Someone else's account at the provider now shows Robin's address.
    enabled.userinfo = {**robin, "sub": "someone-else", "email": "robin@example.com"}
    assert _failed(await _signin(client))

    # Robin's own account, its address changed at the provider: still Robin.
    enabled.userinfo = {**robin, "email": "robin.new@example.com"}
    assert (await _signin(client)).headers["location"] == "/"
    assert (await client.get("/api/auth/me")).json()["username"] == "robin"
    await client.post("/api/auth/logout")

    # And Robin's account showing Ana's address is Robin, not Ana.
    enabled.userinfo = {**robin, "email": "ana@example.com"}
    assert (await _signin(client)).headers["location"] == "/"
    assert (await client.get("/api/auth/me")).json()["username"] == "robin"


async def test_a_removed_member_takes_their_link_with_them(client, enabled):
    enabled.complete = False
    enabled.userinfo = {
        "sub": "ana-at-idp",
        "email": "ana@example.com",
        "email_verified": True,
        "groups": ["admins"],
    }
    assert (await _signin(client)).headers["location"] == "/"
    await client.post("/api/auth/logout")
    assert users.remove(2)
    with db.session() as s:
        assert s.get(db.OidcLink, (ISSUER, "ana-at-idp")) is None
    assert _failed(await _signin(client))

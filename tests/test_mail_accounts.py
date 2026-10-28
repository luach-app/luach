"""Each member's own mailbox: connected by them, searched only for them.

"I should not be able to see Alex's emails" — nor she mine. There is no shared
mailbox and no owner's override; the grant is stored encrypted; a connect finished
in someone else's session is refused."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient

from luach import db, mail_accounts
from luach.agent import context, tools
from luach.app import create_app
from luach.ingest import gmail

TZ = "America/New_York"


@pytest.fixture
def google(monkeypatch, tmp_path):
    """A web OAuth client, and a Google that hands out one token per grant."""
    client = tmp_path / "mail-client.json"
    client.write_text(json.dumps({"web": {"client_id": "cid", "client_secret": "sec"}}))
    monkeypatch.setenv("LUACH_MAIL_OAUTH_CLIENT", str(client))
    monkeypatch.setenv("LUACH_APP_URL", "https://luach.test")
    posted: list[tuple[str, dict]] = []

    def fake_post(url, fields):
        posted.append((url, fields))
        if fields.get("grant_type") == "authorization_code":
            return {
                "access_token": "at-" + fields["code"],
                "refresh_token": "rt-" + fields["code"],
                "scope": mail_accounts.SCOPE,
                "expires_in": 3600,
            }
        if fields.get("grant_type") == "refresh_token":
            return {"access_token": "at-for-" + fields["refresh_token"], "expires_in": 3600}
        return {}

    monkeypatch.setattr(mail_accounts, "_post", fake_post)
    monkeypatch.setattr(
        mail_accounts, "_gmail_get", lambda path, token: {"emailAddress": f"{token}@gmail.test"}
    )
    mail_accounts._access.clear()
    mail_accounts._held.clear()
    mail_accounts._household = None
    # The mailboxes this Google signs in to are the members' own, confirmed here.
    _own(1, "at-robin@gmail.test")
    _own(2, "at-alex@gmail.test")
    return posted


def _own(user_id: int, address: str) -> None:
    from luach.auth import users

    users.add_email(user_id, address)
    users.verify_address(users.start_verification(user_id, address, "alias"))


def _connect(user_id: int, code: str) -> str:
    begun = mail_accounts.start(user_id)
    state = parse_qs(urlparse(begun.url).query)["state"][0]
    return mail_accounts.finish(user_id, begun.cookie, code, state)


def test_the_consent_asks_for_read_only_mail_with_pkce(google):
    begun = mail_accounts.start(2)
    q = parse_qs(urlparse(begun.url).query)
    assert q["scope"] == [mail_accounts.SCOPE] and "readonly" in mail_accounts.SCOPE
    assert q["redirect_uri"] == ["https://luach.test/api/mail/callback"]
    assert q["code_challenge_method"] == ["S256"] and q["access_type"] == ["offline"]
    assert begun.cookie.startswith("2.")


def test_google_always_asks_which_account_and_offers_the_households_first(google, monkeypatch):
    """Without the chooser Google used the browser's personal Gmail, and the Internal
    app refused it with org_internal."""
    from luach.auth import users

    q = parse_qs(urlparse(mail_accounts.start(1).url).query)
    assert q["prompt"] == ["select_account consent"]
    assert "hd" not in q and "login_hint" not in q, "no domain set: any account"

    monkeypatch.setenv("LUACH_MAIL_DOMAIN", "Harper.test")
    users.add_email(1, "robin@harper.test")
    users.verify_address(users.start_verification(1, "robin@harper.test", "alias"))
    users.make_primary(1, "robin@harper.test")
    q = parse_qs(urlparse(mail_accounts.start(1).url).query)
    assert q["hd"] == ["harper.test"] and q["login_hint"] == ["robin@harper.test"]
    q = parse_qs(urlparse(mail_accounts.start(2).url).query)
    assert q["hd"] == ["harper.test"] and "login_hint" not in q, "no address there yet"


def test_the_grant_is_stored_encrypted_and_for_that_member(google):
    assert _connect(2, "alex") == "at-alex@gmail.test"
    with db.session() as s:
        row = s.get(db.MailConnection, 2)
        assert row is not None and "rt-alex" not in row.grant
    assert mail_accounts.status(2) == {
        "connected": True,
        "address": "at-alex@gmail.test",
        "via": "own",
        "can_connect": True,
        "lost": None,
    }
    assert mail_accounts.access_token(2) == "at-for-rt-alex"


def test_a_connect_finished_in_someone_elses_session_is_refused(google):
    begun = mail_accounts.start(2)
    state = parse_qs(urlparse(begun.url).query)["state"][0]
    with pytest.raises(mail_accounts.ConnectFailed, match="different member"):
        mail_accounts.finish(1, begun.cookie, "x", state)
    with pytest.raises(mail_accounts.ConnectFailed, match="state"):
        mail_accounts.finish(2, begun.cookie, "x", "not-the-state")
    assert not mail_accounts.connected(2)


def test_each_member_reaches_only_their_own_mailbox(google, monkeypatch):
    """Two connections; each search goes out with the asker's token and no other."""
    _connect(2, "alex")
    seen: list[str | None] = []

    def fake_api(path, method="GET", payload=None, query=None, token=None):
        seen.append(token)
        return {"messages": []}

    monkeypatch.setattr(gmail, "_api", fake_api)
    gmail.search(2, "flight")
    assert seen == ["at-for-rt-alex"]
    with pytest.raises(mail_accounts.NotConnected):
        gmail.search(1, "flight")  # the owner has no household grant here, and no row
    assert seen == ["at-for-rt-alex"], "the owner's search reached someone's mailbox"


def test_the_owner_household_grant_is_the_owners_only(google, monkeypatch, tmp_path):
    for name in ("client", "tokens"):
        (tmp_path / f"{name}.json").write_text("{}")
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_CLIENT", str(tmp_path / "client.json"))
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_TOKENS", str(tmp_path / "tokens.json"))
    monkeypatch.setattr(gmail, "_token", lambda: "household-token")
    assert mail_accounts.access_token(1) == "household-token"
    assert mail_accounts.status(1)["via"] == "household"
    with pytest.raises(mail_accounts.NotConnected):
        mail_accounts.access_token(2)


def test_the_household_grant_is_named_and_the_owners_own_takes_over(google, monkeypatch, tmp_path):
    """ "Connected — the household mailbox" left the owner guessing whose it was, and
    with no way to connect their own."""
    for name in ("client", "tokens"):
        (tmp_path / f"{name}.json").write_text("{}")
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_CLIENT", str(tmp_path / "client.json"))
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_TOKENS", str(tmp_path / "tokens.json"))
    monkeypatch.setattr(gmail, "_token", lambda: "household")
    st = mail_accounts.status(1)
    assert st["via"] == "household" and st["address"] == "household@gmail.test"
    assert st["can_connect"] is True, "the owner may still connect their own"

    _connect(1, "robin")
    st = mail_accounts.status(1)
    assert st["via"] == "own" and st["address"] == "at-robin@gmail.test"
    assert mail_accounts.access_token(1) != "household"


def test_disconnect_forgets_it_here_and_revokes_it_at_google(google):
    _connect(2, "alex")
    assert mail_accounts.disconnect(2) is True
    assert not mail_accounts.connected(2)
    assert ("https://oauth2.googleapis.com/revoke", {"token": "rt-alex"}) in google
    assert mail_accounts.disconnect(2) is False


def test_a_grant_the_key_can_no_longer_open_is_not_read(google, monkeypatch):
    _connect(2, "alex")
    from cryptography.fernet import Fernet

    monkeypatch.setenv("LUACH_MAIL_KEY", Fernet.generate_key().decode())
    mail_accounts._access.clear()
    with pytest.raises(mail_accounts.NotConnected, match="connect again"):
        mail_accounts.access_token(2)


def test_the_chat_tells_an_unconnected_member_how(google, calendar):
    context.set_turn(context.Turn(calendar=calendar, user_id=2, principal="ana", timezone=TZ))
    try:
        fn = getattr(tools.search_email, "fn", tools.search_email)
        result = fn("flight")
    finally:
        context.set_turn(None)
    assert "Settings" in result["error"] and "own" in result["error"]


async def test_the_routes_act_on_the_caller_only(google, tmp_path):
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://luach.test") as c:
        r = await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        assert r.status_code == 200
        assert (await c.get("/api/mail")).json()["connected"] is False
        r = await c.get("/api/mail/connect")
        assert r.status_code == 302 and r.headers["location"].startswith(
            "https://accounts.google.com/"
        )
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        r = await c.get(f"/api/mail/callback?code=robin&state={state}")
        assert r.status_code == 302 and r.headers["location"] == "/?tab=settings&mail=connected"
        st = (await c.get("/api/mail")).json()
        assert st["connected"] and st["via"] == "own"
        assert (await c.delete("/api/mail")).json()["connected"] is False
        assert (await c.delete("/api/mail")).status_code == 404
        r = await c.get("/api/mail/callback?code=x&state=forged")
        assert r.headers["location"] == "/?tab=settings&mail=failed"


async def test_a_consent_opened_in_a_popup_comes_back_saying_so(google, tmp_path):
    """The page Google returns to closes itself in a popup rather than loading the app."""
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://luach.test") as c:
        await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        r = await c.get("/api/mail/connect?popup=1")
        assert r.status_code == 302 and "luach_mail_popup" in r.headers.get("set-cookie", "")
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        r = await c.get(f"/api/mail/callback?code=robin&state={state}")
        assert r.headers["location"] == "/?tab=settings&mail=connected&popup=1"
        # One popup's flag does not follow the next connect made in the whole window.
        await c.delete("/api/mail")
        r = await c.get("/api/mail/connect")
        state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
        r = await c.get(f"/api/mail/callback?code=robin&state={state}")
        assert r.headers["location"] == "/?tab=settings&mail=connected"


async def test_a_connect_the_app_started_needs_no_session_in_the_browser(google, tmp_path):
    """The iPhone app's browser sheet has no luach cookie: the state itself says whose
    connect it is, sealed, and the way back is the app's own scheme."""
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://luach.test") as c:
        await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        r = await c.post("/api/mail/connect/app")
        assert r.status_code == 200
        url = r.json()["url"]
    q = parse_qs(urlparse(url).query)
    state = q["state"][0]
    assert url.startswith("https://accounts.google.com/") and q["code_challenge_method"] == ["S256"]
    assert state.startswith(mail_accounts.APP_STATE)
    # The verifier is inside, but not readable: Google sees the state.
    sealed = mail_accounts._fernet().decrypt(state[len(mail_accounts.APP_STATE) :].encode())
    assert sealed.decode().startswith("1.") and sealed.decode()[2:] not in state

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://luach.test"
    ) as sheet:
        r = await sheet.get(f"/api/mail/callback?code=robin&state={state}")
        assert r.status_code == 302
        assert "luach_session" not in r.headers.get("set-cookie", "")
    back = urlparse(r.headers["location"])
    assert f"{back.scheme}://{back.netloc}" == "luach://mail"
    q = parse_qs(back.query)
    assert q["mail"] == ["confirm"] and len(q["nonce"][0]) >= 32
    # Nothing is stored until the app claims it with the session that started it.
    assert not mail_accounts.status(1)["connected"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://luach.test") as c:
        await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        r = await c.post("/api/mail/connect/app/finish", json={"nonce": q["nonce"][0]})
        assert r.status_code == 200, r.text
        assert r.json()["connected"] and r.json()["address"] == "at-robin@gmail.test"
        # Once.
        r = await c.post("/api/mail/connect/app/finish", json={"nonce": q["nonce"][0]})
        assert r.status_code == 409


async def test_an_app_state_that_does_not_open_connects_nothing(google, tmp_path):
    import time

    app = create_app(static_dir=tmp_path / "nope")
    expired = (
        mail_accounts.APP_STATE
        + mail_accounts._fernet()
        .encrypt_at_time(b"1.verifier", int(time.time()) - mail_accounts.COOKIE_MAX_AGE - 5)
        .decode()
    )
    gone = mail_accounts.APP_STATE + mail_accounts._fernet().encrypt(b"999.verifier").decode()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://luach.test"
    ) as sheet:
        for state in (mail_accounts.APP_STATE + "forged", expired, gone):
            r = await sheet.get(f"/api/mail/callback?code=robin&state={state}")
            assert r.status_code == 302 and r.headers["location"] == "luach://mail?mail=failed"
        real = parse_qs(urlparse(mail_accounts.start(1, app=True).url).query)["state"][0]
        r = await sheet.get(f"/api/mail/callback?error=access_denied&state={real}")
        assert r.headers["location"] == "luach://mail?mail=failed"
        # A connect from the web still needs the session it was started in.
        r = await sheet.get("/api/mail/callback?code=robin&state=web-state")
        assert r.status_code == 401
    assert not mail_accounts.status(1)["connected"]


def test_an_app_connect_sets_no_cookie(google):
    assert mail_accounts.start(1, app=True).cookie == ""


def _refusing(google, monkeypatch, error: str, code: int = 400):
    """Google's token endpoint refusing every refresh with `error`."""
    import io
    import urllib.error

    real = mail_accounts._post

    def post(url, fields):
        if fields.get("grant_type") == "refresh_token":
            raise urllib.error.HTTPError(
                url, code, "Bad Request", {}, io.BytesIO(json.dumps({"error": error}).encode())
            )
        return real(url, fields)

    monkeypatch.setattr(mail_accounts, "_post", post)


def test_a_grant_google_refuses_for_good_is_forgotten(google, monkeypatch):
    """Made Internal, revoked, a password change: asking again every pass changes nothing."""
    _connect(2, "alex")
    mail_accounts._access.clear()
    _refusing(google, monkeypatch, "invalid_grant")
    with pytest.raises(mail_accounts.NotConnected, match="no longer accepts"):
        mail_accounts.access_token(2)
    assert mail_accounts.status(2)["connected"] is False
    with db.session() as s:
        assert s.get(db.MailConnection, 2) is None


def test_the_owner_falls_back_to_the_household_mailbox(google, monkeypatch, tmp_path):
    for name in ("client", "tokens"):
        (tmp_path / f"{name}.json").write_text("{}")
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_CLIENT", str(tmp_path / "client.json"))
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_TOKENS", str(tmp_path / "tokens.json"))
    monkeypatch.setattr(gmail, "_token", lambda: "household")
    _connect(1, "robin")
    mail_accounts._access.clear()
    _refusing(google, monkeypatch, "org_internal", 403)
    assert mail_accounts.access_token(1) == "household"
    assert mail_accounts.status(1)["via"] == "household"


def test_a_passing_failure_is_not_a_refusal(google, monkeypatch):
    """A 5xx or an unknown error keeps the grant: it may well work next time."""
    import urllib.error

    _connect(2, "alex")
    mail_accounts._access.clear()
    _refusing(google, monkeypatch, "backendError", 503)
    with pytest.raises(urllib.error.HTTPError):
        mail_accounts.access_token(2)
    assert mail_accounts.status(2)["connected"] is True


async def _app_nonce(app, user_id: int, code: str) -> str:
    state = parse_qs(urlparse(mail_accounts.start(user_id, app=True).url).query)["state"][0]
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://luach.test"
    ) as sheet:
        r = await sheet.get(f"/api/mail/callback?code={code}&state={state}")
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["mail"] == ["confirm"], r.headers["location"]
    return q["nonce"][0]


async def test_an_app_connect_claimed_by_another_member_stores_nothing(google, tmp_path):
    """Robin's consent link, finished on Ana's phone: Ana's app gets the nonce, but it is
    Robin's connect, so Ana's session cannot claim it -- and the grant is revoked."""
    app = create_app(static_dir=tmp_path / "nope")
    nonce = await _app_nonce(app, 1, "robin")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://luach.test") as c:
        await c.post(
            "/api/auth/login", json={"username": "ana", "password": "another good password"}
        )
        r = await c.post("/api/mail/connect/app/finish", json={"nonce": nonce})
        assert r.status_code == 409
        assert (
            await c.post("/api/mail/connect/app/finish", json={"nonce": "made-up"})
        ).status_code == 409
        assert (await c.post("/api/mail/connect/app/finish", json={})).status_code == 400
    assert not mail_accounts.connected(1) and not mail_accounts.connected(2)
    assert any(f.get("token") == "rt-robin" for _, f in google), "revoked at Google"
    # Without a session at all, the claim is not even heard.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://luach.test") as c:
        nonce = await _app_nonce(app, 1, "robin")
        assert (
            await c.post("/api/mail/connect/app/finish", json={"nonce": nonce})
        ).status_code == 401


def test_a_held_app_grant_expires(google, monkeypatch):
    import time

    state = parse_qs(urlparse(mail_accounts.start(1, app=True).url).query)["state"][0]
    nonce = mail_accounts.finish_in_app("robin", state)
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + mail_accounts.COOKIE_MAX_AGE + 1)
    with pytest.raises(mail_accounts.ConnectFailed, match="too old"):
        mail_accounts.complete_in_app(1, nonce)
    assert not mail_accounts.connected(1)


async def test_someone_elses_gmail_is_refused_on_the_web_and_from_the_app(google, tmp_path):
    """A consent link sent to someone else: they sign in to their own Gmail, and it
    would have become the sender's. The mailbox must be one of the member's addresses."""
    with pytest.raises(mail_accounts.ConnectFailed, match="confirmed addresses") as refused:
        _connect(1, "alex")  # Google signed in as at-alex@gmail.test, which is Ana's
    assert refused.value.reason == mail_accounts.NOT_YOURS
    assert not mail_accounts.connected(1)
    assert any(f.get("token") == "rt-alex" for _, f in google), "revoked at Google"

    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://luach.test") as c:
        await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        state = parse_qs(urlparse((await c.get("/api/mail/connect")).headers["location"]).query)[
            "state"
        ][0]
        r = await c.get(f"/api/mail/callback?code=stranger&state={state}")
        assert r.headers["location"] == "/?tab=settings&mail=failed&reason=not-yours"

        app_state = parse_qs(urlparse(mail_accounts.start(1, app=True).url).query)["state"][0]
        r = await c.get(f"/api/mail/callback?code=stranger&state={app_state}")
        assert r.headers["location"] == "luach://mail?mail=failed&reason=not-yours"
    assert not mail_accounts.connected(1)


def test_an_unconfirmed_address_is_not_yet_yours(google):
    from luach.auth import users

    users.add_email(1, "at-later@gmail.test")  # claimed, never confirmed
    with pytest.raises(mail_accounts.ConnectFailed, match="confirmed addresses"):
        _connect(1, "later")
    users.verify_address(users.start_verification(1, "at-later@gmail.test", "alias"))
    assert _connect(1, "later") == "at-later@gmail.test"


def test_a_mailbox_gmail_will_not_name_is_refused(google, monkeypatch):
    def broken(path, token):
        raise OSError("down")

    monkeypatch.setattr(mail_accounts, "_gmail_get", broken)
    with pytest.raises(mail_accounts.ConnectFailed, match="did not say"):
        _connect(1, "robin")
    assert not mail_accounts.connected(1)


def test_devs_gmail_stand_in_signs_in_as_the_member_luach_hinted(google, monkeypatch):
    """dev's iPhone and UI tests connect through fixtures/gmail-fake. luach connects a
    mailbox only when it is the member's own, so the stand-in signs in as whoever the
    code names (the consent page puts luach's login_hint there): luach's real exchange
    and profile read, over HTTP, against the stand-in."""
    import importlib.util
    import threading
    from http.server import HTTPServer
    from pathlib import Path

    path = Path(__file__).parents[1] / "fixtures" / "gmail-fake" / "app.py"
    spec = importlib.util.spec_from_file_location("gmail_fake", path)
    assert spec and spec.loader
    fake = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fake)
    server = HTTPServer(("127.0.0.1", 0), fake.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        monkeypatch.setenv("LUACH_GOOGLE_TOKEN_URL", f"{base}/token")
        monkeypatch.setenv("LUACH_GMAIL_API", f"{base}/gmail/v1/users/me")
        # The real calls, not the google fixture's stand-ins for them.
        monkeypatch.setattr(mail_accounts, "_post", _real_post)
        monkeypatch.setattr(mail_accounts, "_gmail_get", _real_gmail_get)
        with pytest.raises(mail_accounts.ConnectFailed, match="confirmed addresses"):
            _connect(1, "fixture-code")  # the stand-in's own mailbox is nobody's here
        assert _connect(1, "fixture-code~robin@example.com") == "robin@example.com"
        assert mail_accounts.access_token(1) == "fixture-access-token~robin@example.com"
    finally:
        server.shutdown()


_real_post = mail_accounts._post
_real_gmail_get = mail_accounts._gmail_get


# --- a grant Google took back is told, not dropped silently ----------------------


@pytest.fixture
def told(monkeypatch):
    """Every push and email luach sends, as (kind, to, title, body)."""
    from luach import mailer, push

    sent: list[tuple[str, object, str, str]] = []
    monkeypatch.setattr(
        push,
        "notify_user",
        lambda user_id, title, body, url="/": sent.append(("push", user_id, title, url)) or 1,
    )
    monkeypatch.setattr(
        mailer,
        "send",
        lambda to, subject, text, html=None: sent.append(("mail", to, subject, text)),
    )
    return sent


def test_a_grant_google_refuses_tells_the_member_once(google, monkeypatch, told):
    """Personal Gmail in Google's testing mode is refused after seven days: the scan
    stopped every week and nobody knew."""
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    _connect(2, "alex")
    mail_accounts._access.clear()
    _refusing(google, monkeypatch, "invalid_grant")
    with pytest.raises(mail_accounts.NotConnected):
        mail_accounts.access_token(2)
    assert [t[:3] for t in told] == [
        ("push", 2, "Gmail disconnected — reconnect"),
        ("mail", "ana@example.com", "Gmail disconnected — reconnect"),
    ]
    assert told[0][3] == "/?tab=settings"
    assert "at-alex@gmail.test" in told[1][3] and "https://luach.test/?tab=settings" in told[1][3]
    st = mail_accounts.status(2)
    assert st["connected"] is False
    assert st["lost"]["address"] == "at-alex@gmail.test" and st["lost"]["via"] == "own"
    # The next pass finds nothing to refresh, and says nothing more.
    with pytest.raises(mail_accounts.NotConnected):
        mail_accounts.access_token(2)
    assert len(told) == 2
    # Somebody else is not told, and sees nothing.
    assert mail_accounts.status(1)["lost"] is None

    # Reconnecting clears it.
    _connect(2, "alex")
    assert mail_accounts.status(2)["lost"] is None


def test_without_outgoing_mail_the_member_is_still_pushed(google, monkeypatch, told):
    _connect(2, "alex")
    mail_accounts._access.clear()
    _refusing(google, monkeypatch, "invalid_grant")
    with pytest.raises(mail_accounts.NotConnected):
        mail_accounts.access_token(2)
    assert [t[0] for t in told] == ["push"]


def test_the_lost_mail_card_escapes_the_address():
    from luach import mail_templates

    text, html = mail_templates.mail_lost("<b>x</b>@gmail.test", "https://luach.test/?tab=settings")
    assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html
    assert "Reconnect" in html and "https://luach.test/?tab=settings" in text
    text, _ = mail_templates.mail_lost("", None)
    assert "your Gmail" in text and "http" not in text


def _household(monkeypatch, tmp_path, answer):
    """The household grant on disk, and Google's token endpoint answering `answer`."""
    import io
    import urllib.error

    (tmp_path / "client.json").write_text(json.dumps({"client_id": "c", "client_secret": "s"}))
    (tmp_path / "tokens.json").write_text(json.dumps({"refresh_token": "household-rt"}))
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_CLIENT", str(tmp_path / "client.json"))
    monkeypatch.setenv("LUACH_GOOGLE_OAUTH_TOKENS", str(tmp_path / "tokens.json"))
    gmail._access.clear()

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def urlopen(req, timeout=None):
        if answer[0] == "refuse":
            raise urllib.error.HTTPError(
                req.full_url, 400, "Bad", {}, io.BytesIO(b'{"error": "invalid_grant"}')
            )
        if answer[0] == "down":
            raise urllib.error.HTTPError(req.full_url, 503, "Down", {}, io.BytesIO(b"{}"))
        return Resp(json.dumps({"access_token": "household-at", "expires_in": 3600}).encode())

    monkeypatch.setattr(gmail.urllib.request, "urlopen", urlopen)


def test_the_household_door_refused_tells_the_owner(google, monkeypatch, tmp_path, told):
    import urllib.error

    answer = ["refuse"]
    _household(monkeypatch, tmp_path, answer)
    with pytest.raises(urllib.error.HTTPError):
        gmail._token()
    with pytest.raises(urllib.error.HTTPError):
        gmail._token()  # the next pass: still refused, not told again
    assert [(t[0], t[1]) for t in told] == [("push", 1)], "only the owner, and once"
    st = mail_accounts.status(1)
    assert st["connected"] is False and st["lost"]["via"] == "household"
    assert mail_accounts.status(2)["lost"] is None, "the door's grant is the owner's business"

    # New tokens on disk: it works again, and the notice goes.
    answer[0] = "ok"
    assert gmail._token() == "household-at"
    st = mail_accounts.status(1)
    assert st["connected"] is True and st["lost"] is None


def test_a_passing_household_failure_tells_nobody(google, monkeypatch, tmp_path, told):
    import urllib.error

    _household(monkeypatch, tmp_path, ["down"])
    with pytest.raises(urllib.error.HTTPError):
        gmail._token()
    assert told == []
    assert mail_accounts.status(1)["lost"] is None


async def test_the_mail_route_shows_the_loss_and_dismisses_it(google, monkeypatch, tmp_path, told):
    _connect(1, "robin")
    mail_accounts._access.clear()
    _refusing(google, monkeypatch, "invalid_grant")
    with pytest.raises(mail_accounts.NotConnected):
        mail_accounts.access_token(1)
    app = create_app(static_dir=tmp_path / "nope")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://luach.test") as c:
        await c.post(
            "/api/auth/login", json={"username": "robin", "password": "correct horse battery"}
        )
        st = (await c.get("/api/mail")).json()
        assert st["connected"] is False and st["lost"]["address"] == "at-robin@gmail.test"
        r = await c.delete("/api/mail")
        assert r.status_code == 200 and r.json()["lost"] is None
        assert (await c.delete("/api/mail")).status_code == 404
    assert mail_accounts.status(1)["lost"] is None


def test_a_dismissed_household_loss_is_not_told_again(google, monkeypatch, tmp_path, told):
    import urllib.error

    _household(monkeypatch, tmp_path, ["refuse"])
    with pytest.raises(urllib.error.HTTPError):
        gmail._token()
    assert mail_accounts.dismiss_lost(1) is True
    assert mail_accounts.status(1)["lost"] is None
    with pytest.raises(urllib.error.HTTPError):
        gmail._token()
    assert len(told) == 1, "dismissed, it must not come back on every pass"
    assert mail_accounts.dismiss_lost(2) is False

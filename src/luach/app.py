"""The FastAPI app: the auth wall, the routers, the static PWA, the loops."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

from luach import __version__, config, db, loops_lock, memory_health, model_menu, public_pages
from luach.agent import control
from luach.auth import api_key, csrf, sessions, throttle
from luach.auth.current import Caller, set_caller
from luach.routes import (
    agent,
    authn,
    board,
    booking,
    calendar,
    family,
    health,
    household,
    members,
    models,
    push,
    transcribe,
)
from luach.routes import control as control_routes
from luach.routes import mail as mail_routes
from luach.routes import memory as memory_routes
from luach.routes import tasks as task_routes
from luach.routes.shared import client_ip

logger = logging.getLogger(__name__)

#: The throttle's name for wrong x-luach-key values, counted per address.
KEY_THROTTLE = "x-luach-key"

OPEN_PATHS = {
    "/api/health",
    "/api/auth/status",
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/logout",
    "/api/auth/forgot",
    "/api/auth/reset",
    # A confirmation link is read on whichever device opened the mail, which is
    # often not the one that is signed in. The token is the proof.
    "/api/auth/verify",
    "/api/auth/accept",
    "/api/auth/passkeys/login/options",
    "/api/auth/passkeys/login/verify",
    "/api/auth/oidc/config",
    "/api/auth/oidc/start",
    "/api/auth/oidc/callback",
    # Google comes back here. A connect from the web carries the session and is checked
    # against it by the route; one the iPhone app started is proven by its sealed state.
    "/api/mail/callback",
    "/api/transcribe/status",
    "/api/push/key",
}


# The usual hardening set for a site on the open internet, sent on every response whatever
# proxy sits in front. connect-src stays 'self': the web app talks to its own API only.
# frame-ancestors 'none' and X-Frame-Options together, for old and new browsers.
SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (
        b"content-security-policy",
        b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        b"img-src 'self' data: https:; connect-src 'self'; font-src 'self' data:; "
        b"frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    ),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(self), geolocation=(), payment=()"),
    (b"x-frame-options", b"DENY"),
    (b"strict-transport-security", b"max-age=31536000; includeSubDomains"),
)


class SecurityHeaders:
    """Add the browser hardening headers to every response. Pure ASGI, like AuthWall."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Any) -> None:
            if message["type"] == "http.response.start":
                present = {k.lower() for k, _ in message.get("headers", [])}
                extra = [(k, v) for k, v in SECURITY_HEADERS if k not in present]
                message = {**message, "headers": list(message.get("headers", [])) + extra}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class AuthWall:
    """Resolve the caller once per request. Pure ASGI so streaming passes untouched.

    Cookie sessions map to members. The service key maps to the owner, named
    by LUACH_API_KEY_NAME on the audit trail, which is also the door its requests
    arrive through. The agent platform's read-only key (LUACH_TULIP_KEY) maps to
    the owner as "tulip", restricted to ``api_key.TULIP_ALLOWED`` (refused here
    otherwise). The service key is refused the routes in ``api_key.SERVICE_REFUSED``,
    and wrong keys are throttled per address. API paths not in OPEN_PATHS and not
    `/api/auth/invite/*` or `/api/book/*` (the public booking page) require one or the other.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        # Latin-1, as HTTP and Starlette have it: any byte decodes, so a header nobody
        # expected is a header that does not match rather than a 500.
        headers = {
            k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
        }
        caller: Caller | None = None
        presented = headers.get(api_key.HEADER)
        if presented:
            # A key is long and random (config.check_service_keys), so this is not what
            # keeps it safe; it is what makes guessing at it loud and slow.
            ip = client_ip(Request(scope))
            if wait := throttle.locked(KEY_THROTTLE, ip):
                response = JSONResponse(
                    {"error": "too many attempts; try again later", "retry_after": wait},
                    status_code=429,
                )
                await response(scope, receive, send)
                return
            if not (api_key.matches(presented) or api_key.matches_tulip(presented)):
                throttle.failed(KEY_THROTTLE, ip)
        if api_key.matches(presented):
            owner = db.owner_id()
            if owner is not None:
                name = config.api_key_name()
                caller = Caller(user_id=owner, principal=name, via_key=True, door=name)
        elif api_key.matches_tulip(presented):
            owner = db.owner_id()
            if owner is not None:
                caller = Caller(
                    user_id=owner,
                    principal=config.TULIP_PRINCIPAL,
                    via_key=True,
                    door="tulip",
                    restricted=True,
                )
        if caller is None:
            cookie = headers.get("cookie", "")
            token = None
            for part in cookie.split(";"):
                name, _, value = part.strip().partition("=")
                if name == sessions.COOKIE_NAME:
                    token = value
            user_id = sessions.authenticate(token)
            if user_id is not None:
                caller = Caller(user_id=user_id, principal=str(user_id))
        set_caller(caller)
        path = scope.get("path", "")
        method = scope.get("method", "GET")
        # A change must come from luach's own pages or from outside a browser (csrf.py).
        # A service key is not a browser's credential, so its callers are not asked.
        if not (caller is not None and caller.via_key) and (
            refused := csrf.refusal(method, path, headers, forwarded_host=_forwarded_host(scope))
        ):
            response = JSONResponse({"error": refused[1]}, status_code=refused[0])
            await response(scope, receive, send)
            return
        if (
            caller is not None
            and caller.via_key
            and not caller.restricted
            and not api_key.service_may(method, path)
        ):
            response = JSONResponse(
                {"error": "the service key cannot change members, sign-in, mail or screens"},
                status_code=403,
            )
            await response(scope, receive, send)
            return
        if caller is not None and caller.restricted and not api_key.tulip_may(method, path):
            response = JSONResponse(
                {"error": "the tulip key may only read and talk to the agent"}, status_code=403
            )
            await response(scope, receive, send)
            return
        if (
            path.startswith("/api/")
            and caller is None
            and path not in OPEN_PATHS
            and not path.startswith("/api/auth/invite/")
            and not path.startswith("/api/book/")
            # The house board carries its own token, checked by its routes.
            and not path.startswith("/api/board/")
        ):
            response = JSONResponse({"error": "sign in first"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _forwarded_host(scope: Scope) -> str:
    """X-Forwarded-Host, when a trusted proxy (LUACH_TRUSTED_PROXIES) sent it."""
    from luach.routes.shared import _trusted_peer

    client = scope.get("client")
    if not client or not _trusted_peer(str(client[0])):
        return ""
    for k, v in scope.get("headers", []):
        if k.lower() == b"x-forwarded-host":
            return str(v.decode("latin-1").split(",")[0].strip())
    return ""


async def _purge_loop() -> None:
    from luach.auth import passkeys

    while True:
        try:
            sessions.purge_expired()
            passkeys.purge_expired()
            await _purge_old_threads()
        except Exception:
            logger.exception("session purge failed")
        await asyncio.sleep(3600)


async def _purge_old_threads() -> None:
    """Sweep up conversations nobody has come back to.

    A thread is working memory. What is worth keeping about a person was saved
    deliberately by the memory tool and is not in here, so this can be a plain
    delete — of the rows and of the model-side state beside them, which is a
    directory per thread on the same volume and would otherwise grow for ever.
    """
    days = config.thread_retention_days()
    if days <= 0:
        return
    from luach.agent import runtime

    cutoff = db.utcnow() - timedelta(days=days)
    with db.session() as s:
        stale = s.execute(select(db.Thread).where(db.Thread.updated_at < cutoff)).scalars().all()
        ids = [t.id for t in stale]
        for t in stale:
            s.delete(t)
    for tid in ids:
        await runtime.forget_thread(tid)
    if ids:
        logger.info("purged %d conversations older than %d days", len(ids), days)


async def _busy_loop() -> None:
    """Re-read the members' work calendars on a timer: a booking page must not
    wait on someone else's server, and a feed that is down costs freshness only."""
    from luach import busy

    while True:
        try:
            busy.refresh_for()
        except Exception:
            logger.exception("busy: refresh failed")
        await asyncio.sleep(busy.REFRESH_MINUTES * 60)


async def _reminder_loop() -> None:
    """Say the things members asked to be told before they happen."""
    from luach import reminders

    while True:
        try:
            reminders.run_once()
            reminders.purge()
        except Exception:
            logger.exception("reminders: pass failed")
        await asyncio.sleep(reminders.TICK_MINUTES * 60)


async def _mail_loop() -> None:
    from luach.ingest import gmail

    minutes = config.gmail_poll_minutes()
    while True:
        try:
            # Without a model every mail would be read and nothing found in it.
            if gmail.configured() and model_menu.ready():
                await gmail.process_once()
        except Exception:
            logger.exception("email door failed")
        await asyncio.sleep(max(60, minutes * 60))


async def _scan_loop() -> None:
    from luach.ingest import mail_scan

    while True:
        try:
            if model_menu.ready():
                await mail_scan.scan_once()
        except Exception:
            logger.exception("mail scan failed")
        await asyncio.sleep(max(60, config.mail_scan_minutes() * 60))


def calendar_line() -> str:
    """The calendar in the startup line: where events really live."""
    backend = config.calendar_backend()
    if backend == "local":
        return "local (luach's own database)"
    if backend == "fake":
        return "fake (in memory, lost on restart)"
    auth = config.calendar_auth()
    if auth not in ("sa", "oauth"):
        auth = "oauth" if config.google_oauth_client() and config.google_oauth_tokens() else "sa"
    return f"google ({config.google_calendar_id() or 'no calendar id'}, {auth})"


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    config.load_credentials()
    # A calendar luach cannot use stops it here, saying why, rather than at the first
    # request, or (as it once did) by keeping the household's events in memory.
    problem = config.calendar_problem()
    if problem:
        logger.error("luach cannot start: %s", problem)
        raise RuntimeError(problem)
    config.check_service_keys()
    db.init_db()
    control.trail()  # load + verify the chain early, so a broken one is logged at boot
    if not control.trail().verify():
        logger.error("audit chain does NOT verify — someone edited audit_records")
    tasks = [asyncio.create_task(_run_the_loops())]
    # Memory fails quietly — a tool that raises still produces a friendly reply
    # — so it is probed here, where a broken deploy says so in the log at deploy
    # time. In the background: the probe loads an ONNX model on its first run
    # and nothing about the calendar should wait on that.
    tasks.append(asyncio.create_task(memory_health.probe_at_startup()))
    _ensure_family()
    _setup_code()
    _ensure_menu()
    logger.info(
        "luach %s up: calendar=%s model=%s",
        __version__,
        calendar_line(),
        model_menu.default_id() or "not configured",
    )
    if config.calendar_backend() == "fake":
        from luach.calendar.client import FAKE_WARNING

        logger.warning(FAKE_WARNING)
    if not model_menu.ready():
        logger.warning(
            "no model is configured: the assistant will say so until OPENAI_BASE_URL and "
            "LUACH_MODEL are set, or the owner picks one in Settings > Household > Models"
        )
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        loops_lock.release()


async def _run_the_loops() -> None:
    """The loops, once this copy holds the lock (see loops_lock): during a deploy
    the old copy keeps them until it stops, and the new one serves from its start."""
    await loops_lock.wait_for(config.state_dir() / "loops.lock")
    loops = [_purge_loop(), _busy_loop(), _reminder_loop(), _model_health_loop()]
    if config.gmail_poll_minutes():
        loops.append(_mail_loop())
    if config.mail_scan_minutes():
        loops.append(_scan_loop())
    await asyncio.gather(*loops)


def _setup_code() -> None:
    """With no accounts yet, the one-time code the first account needs, in the log (and in
    the state directory); with accounts, any code a first run left behind is removed."""
    from luach.auth import setup

    if db.users_exist():
        setup.spent()
    else:
        setup.ensure()


def _ensure_menu() -> None:
    """The menu from LUACH_MODELS on a first start; a trial's leftovers cleared."""
    from luach import model_trials

    try:
        model_menu.seed()
    except Exception:
        logger.exception("the model menu could not be seeded")
    try:
        model_trials.drop_leftovers()
    except Exception:
        logger.exception("could not clear what an interrupted model trial left")


async def _model_health_loop() -> None:
    """A model marked not answering is asked again every hour (one tiny request),
    so one the provider brings back recovers without anyone doing anything."""
    from luach import model_health

    while True:
        await asyncio.sleep(3600)
        try:
            if model_menu.ready():
                await model_health.recheck_unhealthy()
        except Exception:
            logger.exception("model health check failed")


def _ensure_family() -> None:
    """LUACH_FAMILY names the people a box should have (see family.ensure)."""
    spec = config.env("LUACH_FAMILY", "")
    if not spec:
        return
    from luach import family

    try:
        added = family.ensure(spec)
    except ValueError:
        logger.exception("LUACH_FAMILY could not be applied")
        return
    if added:
        logger.info("family: added %s from LUACH_FAMILY", ", ".join(added))


class _NoSecretsInTheAccessLog(logging.Filter):
    """uvicorn logs every path with its query string, and a link can carry a credential:
    Google's sign-in comes back as /api/mail/callback?code=…&state=… (and the OIDC
    callback likewise), and luach's own mails link to ?reset=, ?invite=, ?verify= and a
    booking's ?manage=. Some tokens are in the path itself: an invitation is read at
    /api/auth/invite/<token>, a booking managed at /api/book/<slug>/manage/<token>, a
    screen collects its pairing at /api/board/pair/<code>. Short-lived or not, each is a
    credential and has no business in a log."""

    _SECRET = re.compile(r"\b(code|state|reset|invite|verify|manage|token|nonce)=[^&\s\"]+")
    _IN_PATH = re.compile(
        r"(/api/auth/invite/|/api/book/[^/?\s\"]+/manage/|/api/board/pair/)[^/?\s\"]+"
    )

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path = self._SECRET.sub(r"\1=…", args[2])
            path = self._IN_PATH.sub(r"\1…", path)
            if path != args[2]:
                record.args = (*args[:2], path, *args[3:])
        return True


def _quiet_access_log() -> None:
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _NoSecretsInTheAccessLog) for f in access.filters):
        access.addFilter(_NoSecretsInTheAccessLog())


def _public_page(request: Request, page: Path) -> Response:
    """About or Privacy, filled in with this luach's settings. Still a page a browser
    and a CDN may keep: it carries an ETag and answers a matching one with 304."""
    from fastapi.responses import HTMLResponse

    body = public_pages.render(page.read_text(encoding="utf-8"))
    tag = public_pages.etag(body)
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers={"ETag": tag})
    return HTMLResponse(body, headers={"ETag": tag})


#: index.html names the hashed bundle, so it must be asked again every time: a cached
#: copy after an upgrade pointed at /assets files that were gone, and showed a blank
#: page. The service worker is the same: a stale one outlives the app it came with.
NO_CACHE = {"Cache-Control": "no-cache"}
#: Vite names every file under /assets after its contents: a new build is a new name.
IMMUTABLE = "public, max-age=31536000, immutable"


def _hashed_assets(directory: Path) -> Any:
    """/assets, where a file never changes under its name, so a browser keeps it for a year."""
    from fastapi.staticfiles import StaticFiles

    class Hashed(StaticFiles):
        async def get_response(self, path: str, scope: Scope) -> Response:
            response = await super().get_response(path, scope)
            # Not a miss: a 404 cached for a year would outlive the deploy that fixes it.
            if response.status_code in (200, 304):
                response.headers["Cache-Control"] = IMMUTABLE
            return response

    return Hashed(directory=directory)


def _shell(path: Path) -> FileResponse:
    """A file served from the app's root: the shell and the worker are never kept."""
    if path.name in ("index.html", "sw.js"):
        return FileResponse(path, headers=NO_CACHE)
    return FileResponse(path)


def create_app(static_dir: str | Path | None = None) -> FastAPI:
    _quiet_access_log()
    app = FastAPI(
        title="luach", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None
    )

    # Starlette raises its own HTTPException for a path that matched no route, and
    # a handler registered for FastAPI's does not see it — which is how a 404 kept
    # its {"detail": ...} shape while every other error here says {"error": ...}.
    @app.exception_handler(StarletteHTTPException)
    @app.exception_handler(HTTPException)
    async def _http_error(request: Request, exc: HTTPException) -> JSONResponse:
        raw: Any = exc.detail
        detail = raw if isinstance(raw, dict) else {"error": str(raw)}
        # Starlette's own 404 says {"detail": "Not Found"}; everything else here
        # answers {"error": ...}, and a caller should not have to parse two shapes
        # to find out what went wrong.
        if exc.status_code == 404 and detail in (
            {"error": "Not Found"},
            {"error": "404: Not Found"},
        ):
            detail = {"error": "no such route"}
        return JSONResponse(detail, status_code=exc.status_code)

    # FastAPI answers a malformed path or query with 422 {"detail": [...]}, a
    # shape no other error here has. A bad id in a path names nothing, so it is
    # a 404 like any other id that is not there; anything else is a 400 that
    # says which field and what was wrong with it.
    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        problem: dict[str, Any] = dict(exc.errors()[0]) if exc.errors() else {}
        loc = [str(part) for part in problem.get("loc", ())]
        where = loc[0] if loc else ""
        name = loc[1] if len(loc) > 1 else "the request"
        if where == "path":
            noun = name.removesuffix("_id").replace("_", " ")
            return JSONResponse({"error": f"there is no {noun} with that id"}, status_code=404)
        if problem.get("type") == "missing":
            return JSONResponse({"error": f"{name} is required"}, status_code=400)
        wanted = {
            "int_parsing": "a whole number",
            "bool_parsing": "true or false",
            "float_parsing": "a number",
        }.get(str(problem.get("type")), "valid")
        return JSONResponse({"error": f"{name} must be {wanted}"}, status_code=400)

    for r in (
        authn,
        board,
        booking,
        members,
        memory_routes,
        mail_routes,
        models,
        calendar,
        family,
        household,
        agent,
        control_routes,
        task_routes,
        transcribe,
        push,
        health,
    ):
        app.include_router(r.router)

    static = Path(static_dir) if static_dir else Path(config.env("LUACH_STATIC_DIR", "web/dist"))
    app.state.static_dir = static
    if static.is_dir():
        app.mount("/assets", _hashed_assets(static / "assets"), name="assets")

        # HEAD too: an uptime monitor asks HEAD / and read luach's 405 as down.
        @app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)
        async def spa(path: str, request: Request) -> Response:
            candidate = static / path
            # /about and /privacy are pages of their own (web/public/<name>/index.html),
            # readable without signing in: Google checks both before it lets members
            # connect Gmail, and the app itself opens on the sign-in screen.
            if path and (candidate / "index.html").is_file():
                candidate = candidate / "index.html"
            if (
                path
                and candidate.is_file()
                and candidate.resolve().is_relative_to(static.resolve())
            ):
                if public_pages.page_for(static, candidate):
                    return _public_page(request, candidate)
                return _shell(candidate)
            # A path under /api that reached here matched no route. Handing it the
            # single-page app means a caller who mistyped one gets 200 and a page
            # of HTML: asked for /api/pending (the route is /api/control/pending),
            # it answered 200 <!doctype html>, which reads as "that worked".
            # A browser only ever asks for real pages; a machine
            # deserves to be told.
            if path.startswith("api/"):
                return JSONResponse({"error": "no such route"}, status_code=404)
            return _shell(static / "index.html")

    app.add_middleware(AuthWall)
    app.add_middleware(SecurityHeaders)
    return app


app = create_app()

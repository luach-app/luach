from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Request

from luach import __version__, config, db, memory_health, model_menu
from luach.auth import users
from luach.calendar.client import get_calendar
from luach.routes.shared import require_member

router = APIRouter(prefix="/api")

#: The entry script Vite names after its contents: /assets/index-<hash>.js.
_ENTRY = re.compile(r'<script[^>]*\bsrc="(/assets/[^"]+\.js)"')
_seen: dict[str, tuple[int, int, str]] = {}


def build_of(static: Path | None) -> str:
    """Which build of the web app this server hands out: its entry script's name.

    The name changes whenever the app's code does, and a page can read its own
    from its <script> tag, so a wall board compares the two and knows it is
    behind without remembering anything. "" when there is no built app (dev,
    the tests). Read from disk at most once per change of index.html.
    """
    if static is None:
        return ""
    index = Path(static) / "index.html"
    try:
        st = index.stat()
    except OSError:
        return ""
    key = str(index)
    cached = _seen.get(key)
    if cached and cached[:2] == (st.st_mtime_ns, st.st_size):
        return cached[2]
    try:
        m = _ENTRY.search(index.read_text(errors="replace"))
    except OSError:
        return ""
    found = m.group(1) if m else ""
    _seen[key] = (st.st_mtime_ns, st.st_size, found)
    return found


@router.get("/health")
async def health(request: Request) -> dict:
    """Up, and which build: all anyone may ask without signing in.

    The readiness probe and the wall board read it, so it stays open. What it used
    to carry besides — the calendar's identity (a personal calendar's id is its
    owner's Gmail), the service account, the model's address, how many live here —
    is /api/health/details, for members."""
    # The readiness probe still keeps memory's verdict fresh (the probe itself runs in
    # the background, cached for a minute); only the answer moved behind sign-in.
    await memory_health.check()
    return {
        "ok": True,
        "version": __version__,
        # The web app's build; the house board reloads itself when it changes.
        "build": build_of(getattr(request.app.state, "static_dir", None)),
    }


@router.get("/health/details")
async def health_details(request: Request) -> dict:
    """The public answer and how this luach is wired, for a signed-in member."""
    require_member()
    return {
        **(await health(request)),
        "calendar": get_calendar().identity(),
        # "not configured" until the deployment names an endpoint and a model (or the
        # owner picks one in Settings › Household › Models): the calendar works without.
        "model": (
            {"id": model_menu.default_id(), "base_url": config.model_base_url()}
            if model_menu.ready()
            else "not configured"
        ),
        # Whether luach can still remember things, from a cached probe. Not part
        # of "ok": a household whose memory is down should still get its
        # calendar, and the readiness probe should not take the pod out for it.
        "memory": await memory_health.check(),
        "members": len(users.members()) if db.users_exist() else 0,
    }

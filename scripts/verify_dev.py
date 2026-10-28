"""Does a deployed luach work for a person? Checks a running server the way the app uses it.

The test suites drive luach against stubs. This drives a real deployment over HTTP, with a session
minted for its owner (`verify_dev_pod.py mint`), and checks what the stubbed suites cannot see: the
auth wall on the real build, the PWA's own bundle served under its CSP, a calendar event that is
really written, read back and removed, and an agent turn that reaches the real model and the real
calendar.

    python3 scripts/verify_dev.py <base url> <session file>

The session file holds one line, `<cookie name> <token>`. Writes only in a calendar that is
luach's own (health details say backend `local` or `fake`); anything else is refused before the
first write, so it is for a test deployment, never for a household's real calendar. What it writes
it removes: the event, and the conversation the agent turn opened. Exit 0 when every check passed.
Standard library only, so the machine that runs it needs nothing installed.

A deployment pipeline runs it from a checkout of the commit it deployed (tests/
test_release_pipeline.py holds it to this command line).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

#: Calendars luach keeps itself. A Google calendar is a family's real one: never written here.
OWN_CALENDARS = {"local", "fake"}
TITLE = "verify-dev check"


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body or b"null")
        except ValueError:
            return None


@dataclass
class Probe:
    base: str
    cookie: str = ""
    ok: bool = True
    made: list[str] = field(default_factory=list)

    def call(
        self,
        path: str,
        method: str = "GET",
        payload: Any = None,
        *,
        auth: bool = True,
        timeout: float = 30,
    ) -> Reply:
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.base.rstrip("/") + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        if auth and self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return Reply(
                    resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
                )
        except urllib.error.HTTPError as exc:
            return Reply(exc.code, {k.lower(): v for k, v in exc.headers.items()}, exc.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return Reply(0, {}, str(exc).encode())

    def check(self, name: str, passed: bool, detail: str = "") -> bool:
        self.ok = self.ok and passed
        print(f"{'ok  ' if passed else 'FAIL'} {name}{'  ' + detail if detail else ''}", flush=True)
        return passed


def scripts_of(index: str) -> list[str]:
    """The same-origin scripts the page loads: the bundle a CSP or a bad build would break."""
    return [s for s in re.findall(r'<script[^>]+src="([^"]+)"', index) if s.startswith("/")]


def tool_names(turn: Any) -> list[str]:
    calls = turn.get("tool_calls") if isinstance(turn, dict) else None
    return [str(c.get("tool")) for c in calls or [] if isinstance(c, dict)]


def run(base: str, cookie_name: str, token: str, today: dt.date | None = None) -> bool:
    p = Probe(base)
    today = today or dt.date.today()

    # -- the box, before anyone signs in: up, and saying nothing more than that
    health = p.call("/api/health", auth=False)
    h = health.json() if health.status == 200 else None
    if not p.check("health", isinstance(h, dict) and h.get("ok") is True, f"HTTP {health.status}"):
        return False
    assert isinstance(h, dict)
    p.check("health says only up, version and build", set(h) <= {"ok", "version", "build"})

    index = p.call("/", auth=False)
    page = index.body.decode("utf-8", "replace")
    p.check("the PWA is served", index.status == 200 and 'id="root"' in page)
    csp = index.headers.get("content-security-policy", "")
    p.check("under its CSP", "script-src 'self'" in csp and "frame-ancestors 'none'" in csp)
    bundle = scripts_of(page)
    p.check("the page loads its own bundle", bool(bundle), ", ".join(bundle) or "no script")
    for src in bundle:
        js = p.call(src, auth=False)
        kind = js.headers.get("content-type", "")
        p.check(
            f"  {src}",
            js.status == 200 and "javascript" in kind and len(js.body) > 1000,
            f"HTTP {js.status} {kind} {len(js.body)} bytes",
        )

    me = p.call("/api/auth/me", auth=False)
    p.check("no session: auth/me refuses", me.status == 401, f"HTTP {me.status}")
    agent = p.call("/api/agent", "POST", {"text": "hi"}, auth=False)
    p.check("no session: the agent refuses", agent.status in (401, 403), f"HTTP {agent.status}")

    # -- signed in
    p.cookie = f"{cookie_name}={token}"
    me = p.call("/api/auth/me")
    who = me.json() if me.status == 200 else None
    if not p.check("signed in: auth/me", isinstance(who, dict), f"HTTP {me.status}"):
        return False
    p.check("own threads", p.call("/api/threads").status == 200)
    p.check("the family", p.call("/api/family").status == 200)
    p.check("mail status", p.call("/api/mail").status == 200)

    # How the box is wired is for members: /api/health/details.
    details = p.call("/api/health/details")
    d = details.json() if details.status == 200 else None
    p.check("health details, signed in", isinstance(d, dict), f"HTTP {details.status}")
    d = d if isinstance(d, dict) else {}
    backend = str((d.get("calendar") or {}).get("backend") or "")
    p.check("a model is configured", bool((d.get("model") or {}).get("id")))
    memory = d.get("memory") or {}
    if memory.get("configured"):
        p.check("memory answers", memory.get("ok") is not False, str(memory.get("error") or ""))

    if not p.check(
        "the calendar is luach's own, so it may be written",
        backend in OWN_CALENDARS,
        f"backend={backend}",
    ):
        return False

    # -- a calendar event round trip: written, read back, removed. Nobody invited.
    day = (today + dt.timedelta(days=2)).isoformat()
    made = p.call(
        "/api/calendar/events",
        "POST",
        {
            "title": TITLE,
            "start": f"{day}T06:10",
            "end": f"{day}T06:40",
            "attendees": [],
            "description": "written by luach verify-dev; removed by it a moment later",
        },
    )
    ev = made.json() if made.status == 200 else None
    event_id = str(ev.get("id")) if isinstance(ev, dict) and ev.get("id") else ""
    p.check("an event is written", bool(event_id), f"HTTP {made.status}")
    try:
        if event_id:
            listed = p.call(f"/api/calendar/events?start={day}&end={day}").json() or {}
            ids = {str(e.get("id")) for e in listed.get("events") or [] if isinstance(e, dict)}
            p.check("and read back", event_id in ids)

            # -- the agent: the real model, reaching the real calendar for a calendar question
            turn = p.call("/api/agent", "POST", {"text": f"what's on {day}?"}, timeout=120)
            t = turn.json() if turn.status == 200 else None
            reply = str(t.get("reply") or "") if isinstance(t, dict) else ""
            if isinstance(t, dict) and t.get("thread_id"):
                p.made.append(str(t["thread_id"]))
            p.check("the agent answers", bool(reply), f"HTTP {turn.status}")
            tools = tool_names(t)
            p.check(
                "a calendar question reads the calendar",
                "list_events" in tools,
                ",".join(tools) or "no tool",
            )
            if TITLE not in reply.lower():
                print(
                    "     note: the reply does not name the event; the model's wording, "
                    "not a failure",
                    flush=True,
                )
    finally:
        if event_id:
            gone = p.call(f"/api/calendar/events/{event_id}", "DELETE")
            p.check("and removed", gone.status == 200, f"HTTP {gone.status}")
        for thread in p.made:
            p.call(f"/api/threads/{thread}", "DELETE")
    if event_id:
        left = p.call(f"/api/calendar/events?start={day}&end={day}").json() or {}
        ids = {str(e.get("id")) for e in left.get("events") or [] if isinstance(e, dict)}
        p.check("and gone from the calendar", event_id not in ids)
    return p.ok


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <base url> <session file>", file=sys.stderr)
        return 2
    with open(argv[2]) as fh:
        cookie_name, token = fh.read().split()[:2]
    return 0 if run(argv[1], cookie_name, token) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))

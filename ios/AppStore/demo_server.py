#!/usr/bin/env python3
"""A made-up household for App Store screenshots: the Riveras (Dana, Sam, Noa, Eli).

    python3 demo_server.py [port]        # on the Mac; the app pointed at http://127.0.0.1:<port>

App Store screenshots are public, so they never show a real family: this answers the calls the
app's screens make with invented people and a week of invented plans, dated from today. It needs
no session (every request is Dana's) and changes nothing. Ask answers one canned turn.
Shapes follow docs/API.md and the fixtures in ios/LuachTests.
"""
from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TZ = "-04:00"
PEOPLE = [
    {"key": "dana", "name": "Dana", "hex": "#039be5", "kind": "adult"},
    {"key": "sam", "name": "Sam", "hex": "#f4511e", "kind": "adult"},
    {"key": "noa", "name": "Noa", "hex": "#33b679", "kind": "kid"},
    {"key": "eli", "name": "Eli", "hex": "#8e24aa", "kind": "kid"},
]
ME = {"id": 1, "username": "dana", "email": "dana@example.com", "display_name": "Dana",
      "timezone": "America/New_York", "language": "en", "is_owner": True, "model": "",
      "last_seen": "2026-10-27T15:00:00+00:00", "emails": ["dana@example.com"],
      "notify_emails": [], "notify_pending": []}


def d(offset: int) -> date:
    return date.today() + timedelta(days=offset)


def at(offset: int, hour: int, minute: int = 0) -> str:
    return f"{d(offset).isoformat()}T{hour:02d}:{minute:02d}:00{TZ}"


# (day offset, start, minutes, title, leaders, location)
PLANS = [
    (0, (8, 15), 30, "School drop-off", ["sam"], ""),
    (0, (15, 30), 45, "Dentist", ["noa"], "Smile Dental, 2nd floor"),
    (0, (17, 0), 60, "Swimming lesson", ["eli"], "Community pool"),
    (0, (19, 30), 90, "Dinner with the Cohens", ["dana", "sam"], "Our place"),
    (1, (16, 0), 60, "Piano", ["noa"], ""),
    (1, (18, 0), 60, "Soccer practice", ["eli"], "Riverside field"),
    (2, (9, 0), 60, "Parent–teacher meeting", ["dana"], "Room 12"),
    (3, (17, 30), 60, "Soccer practice", ["eli"], "Riverside field"),
    (4, (20, 0), 120, "Movie night", [], ""),
    (5, (10, 0), 90, "Farmers market", ["dana", "noa"], ""),
    (6, (12, 0), 120, "Grandma's birthday lunch", [], "Grandma's"),
]


def event(i: int, plan: tuple) -> dict:
    off, (h, m), mins, title, leaders, location = plan
    start = datetime.combine(d(off), datetime.min.time()).replace(hour=h, minute=m)
    end = start + timedelta(minutes=mins)
    return {"id": f"demo{i}", "title": title, "start": f"{start.isoformat()}{TZ}", "end": f"{end.isoformat()}{TZ}",
            "all_day": False, "location": location, "description": "", "recurrence": [], "recurring_event_id": "",
            "html_link": "", "creator": "dana@example.com", "calendar_id": "family", "attendees": [], "invite_error": "",
            "leader": leaders[0] if leaders else "", "leaders": leaders, "color_id": "", "ical_uid": "", "organizer": "",
            "read_only": False, "recurring": False}


EVENTS = [event(i, p) for i, p in enumerate(PLANS)]
TASKS = [
    {"id": 1, "title": "Pack the swim bag", "person": "eli", "due": d(0).isoformat(), "days": [], "notes": "",
     "done": False, "overdue": False, "chore": False},
    {"id": 2, "title": "Practice scales", "person": "noa", "due": "", "days": ["MO", "TU", "WE", "TH", "FR"],
     "notes": "", "done": True, "overdue": False, "chore": True},
    {"id": 3, "title": "Feed the cat", "person": "", "due": "", "days": ["MO", "TU", "WE", "TH", "FR", "SA", "SU"],
     "notes": "", "done": False, "overdue": False, "chore": True},
    {"id": 4, "title": "Buy the birthday card", "person": "dana", "due": d(0).isoformat(), "days": [], "notes": "",
     "done": False, "overdue": False, "chore": False},
]
HOLDS = [
    {"id": "h1", "tool": "create_event", "summary": f"Add “Piano recital” — {d(5).strftime('%a %-d %b')}, 16:00–17:00 · for Noa",
     "reason": ["ambiguous"], "principal": "sam", "door": "web", "status": "pending", "created_at": "", "source": ""},
    {"id": "h2", "tool": "update_event", "summary": f"Move “Soccer practice” to {d(3).strftime('%a %-d %b')}, 18:00",
     "reason": ["mutation-existing"], "principal": "eli", "door": "web", "status": "pending", "created_at": "", "source": ""},
]


def compact(e: dict) -> dict:
    s = datetime.fromisoformat(e["start"])
    t = datetime.fromisoformat(e["end"])
    return {"id": e["id"], "title": e["title"], "when": f"{s.strftime('%a %-d %b')}, {s:%H:%M}–{t:%H:%M}",
            "location": e["location"]}


def stream() -> str:
    week = [compact(e) for e in EVENTS if e["start"][:10] <= d(6).isoformat()][:6]
    frames = [
        {"type": "session", "thread_id": "demo-thread"},
        {"type": "model", "name": "Household model"},
        {"type": "tool_start", "tool": "list_events", "args": {"start_date": d(0).isoformat()}},
        {"type": "tool_result", "tool": "list_events", "result": {}},
        {"type": "widget", "kind": "agenda", "data": {"title": f"{d(0).strftime('%a %-d')} – {d(6).strftime('%a %-d %b')}",
                                                       "events": week, "truncated": True}},
    ]
    words = ("A full week! Noa has the dentist this afternoon and piano tomorrow, Eli has swimming today and "
             "soccer twice, and Saturday is Grandma's birthday lunch. Thursday evening is still free.")
    frames += [{"type": "token", "text": w + " "} for w in words.split(" ")]
    frames.append({"type": "done", "reply": words, "thread_id": "demo-thread", "model": "Household model"})
    return "".join(f"data: {json.dumps(f)}\n\n" for f in frames)


class Demo(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # quiet
        pass

    def send(self, body, status: int = 200, kind: str = "application/json") -> None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        p = url.path
        if p in ("/api/auth/me",):
            return self.send(ME)
        if p == "/api/auth/status":  # what the sign-in screen checks an address with
            return self.send({"users_exist": True, "authenticated": True, "member": ME,
                              "mail": {"enabled": False}, "sso": {"enabled": False, "label": ""}})
        if p == "/api/calendar/events":
            lo, hi = q.get("start", "0000"), q.get("end", "9999")
            return self.send({"events": [e for e in EVENTS if lo <= e["start"][:10] < hi], "timezone": "America/New_York"})
        if p == "/api/household/calendars":
            return self.send({"available": [{"id": "family", "name": "Family", "color": "#f4b942", "primary": True,
                                             "writable": True, "enabled": True, "default": True}],
                              "calendars": ["family"], "default_calendar": "family", "default_attendees": []})
        if p == "/api/family":
            return self.send({"people": [dict(x, color=str(i + 1), email="", user_id=None, position=i) for i, x in enumerate(PEOPLE)],
                              "colors": []})
        if p == "/api/board/today":
            day = q.get("day") or d(0).isoformat()
            off = (date.fromisoformat(day) - d(0)).days
            today_events = [e for e in EVENTS if e["start"][:10] == day]
            tomorrow = [e for e in EVENTS if e["start"][:10] == (d(off + 1)).isoformat()]
            return self.send({"board": "", "viewer": "Dana", "can_edit": True, "language": "en",
                              "timezone": "America/New_York", "now": f"{datetime.now().isoformat()}{TZ}",
                              "today": d(0).isoformat(), "day": day, "people": PEOPLE, "events": today_events,
                              "tomorrow": tomorrow, "tasks": TASKS if off == 0 else []})
        if p in ("/api/tasks", "/api/tasks/all"):
            return self.send({"day": d(0).isoformat(), "tasks": TASKS, "may_assign": True})
        if p == "/api/control/pending":
            return self.send({"pending": HOLDS})
        if p == "/api/mail":
            return self.send({"connected": False, "address": "", "via": "", "can_connect": True})
        if p == "/api/transcribe/status":
            return self.send({"available": True})
        if p == "/api/threads":
            return self.send({"threads": [], "more": False, "retention_days": 60})
        if p == "/api/models":
            return self.send({"models": ["household"], "default": "household", "chosen": "",
                              "catalogue": [{"id": "household", "name": "Household model",
                                             "about": "Runs on the household's own machine. Nothing leaves the house."}]})
        return self.send({"error": "no such route"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path == "/api/agent/stream":
            self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
            return self.send(stream(), kind="text/event-stream")
        return self.send({"error": "this demo changes nothing"}, 403)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"demo household on http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Demo).serve_forever()

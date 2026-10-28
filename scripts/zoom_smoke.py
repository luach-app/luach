#!/usr/bin/env python
"""Prove the Zoom credentials work, without printing them.

    LUACH_ZOOM_ACCOUNT_ID=... LUACH_ZOOM_CLIENT_ID=... LUACH_ZOOM_CLIENT_SECRET=... \
        hatch run python scripts/zoom_smoke.py

Creates a meeting half an hour from now, prints its join URL, deletes it again.
Nothing is written to the calendar and no credential is echoed.
"""

from __future__ import annotations

import sys
from datetime import timedelta

from luach import config, meetings
from luach.calendar import times


def main() -> int:
    if not meetings.configured():
        print("no Zoom credentials in the environment (LUACH_ZOOM_ACCOUNT_ID/CLIENT_ID/SECRET)")
        return 2
    tz = config.timezone()
    when = times.now_in(tz) + timedelta(minutes=30)
    made = meetings.create_meeting("luach smoke test — safe to ignore", when, 15, tz)
    if made is None:
        print("Zoom refused; see the log line above for the status code")
        return 1
    print(f"created meeting {made.id}: {made.join_url}")
    print("deleted" if meetings.delete_meeting(made.id) else "could NOT delete — remove it by hand")
    return 0


if __name__ == "__main__":
    sys.exit(main())

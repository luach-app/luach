---
name: repeating-events
description: Use when an event repeats, or stops, or changes how it repeats — "every Tuesday", "weekdays at 7:10", "every day", "every other week", "until the middle of November", "until the end of October", "no more on Thursdays", "it stops in December".
allowed-tools: create_event update_event find_events
---
# Repeating events

- `recurrence` is one RRULE: "every Tuesday" is `RRULE:FREQ=WEEKLY;BYDAY=TU`;
  weekdays `RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR`; every day `RRULE:FREQ=DAILY`;
  every other week `RRULE:FREQ=WEEKLY;INTERVAL=2;BYDAY=…`.
- An end is `UNTIL=YYYYMMDD` inside the rule: "until the end of October" is
  `UNTIL=20261031`; "until the middle of November" is `UNTIL=20261115`.
- `start` is the FIRST occurrence: the next matching day from the [context] line.
- Adding an end, or changing the days, to one that exists: find it, then
  `update_event` with the whole new `recurrence` — it changes every occurrence, so only
  when the person asked for that. `recurrence="none"` stops it repeating.
- Say back the pattern and the end: "every Thursday at 18:00 until 31 Oct".

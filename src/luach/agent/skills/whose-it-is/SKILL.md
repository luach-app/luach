---
name: whose-it-is
description: Use when something is for someone in the family, or for several of them, or should be on someone's board — "{a} has football at 5", "breakfast for {a} and {b}", "{a}'s dentist", "put it on their board", "it's {b}'s now", "this is for {a}".
allowed-tools: create_event update_event find_events
---
# Whose it is

The family is in the [context] line (`family=`). An event or a task can be one of
them's, several of them's, or the whole family's.

- Whose it is goes in `for_whom`, and ONLY there: "{a}", or several, "{a} and {b}".
  It is then in their colour, on their part of the house board, and they are invited.
- The title is what the thing IS — "Football", "Breakfast", "Dentist". Never put a
  person's name in the title, and never add "board" or any word about who it is for.
- "my …" is the member who is speaking.
- Something for everyone gets no `for_whom`.
- A name that is NOT in the family is part of what the event is ("add Jordan Pike at
  6:30" is an event called "Jordan Pike"), never `for_whom`.

Changing whose it is — "this is for {a}", "put it on {b}'s board too", "it's {a} and
{b}'s": find the event with `find_events` (or use the one you just made in this
conversation), then `update_event` with `for_whom` and nothing else. Do not touch the
title. "Too" means the people it already had plus the new ones.

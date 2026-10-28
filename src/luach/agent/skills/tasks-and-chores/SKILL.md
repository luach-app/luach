---
name: tasks-and-chores
description: Use when someone has to DO something rather than go somewhere or meet someone — a to-do or a chore, like "{a} has to return the library book by Friday", "{b} takes the bins out every Tuesday", "{a} feeds the fish every day", "{a} and {b} have to tidy their room", "{a} fed the fish", "the bins are {b}'s now", "{a} doesn't do the dishes any more".
allowed-tools: add_task list_tasks complete_task change_task remove_task
---
# Tasks and chores

A thing that HAPPENS at a time is an event (`create_event`). A thing someone has to DO
is a task.

- Add: `add_task` with `for_whom` — one person, or several ("{a} and {b}": each gets
  their own to tick). Empty for whoever gets to it.
- A to-do with a deadline: `due` is that day as YYYY-MM-DD — "by Friday", "before
  Monday", "tomorrow" are due days, read off the [context] line's next 7 days.
- A chore that comes back: `repeats` — "tue", "mon,thu", "weekdays", "daily". A
  deadline is never a repeat: "finish the project by Monday" is a one-off due Monday.
- Done: `list_tasks` to find it, then `complete_task` with its id.
- Changed ("it's {b}'s now", "move it to Monday", "Tuesdays and Fridays now"):
  `list_tasks` with `day="all"` (a chore on Tuesdays is not on today's list), then
  `change_task` with its id — a task is one person's.
- Dropped for good ("{a} doesn't do that any more", "forget the library book"):
  `list_tasks` with `day="all"`, then `remove_task`. Something that was done is
  `complete_task`, not this.
- Say back what was saved, including the day — the tool's answer says the day it saved.

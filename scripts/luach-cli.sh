#!/bin/sh
#
# luach — a small client for a trusted service that holds luach's service key
# (LUACH_API_KEY on the server), such as a chat bot that talks to the household
# calendar on a family's behalf.
#
# It is one executable on purpose: an agent whose shell commands are
# allowlisted by binary path can be given this and nothing else. It reads the
# service key itself, so the key never travels through a command the agent
# composed, logged, or could quote back.
#
# USAGE
#   luach ask "dentist next tuesday 3pm"           one agent turn, JSON reply
#   luach ask "and move it to 4" --thread <id>     continue a conversation
#   luach agenda [DAYS]                            plain list of upcoming events
#   luach pending                                  holds waiting for a person
#   luach approve <id> | luach deny <id>           decide a hold (a person said so)
#   luach health
#
# SETTINGS
#   LUACH_URL   the server (default http://127.0.0.1:8004)
#   LUACH_KEY   the service key
#   LUACH_ENV   optional: a file of KEY=value lines setting the two above, read
#               first, so the key need not sit in the caller's environment
#
set -eu
case "${1:-}" in
    ""|-h|--help)
        sed -n '/^# USAGE/,/^set -eu$/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//' >&2; exit 2 ;;
esac
if [ -n "${LUACH_ENV:-}" ]; then
    [ -r "$LUACH_ENV" ] || { echo "luach: cannot read $LUACH_ENV" >&2; exit 3; }
    # shellcheck disable=SC1090
    . "$LUACH_ENV"
fi
: "${LUACH_URL:=http://127.0.0.1:8004}"
: "${LUACH_KEY:?set LUACH_KEY, or LUACH_ENV to a file that sets it}"

json_escape() { printf '%s' "$1" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))'; }
call() { # method path [body]
    if [ $# -ge 3 ]; then
        curl -sS --max-time 180 -X "$1" -H "x-luach-key: $LUACH_KEY" -H 'content-type: application/json' \
            --data-binary "$3" "$LUACH_URL$2"
    else
        curl -sS --max-time 30 -X "$1" -H "x-luach-key: $LUACH_KEY" "$LUACH_URL$2"
    fi
    echo
}

cmd="${1:-}"; [ $# -gt 0 ] && shift
case "$cmd" in
    ask)
        text="${1:-}"; [ -n "$text" ] || { echo "usage: luach ask \"text\" [--thread id]" >&2; exit 2; }
        shift
        thread=""
        [ "${1:-}" = "--thread" ] && thread="${2:-}"
        body=$(printf '{"text": %s, "thread_id": %s}' "$(json_escape "$text")" "$(json_escape "$thread")")
        call POST /api/agent "$body"
        ;;
    agenda)
        days="${1:-7}"
        start=$(date +%F); end=$(date -d "+$days days" +%F)  # GNU date
        call GET "/api/calendar/events?start=$start&end=$end" | python3 -c '
import json,sys
d=json.load(sys.stdin)
if "error" in d:
    print("luach:", d["error"], file=sys.stderr); sys.exit(1)
for e in d.get("events",[]):
    when = e["start"] if e.get("all_day") else e["start"][:16].replace("T"," ")
    loc = ("  @ " + e["location"]) if e.get("location") else ""
    print(when + "  " + e["title"] + loc + "  [id:" + e["id"] + "]")
if not d.get("events"): print("no events in that window")'
        ;;
    pending)  call GET "/api/control/pending" ;;
    approve)  [ -n "${1:-}" ] || { echo "usage: luach approve <id>" >&2; exit 2; }; call POST "/api/control/pending/$1/approve" ;;
    deny)     [ -n "${1:-}" ] || { echo "usage: luach deny <id>" >&2; exit 2; }; call POST "/api/control/pending/$1/deny" ;;
    health)   call GET /api/health/details ;;
    *) echo "luach: unknown command '$cmd' (try --help)" >&2; exit 2 ;;
esac

#!/usr/bin/env bash
# The read-only check of the iPhone app against the family's luach (prod).
#
#   ios/scripts/test-prod.sh
#
# Runs only ProdReadTests and ProdUITests: GETs through the app's own calls, and the app opened on
# every tab and every settings screen a member sees, tapping nothing that writes. It signs in as the
# `ios-test` member made for this, whose login lives on the Mac only:
#
#   ~/.luach/prod-test.env   (chmod 600)   LUACH_PROD_USER=ios-test
#                                          LUACH_PROD_PASSWORD=…
#
# Settings (ios/scripts/settings.sh): LUACH_PROD_SERVER, the family's luach; LUACH_MAC_HOST and
# LUACH_MAC_DIR, where it builds.
#
# The password never leaves the Mac: the sign-in, the run and the sign-out all happen there. The
# tests get the session as LUACH_PROD_* — names no other test reads, so nothing that writes ever
# sees prod (LuachTests/Support/Dev.swift, LuachUITests/Support/LuachApp.swift).
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
. "$here/settings.sh"
server="${LUACH_PROD_SERVER:-}"
server="${server%/}"
[ -n "$server" ] || { echo "no LUACH_PROD_SERVER: which luach is prod? (ios/README.md, \"Settings\")" >&2; exit 2; }
dir="$mac_dir/luach-prod"

mac "mkdir -p $dir"
rsync -a --delete --exclude build --exclude scripts/local.env "$repo/ios/" "$(on_mac "$dir/ios/")"

set +e
mac "bash -s -- $(printf '%q ' "$dir" "$server")" <<'MAC'
set -uo pipefail
dir=$1 server=$2
cd "$dir"/ios && mkdir -p build
creds=~/.luach/prod-test.env
[ -f "$creds" ] || { echo "no $creds: see ios/README.md, 'The prod check'"; exit 2; }
user=$(sed -n 's/^LUACH_PROD_USER=//p' "$creds"); pass=$(sed -n 's/^LUACH_PROD_PASSWORD=//p' "$creds")
[ "$user" = ios-test ] || { echo "the prod check signs in as ios-test only (got '$user')"; exit 2; }

jar=$(mktemp); chmod 600 "$jar"
# The password goes through environments and stdin, never a process's arguments, which anyone on
# the Mac reads in `ps`.
code=$(LUACH_U="$user" LUACH_P="$pass" python3 -c 'import json, os; print(json.dumps({"username": os.environ["LUACH_U"], "password": os.environ["LUACH_P"]}))' |
  curl -s -o /dev/null -w '%{http_code}' -c "$jar" -H 'Content-Type: application/json' --data-binary @- "$server/api/auth/login")
unset pass
[ "$code" = 200 ] || { echo "signing in as ios-test answered $code"; rm -f "$jar"; exit 2; }
token=$(awk '$6 == "luach_session" {print $7}' "$jar")
# However the run ends, the session goes with it.
trap 'curl -s -o /dev/null -b "$jar" -X POST "$server/api/auth/logout"; rm -f "$jar"' EXIT

D=$(xcrun simctl list devices available | grep -E "^ +luach-prod \(" | head -1 | sed -E 's/.*\(([0-9A-F-]{36})\).*/\1/')
[ -n "$D" ] || D=$(xcrun simctl create luach-prod "iPhone 18 Pro")
pkill -f "xcodebuild test .*id=$D" 2>/dev/null && sleep 3
rm -rf build/prod.xcresult
# Exported, so the session is in no process's arguments; the UI tests hand it to the app in its
# environment (LuachUITests/Support/LuachApp.swift).
export TEST_RUNNER_LUACH_PROD_SERVER="$server" TEST_RUNNER_LUACH_PROD_SESSION="$token"
unset token
xcodebuild test -project Luach.xcodeproj -scheme Luach -destination "id=$D" -derivedDataPath build \
  -resultBundlePath build/prod.xcresult \
  -only-testing:LuachTests/ProdReadTests -only-testing:LuachUITests/ProdUITests > build/prod.log 2>&1
status=$?
grep -E "recorded an issue|error: -\[|✘ Test|Test Case .*(passed|failed|skipped)" build/prod.log | head -40
grep -E "Test run with|Executed [0-9]+ tests?, with|\*\* TEST (SUCCEEDED|FAILED) \*\*" build/prod.log | tail -4
[ $status -eq 0 ] || grep -E "error:" build/prod.log | grep -v -E "Test|XCT" | head -10
exit $status
MAC
status=$?
[ $status -eq 0 ] && echo "PROD CHECK PASSED" || echo "PROD CHECK FAILED ($status)"
exit $status

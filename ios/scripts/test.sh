#!/usr/bin/env bash
# Run the iPhone app's tests: unit tests, then the integration and UI tests against a dev luach
# with a session minted for the run and signed out after it.
#
#   ios/scripts/test.sh                                  # everything; against dev when one is set
#   ios/scripts/test.sh --unit                           # only what needs no server
#   ios/scripts/test.sh -- -only-testing:LuachTests/APITests     # any xcodebuild arguments
#
# Settings (ios/scripts/settings.sh; from the environment or ios/scripts/local.env):
#   LUACH_MAC_HOST, LUACH_MAC_DIR    where it builds: a Mac over ssh, or this Mac
#   LUACH_DEV_SERVER                 the dev luach; unset, the tests that need one are skipped
#   LUACH_DEV_KUBECONFIG, LUACH_DEV_NAMESPACE   how to reach its pod to mint the session
#   LUACH_PROD_SERVER                the family's luach, which no test here may use
# And for the run:
#   LUACH_TEST_NAME       a name of its own for this run's copy and simulator, so runs side by
#                         side do not share them (default "test"); an area's name (core, agenda,
#                         board, you, household) also limits the run to that area's tests
#   LUACH_COVERAGE_MIN    fail when the app's line coverage is below this percentage
# The tests run from this working tree, copied to <LUACH_MAC_DIR>/luach-<name> on the Mac.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
. "$here/settings.sh"
mode=all
if [ "${1:-}" = --unit ]; then mode=unit; shift; fi
[ "${1:-}" = -- ] && shift
name="${LUACH_TEST_NAME:-test}"
dir="$mac_dir/luach-$name"
server="${LUACH_DEV_SERVER:-}"
server="${server%/}"
prod_host="$(host_of "${LUACH_PROD_SERVER:-}")"

# The integration and UI tests write: never to the family's luach.
if [ -n "$server" ] && [ -n "$prod_host" ] && [ "$(host_of "$server")" = "$prod_host" ]; then
  echo "LUACH_DEV_SERVER is the family's luach (LUACH_PROD_SERVER): the tests here write, so they never run there" >&2
  exit 2
fi
if [ "$mode" = all ] && [ -z "$server" ]; then
  echo "no LUACH_DEV_SERVER: the integration and UI tests are skipped"
fi

# A run named for an area (core, agenda, board, you, household) takes only that area's tests,
# so another area's half-written tests cannot break its build. Any other name takes them all.
ex=(--exclude build --exclude scripts/local.env)
gone=()
areas="Core Agenda Board You Household"
mine="$(for a in $areas; do [ "$(echo "$a" | tr '[:upper:]' '[:lower:]')" = "$name" ] && echo "$a"; done; true)"
if [ -n "$mine" ]; then
  for a in $areas; do
    [ "$a" = "$mine" ] || { ex+=(--exclude "/LuachTests/$a/" --exclude "/LuachUITests/$a/"); gone+=("LuachTests/$a" "LuachUITests/$a"); }
  done
fi
# The Mac's rsync is openrsync, which refuses --delete-excluded with protect rules: what an
# earlier run left of other areas' tests is removed by hand instead.
mac "mkdir -p $dir/ios && cd $dir/ios && rm -rf ${gone[*]:-}"
rsync -a --delete "${ex[@]}" "$repo/ios/" "$(on_mac "$dir/ios/")"

token=""
if [ "$mode" = all ] && [ -n "$server" ]; then
  work="$(mktemp -d)"; chmod 700 "$work"
  kube=(kubectl)
  [ -n "${LUACH_DEV_KUBECONFIG:-}" ] && kube=(env KUBECONFIG="${LUACH_DEV_KUBECONFIG/#\~/$HOME}" kubectl)
  [ -n "${LUACH_DEV_NAMESPACE:-}" ] && kube+=(-n "$LUACH_DEV_NAMESPACE")
  "${kube[@]}" exec -i deploy/luach -c luach -- python - mint < "$repo/scripts/verify_dev_pod.py" > "$work/session" \
    || { echo "could not mint a session in dev's pod (is it reachable? LUACH_DEV_KUBECONFIG, LUACH_DEV_NAMESPACE)" >&2; exit 1; }
  read -r cookie token _ < "$work/session"
  # Signed out however the run ends: the session is good for 30 days otherwise.
  # Interrupted, the Mac's half is stopped too, so nothing goes on testing with a dead session.
  # The cookie reaches curl on stdin (-K -): an argument shows in `ps` to anyone on the machine.
  trap 'mac "pkill -f \"xcodebuild test .*luach-$name\"" 2>/dev/null || true
        printf "cookie = \"%s=%s\"\n" "$cookie" "$token" | curl -s -o /dev/null -X POST -K - "$server/api/auth/logout"
        rm -rf "$work"' EXIT
fi

only=()
[ "$mode" = unit ] && only=(-only-testing:LuachTests)

set +e
# ssh joins its arguments into one command line, where an empty one would vanish and shift the
# rest: each is quoted on its way. The session is not among them: arguments show in `ps` to
# anyone on either machine, so it goes ahead of the script on ssh's stdin, and on the Mac only
# into the environment of what needs it.
IFS= read -r -d '' script <<'MAC'
dir=$1 name=$2 server=$3 prod_host=$4 floor=$5; shift 5
cd "$dir"/ios
D=$(xcrun simctl list devices available | grep -E "^ +luach-$name \(" | head -1 | sed -E 's/.*\(([0-9A-F-]{36})\).*/\1/')
[ -n "$D" ] || D=$(xcrun simctl create "luach-$name" "iPhone 18 Pro")
# One run per simulator: an earlier run still going (its caller interrupted) would drive the
# same app with a session that has since been signed out.
pkill -f "xcodebuild test .*id=$D" 2>/dev/null && sleep 3
# The microphone already allowed, so asking for it answers at once instead of a prompt nobody taps.
bundle=$(sed -n 's/.*PRODUCT_BUNDLE_IDENTIFIER = \(.*\);/\1/p' Luach.xcodeproj/project.pbxproj | head -1)
xcrun simctl boot "$D" 2>/dev/null; xcrun simctl privacy "$D" grant microphone "$bundle" 2>/dev/null
mkdir -p build && rm -rf build/tests.xcresult
# Exported, not `env NAME=value …`: the shell's own export puts the session in no process's
# arguments. xcodebuild hands TEST_RUNNER_* to the test runner without the prefix, and the UI
# tests hand the session to the app in its environment (LuachUITests/Support/LuachApp.swift).
export TEST_RUNNER_LUACH_TEST_SERVER="${token:+$server}" TEST_RUNNER_LUACH_TEST_SESSION="$token" \
  TEST_RUNNER_LUACH_PROD_HOST="$prod_host"
unset token
xcodebuild test -project Luach.xcodeproj -scheme Luach -destination "id=$D" \
  -derivedDataPath build -resultBundlePath build/tests.xcresult "$@" > build/test.log 2>&1
status=$?
# What failed, in the words of the assertion; then the totals.
grep -E "(error|failed|issue).*(Test|Expectation|#expect|XCT)|^✘|recorded an issue" build/test.log | grep -v "^Test Suite" | head -60
grep -E "Executed [0-9]+ tests?|Test run with [0-9]+ tests|^✔ Test run|^✘ Test run|\*\* TEST (SUCCEEDED|FAILED) \*\*" build/test.log | tail -6
# A build that failed says so here, with its compiler errors.
[ $status -eq 0 ] || grep -E "error:" build/test.log | grep -v -E "Test|XCT" | head -20

# Line coverage of the app itself, the files least covered first.
if [ -d build/tests.xcresult ]; then
  xcrun xccov view --report --json build/tests.xcresult > build/coverage.json 2>/dev/null && python3 - "$floor" <<'PY'
import json, sys
floor = float(sys.argv[1])
report = json.load(open("build/coverage.json"))
app = next((t for t in report.get("targets", []) if t["name"] == "Luach.app"), None)
if app is None:
    print("coverage: no data for Luach.app"); sys.exit(0)
files = sorted(app["files"], key=lambda f: f["lineCoverage"])
print("\ncoverage by file (lowest first):")
for f in files:
    print(f"  {f['lineCoverage']*100:5.1f}%  {f['coveredLines']:5}/{f['executableLines']:<5} {f['path'].split('/ios/Luach/')[-1]}")
total = app["lineCoverage"] * 100
print(f"\ncoverage: Luach.app {total:.1f}% of lines ({app['coveredLines']}/{app['executableLines']})")
if total < floor:
    print(f"coverage below the floor of {floor:.0f}%"); sys.exit(3)
PY
  cov=$?
  [ $status -eq 0 ] && status=$cov
fi
exit $status
MAC
{ printf 'token=%q\n' "$token"; printf '%s' "$script"; } |
  mac "bash -s -- $(printf '%q ' "$dir" "$name" "$server" "$prod_host" "${LUACH_COVERAGE_MIN:-0}" ${only[@]+"${only[@]}"} "$@")"
status=$?
set -e
[ $status -eq 0 ] && echo "TESTS PASSED" || echo "TESTS FAILED ($status)"
exit $status

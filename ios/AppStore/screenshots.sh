#!/usr/bin/env bash
# App Store screenshots of this working tree, against the made-up household in demo_server.py.
#
#   ios/AppStore/screenshots.sh [out-dir]      # default: ios/AppStore/screenshots (not committed)
#
# Builds the app on the Mac (LUACH_MAC_HOST and LUACH_MAC_DIR, ios/scripts/settings.sh; unset, this
# one), starts the demo household there, and shoots each screen on an iPhone 18 Pro Max simulator
# (the 6.9-inch size App Store Connect asks for) with a clean status bar.
# Then: python3 ios/scripts/asc.py screenshots <dir> on the Mac uploads them.
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
. "$repo/ios/scripts/settings.sh"
out="${1:-$repo/ios/AppStore/screenshots}"
dir="$mac_dir/luach-shots"
mkdir -p "$out"

mac "mkdir -p $dir"
rsync -a --delete --exclude build --exclude scripts/local.env "$repo/ios/" "$(on_mac "$dir/ios/")"

mac "bash -s -- $(printf '%q ' "$dir")" <<'MAC'
set -euo pipefail
dir=$1
cd "$dir"/ios
bundle=$(sed -n 's/.*PRODUCT_BUNDLE_IDENTIFIER = \(.*\);/\1/p' Luach.xcodeproj/project.pbxproj | head -1)
xcodebuild -project Luach.xcodeproj -scheme Luach -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build -quiet build > build.log 2>&1 || { tail -20 build.log; exit 1; }
D=$(xcrun simctl list devices available | grep -E "^ +luach-shots \(" | head -1 | sed -E 's/.*\(([0-9A-F-]{36})\).*/\1/' || true)
[ -n "$D" ] || D=$(xcrun simctl create luach-shots "iPhone 18 Pro Max")
xcrun simctl boot "$D" 2>/dev/null || true
xcrun simctl bootstatus "$D" -b >/dev/null
xcrun simctl ui "$D" appearance light
xcrun simctl status_bar "$D" override --time 9:41 --batteryState charged --batteryLevel 100 \
  --cellularMode active --cellularBars 4 --wifiBars 3 --operatorName ""
xcrun simctl install "$D" build/Build/Products/Debug-iphonesimulator/Luach.app

python3 AppStore/demo_server.py 8765 > /tmp/luach-demo.log 2>&1 &
server=$!
trap 'kill $server 2>/dev/null' EXIT
sleep 1

rm -rf /tmp/luach-shots && mkdir -p /tmp/luach-shots
shoot() {
  local name=$1 wait=$2; shift 2
  xcrun simctl terminate "$D" "$bundle" 2>/dev/null || true
  xcrun simctl launch "$D" "$bundle" -server http://127.0.0.1:8765 -sessionCookie demo -thread "" "$@" >/dev/null
  sleep "$wait"
  xcrun simctl io "$D" screenshot "/tmp/luach-shots/$name.png" >/dev/null 2>&1
}
shoot 1-agenda 6 -tab agenda -agendaMode upcoming
shoot 2-board 6 -tab board
shoot 3-ask 12 -tab ask -ask "What does our week look like?"
shoot 4-month 6 -tab agenda -agendaMode month
shoot 5-approvals 6 -tab approvals
sips -g pixelWidth -g pixelHeight /tmp/luach-shots/1-agenda.png | tail -2 | tr '\n' ' '; echo
MAC
if [ -n "$LUACH_MAC_HOST" ]; then
  scp -q "$LUACH_MAC_HOST:/tmp/luach-shots/*.png" "$out/"
else
  cp /tmp/luach-shots/*.png "$out/"
fi
echo "screenshots: $out"

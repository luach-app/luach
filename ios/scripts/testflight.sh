#!/usr/bin/env bash
# Build one commit of luach's iPhone app on the Mac and upload it to TestFlight.
#
#   ios/scripts/testflight.sh            # origin/main
#   ios/scripts/testflight.sh <ref>
#
# Run from this checkout; the Mac builds exactly that commit (git archive), never a working tree.
# Which Mac: LUACH_MAC_HOST and LUACH_MAC_DIR (ios/scripts/settings.sh); unset, this one.
# The Mac needs, once (ios/README.md, "TestFlight"):
#   ~/.appstoreconnect/private_keys/AuthKey_<KEY_ID>.p8   the App Store Connect API key (Admin)
#   ~/.appstoreconnect/luach.env                           LUACH_ASC_KEY_ID, LUACH_ASC_ISSUER_ID,
#                                                          LUACH_TEAM_ID
# With the key, xcodebuild signs with a cloud-managed certificate and makes the App Store profile
# itself: nobody signs in to Xcode, and there is nothing that expires on a date to remember.
# ios/scripts/asc.py talks to App Store Connect with the same key (builds, testers, bundle IDs).
set -euo pipefail

ref="${1:-origin/main}"
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(git -C "$here" rev-parse --show-toplevel)"
. "$here/settings.sh"
git -C "$repo" fetch -q origin
sha="$(git -C "$repo" rev-parse --short=7 "$ref^{commit}")"
# Every upload needs a higher build number than the last; the time does that without a counter.
build="$(date -u +%Y%m%d%H%M)"
dir="$mac_dir/luach-release/$sha"

echo "== luach $sha → TestFlight as build $build"
mac "rm -rf $dir && mkdir -p $dir"
git -C "$repo" archive "$sha" ios | mac "tar -x -C $dir"

mac "bash -s -- $(printf '%q ' "$dir" "$build" "$sha")" <<'MAC'
set -euo pipefail
dir=$1 build=$2 sha=$3
set -a; . ~/.appstoreconnect/luach.env; set +a
key=~/.appstoreconnect/private_keys/AuthKey_${LUACH_ASC_KEY_ID}.p8
[ -f "$key" ] || { echo "no API key at $key" >&2; exit 1; }
auth=(-allowProvisioningUpdates -authenticationKeyPath "$key"
      -authenticationKeyID "$LUACH_ASC_KEY_ID" -authenticationKeyIssuerID "$LUACH_ASC_ISSUER_ID")
cd "$dir"/ios && mkdir -p build

# Archived unsigned, signed at export with Apple's cloud-managed distribution certificate through
# the API key: a development signature would want a registered device (there is none: the family
# installs through TestFlight), and the Mac's keychain is locked to an SSH session anyway.
xcodebuild -project Luach.xcodeproj -scheme Luach -configuration Release \
  -destination generic/platform=iOS -archivePath build/Luach.xcarchive archive \
  CODE_SIGNING_ALLOWED=NO DEVELOPMENT_TEAM="$LUACH_TEAM_ID" CURRENT_PROJECT_VERSION="$build" \
  > build/archive.log 2>&1 || { tail -40 build/archive.log; echo "ARCHIVE FAILED"; exit 1; }
echo "archived"

cat > build/export.plist <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>method</key><string>app-store-connect</string>
  <key>destination</key><string>upload</string>
  <key>teamID</key><string>$LUACH_TEAM_ID</string>
  <key>signingStyle</key><string>automatic</string>
  <key>manageAppVersionAndBuildNumber</key><false/>
</dict></plist>
PLIST
xcodebuild -exportArchive -archivePath build/Luach.xcarchive -exportOptionsPlist build/export.plist \
  -exportPath build/export "${auth[@]}" \
  > build/export.log 2>&1 || { tail -40 build/export.log; echo "UPLOAD FAILED"; exit 1; }
echo "uploaded luach $sha as build $build: TestFlight lists it once Apple has processed it (a few minutes)"
MAC

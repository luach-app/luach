# luach for iPhone

A native SwiftUI app over the same HTTP API the web app uses ([docs/API.md](../docs/API.md)).
Nothing on the server is specific to it: it signs in with the `luach_session` cookie like a
browser, and the cookie's max-age keeps it signed in across launches.

It does what the web app does. Tabs, in the web's order:

| Tab | What it does |
|---|---|
| Agenda | Month and Upcoming; open an event, add one on a day, edit or delete it (`Features/Agenda`) |
| Board | A member's day, today up to 30 days ahead: people, events, tasks, ticking; long-press to give or move (`Features/Board`) |
| Approvals | Every held action, Approve / Deny; the badge is the count; the email scan's line while it runs |
| Ask | Text or the mic; the reply streams with its steps, cards, model and copy; earlier conversations to reopen, rename or delete |

The account button on every tab opens Settings in the web's sections: You (profile,
addresses, Gmail, also notify, memory), Calendar feed (luach's events in the iPhone's own
Calendar, through a `webcal://` link: Add to Calendar), Household and Members (owner), Meetings
(booking page, busy calendars), Reminders, Security (passkeys, password, audit trail, delete
account).
Screens are named in `Features/FeatureScreens.swift`. A settings form, the event editor and the
task editor ask "Discard changes?" before Back, Cancel or a swipe drops unsaved edits.

Reminders show on the phone as local notifications (`Reminders.swift`): the app works out the
server's rules (`luach/reminders.py`: a nudge before each timed event, the evening list, the week
ahead) from `/api/reminders` and the next 16 days of the calendar, in the member's zone, and hands
iOS the 64 nearest. They are worked out again at launch, on coming forward, after any change made in
the app, and in a background refresh (`BGAppRefreshTask` `luach.refresh`, which also sets the
Approvals count on the icon). iOS is asked for permission when a reminder is turned on (Settings ›
Reminders), never at launch. Signing out removes them. The Approvals tab asks again every 30 seconds
while it is on screen.

Waiting on Apple signing: creating passkeys (the `webcredentials:` associated domain; until
then the row opens the web) and remote push (APNs). Wall-board pairing is left to the
web: a phone is not a wall screen.

## Any household's luach

Every household runs its own luach, so the app has no server built in. Signing in starts with
"Your luach's address": `luach.example.com` or a full URL (https:// is added when there is no
scheme). Plain http is refused, at home too: a private address names a different machine on every
network, so a phone that remembered `http://192.168.1.20` would send its session cookie to whatever
answers that address on the next Wi-Fi; https proves which server it is, and a household puts luach
behind a reverse proxy anyway (docs/SELF-HOSTING.md). Every request checks it (`API.request`), a
redirect to http is not followed, and an http address an older build saved is forgotten with its
cookie. Debug builds alone may use http to this device's loopback (the screenshots' demo household).
`NSLocalNetworkUsageDescription` is there for an https luach whose name resolves to a home address.
The app asks
that address's `GET /api/auth/status` before showing the username and password, and says so when
it is not a luach, cannot be reached, or has no accounts yet. Once a sign-in succeeds the address
is remembered; the sign-in screen shows it small, with Change, and names the household
(`household` in the status). "Forgot your password?" asks the server to mail a reset link, or, on a
luach that sends no mail, shows the command its owner runs instead. "What's luach?" opens the
project's page (`ServerAddress.about` in `Luach/ServerAddress.swift`). What the phone keeps of a
household (the agenda's cache, the open conversation, held actions, scheduled reminders) is keyed by
the luach and the member and forgotten on sign-out, on deleting the account and on another address.

Not in the app yet, left to the web: single sign-on, signing in with a passkey, and accepting an
invitation (the invitation link opens the web, which makes the account; then sign in here).

## Building

It builds on a Mac with Xcode 27, from `ios/`:

    xcodebuild -project Luach.xcodeproj -scheme Luach \
      -destination 'generic/platform=iOS Simulator' -derivedDataPath build build

The project uses folder-synchronised groups: a new `.swift` file under `Luach/` is part of the
app without touching `project.pbxproj`. The icon — a calendar page on amber with לוח on it — is
drawn on the Mac by `swift ios/scripts/icon.swift <out.png>` (AppKit and the system's rounded
Hebrew), opaque and full bleed as the App Store wants it.

The bundle ID, `io.github.luach-app.luach`, is the published app's. A fork that builds its own app sets
its own bundle ID and team in Xcode (the Luach target's Signing & Capabilities, and the two test
targets'); the scripts read the bundle ID from the project.

## Settings

The scripts in `ios/` (`scripts/test.sh`, `test-prod.sh`, `testflight.sh`, `AppStore/screenshots.sh`)
name no one's hosts. They read these from the environment, or from `ios/scripts/local.env`, a file
of `KEY=value` lines that is not committed; the environment wins over the file
(`scripts/settings.sh` reads both).

| Setting | What it is | Unset |
|---|---|---|
| `LUACH_MAC_HOST` | the Mac that builds, as `ssh` names it | this machine, which has to be a Mac with Xcode |
| `LUACH_MAC_DIR` | where on that Mac each run keeps its copy, from its home folder | `Library/Caches/luach` |
| `LUACH_DEV_SERVER` | the luach the integration and UI tests use, `https://…` | those tests are skipped; unit and hosted tests still run |
| `LUACH_DEV_KUBECONFIG` | the kubeconfig that reaches that luach's pod, to mint each run's session | kubectl's own |
| `LUACH_DEV_NAMESPACE` | that pod's namespace | the kubeconfig's |
| `LUACH_PROD_SERVER` | the family's own luach: `test-prod.sh` reads it, and every test that writes refuses it | no prod check; nothing to refuse |

For example:

    LUACH_MAC_HOST=my-mac
    LUACH_MAC_DIR=Projects/luach-runs
    LUACH_DEV_SERVER=https://test.luach.example.com
    LUACH_DEV_KUBECONFIG=~/.kube/home.yaml
    LUACH_DEV_NAMESPACE=luach-test
    LUACH_PROD_SERVER=https://luach.example.com

On a Mac, with nothing set, `ios/scripts/test.sh` builds and tests right there: the unit and hosted
tests, the rest skipped. `LUACH_MAC_HOST=` (set but empty) runs locally even when `local.env`
names a Mac.

## Looking at a screen without tapping

Debug builds read launch arguments (they land in `UserDefaults`), so a screen can be checked
over SSH: `-server <url>`, `-sessionCookie <token>`, `-signedOut YES`, `-tab`, `-screen <name>`
(any of FeatureScreens), `-ask`, `-showThreads YES`, and each area's own (`-agendaMode month`,
`-boardDay 2`, `-householdScroll hours`, …; grep for `UserDefaults.standard` in its folder).

    D=<simulator udid>     # xcrun simctl list devices available
    xcrun simctl install $D build/Build/Products/Debug-iphonesimulator/Luach.app
    xcrun simctl launch $D <bundle id> \
      -server https://test.luach.example.com \
      -sessionCookie <token> -tab ask -ask "What's on this week?"
    xcrun simctl io $D screenshot /tmp/shot.png

The token is a dev session from `scripts/verify_dev_pod.py mint`, run inside the dev server's
container; log it out when done. `-ask` sends a real turn: keep it to questions on dev.

## Tests

Three layers, run on the Mac (`LUACH_MAC_HOST`, or this one) from this checkout:

| Layer | Where | What it proves |
|---|---|---|
| Unit | `LuachTests` (Swift Testing), answered by `StubServer` | every model, every call (path, query, body, the server's error sentence), every rule; screens hosted in a window for what dev cannot produce |
| Integration | `LuachTests`, `.dev` suites | the app's own calls against dev's real API: reads, and ios-test items created, changed and removed |
| UI | `LuachUITests` (XCTest) | the app tapped through on dev, signed in as dev's owner |

    ios/scripts/test.sh                  # everything, against dev; prints line coverage by file
    ios/scripts/test.sh --unit           # only what needs no server
    LUACH_TEST_NAME=agenda ios/scripts/test.sh -- -only-testing:LuachTests/AgendaDevTests

`test.sh` mints a session in the pod of `LUACH_DEV_SERVER` for the run (with `scripts/verify_dev_pod.py`)
and signs it out after, gives each run its own copy and simulator (`LUACH_TEST_NAME`; an area's
name limits the run to that area's tests), stops any earlier run still going on that simulator, and
fails under `LUACH_COVERAGE_MIN`. With no `LUACH_DEV_SERVER` it mints nothing and the integration and
UI tests skip themselves. It refuses to start when `LUACH_DEV_SERVER` is `LUACH_PROD_SERVER`, and hands
prod's host to the tests (`LUACH_PROD_HOST`), which refuse it too. A full run is about 500 tests and
60 UI tests, 98% of the app's lines.

What a test may do on dev: read anything; create only items titled `ios-test…`, with no one invited,
and remove them before it ends; record a setting before changing it and put it back; never decide a
hold it did not cause, send mail, or touch the household's calendars.

### The prod check

    ios/scripts/test-prod.sh

Read-only, against `LUACH_PROD_SERVER`: `ProdReadTests` read through the app's own calls and decoders,
and `ProdUITests` open every tab and every settings screen a member sees, tapping nothing that writes.
It signs in on the Mac as the `ios-test` member made for it — not the owner, so it also checks that
prod refuses that member the owner's lists and shows them an audit with no addresses in it. The login
lives only on the Mac, in `~/.luach/prod-test.env` (chmod 600):

    LUACH_PROD_USER=ios-test
    LUACH_PROD_PASSWORD=…

A prod run passes the session as `LUACH_PROD_*`, names no other test reads, and every dev test and
helper refuses prod's address besides: nothing that writes can reach the family's luach.

## TestFlight

`ios/scripts/testflight.sh [ref]` (default `origin/main`) builds that commit on the Mac and
uploads it; the build number is the UTC time, so each upload is higher than the last. Signing
is automatic through the App Store Connect API key: no one signs in to Xcode, and the
certificate and profile are made and renewed by xcodebuild. Once, on the Mac:

    ~/.appstoreconnect/private_keys/AuthKey_<KEY_ID>.p8    # the API key, Admin, chmod 600
    ~/.appstoreconnect/luach.env                            # LUACH_ASC_KEY_ID=…
                                                            # LUACH_ASC_ISSUER_ID=…
                                                            # LUACH_TEAM_ID=…

and in App Store Connect an app with the project's bundle ID. The family are
internal testers (users in App Store Connect, in the internal group): no Beta App Review.

## The App Store listing

`ios/AppStore/listing.json` holds the store text and URLs; `python3 ios/scripts/asc.py listing
<listing.json>` on the Mac fills the listing (it never submits), and `ios/AppStore/screenshots.sh`
shoots the screenshots against the invented household in `AppStore/demo_server.py`. What is the
publisher's own stays on the Mac, in `~/.appstoreconnect/luach.env` beside the key's settings (quote
a value with spaces: `testflight.sh` sources the file):

    LUACH_COPYRIGHT="2026 …"                  # the version's copyright line
    LUACH_REVIEW_FIRST_NAME=…                 # App Review's contact
    LUACH_REVIEW_LAST_NAME=…
    LUACH_REVIEW_EMAIL=…
    LUACH_REVIEW_PHONE=…
    LUACH_REVIEW_SERVER=…                     # the address App Review signs in to ({server} in the notes)

and the demo account App Review signs in with, in `~/.luach/review-account.env`
(`LUACH_REVIEW_USER`, `LUACH_REVIEW_PASSWORD`).
`PrivacyInfo.xcprivacy` is what the App Store asks of every upload: no tracking, nothing
collected, `UserDefaults` for the app's own settings.

## Still to do

- **Signing.** The Apple Developer membership and the key above.
- Passkeys and password autofill: an `apple-app-site-association` served by luach, and the
  `webcredentials:` associated domain.
- Remote push for held actions (APNs beside the existing web push), a share extension
  for forwarding text and mail, and Siri / App Intents for "tell luach…".

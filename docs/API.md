# luach HTTP API

All JSON unless noted. Auth is a session cookie `luach_session` (httponly). A
trusted service (a chat bot, for example) may instead send `x-luach-key: <key>` with
the service key (`LUACH_API_KEY`), and acts as the owner; the audit trail and the
`door` of what it does carry the key's name (`LUACH_API_KEY_NAME`, default `service`).
[`scripts/luach-cli.sh`](../scripts/luach-cli.sh) is a small client for that key.
It does not reach the household's keys: members and invites, the owner's sign-in
(`PATCH /api/auth/me`, password, addresses, passkeys), connecting or dropping a mailbox,
push subscriptions and pairing screens answer 403 to it.

A request that changes something (POST, PUT, PATCH, DELETE) without a key must come from
luach's own pages or from outside a browser: an `Origin` or `Sec-Fetch-Site` that names
another site is a 403, and a body must be `application/json` (415 otherwise; a bare
request with no body and no type is fine). `/api/transcribe` takes audio, and still checks
the origin.

Both keys must be at least 32 random characters (`openssl rand -hex 32`); luach refuses
to start with a shorter one or with the example's placeholder. Wrong keys are throttled
per address like passwords: after a few, the address waits (429 with `retry_after`).

A second, read-only key (`LUACH_TULIP_KEY`), for an agent platform, goes in the same
header. It also acts as the owner, named `tulip`, but may only read (the calendar,
family, household, tasks, holds, the audit trail, its threads, memory, upcoming
bookings, health) and talk to the agent, whose gate still decides every write. It never
approves: not with `approved`, not with a "yes", not through the control routes. Any
other route answers 403. Set to the same value as `LUACH_API_KEY`, it is off.

Errors: `{"error": "<human sentence>"}` with 4xx/5xx, and nothing else:

- **400** — the request is wrong: a field missing (`"start is required"`), of the wrong
  kind (`"limit must be a whole number"`), or a value luach will not store (a repeat rule
  it cannot read, an address that is not one, a calendar the credential cannot see).
  Bad input is refused, never quietly dropped or rewritten.
- **401** — sign in first. **403** — signed in, not allowed (not the owner; a child's
  account changing tasks; someone else's conversation).
- **404** — no such thing. An id in a path that cannot be one (a word, or a number past
  2⁶³) is a 404 like any id that is not there. An unknown `/api/...` path is
  `{"error": "no such route"}`.
- **429** — throttled; carries `retry_after` (seconds) where the wait is known.
- A 500 is a bug.

Creates answer 200 with the object. Every DELETE answers `{"ok": true, …}` — some add the
listing that is left (`emails`, `passkeys`, `sources`) or what else happened (`guest_told`,
`revoked`). Ids are integers for members, tasks, boards and busy feeds, and strings for
events, threads and held actions. Times luach keeps (`created_at`, `last_seen`, …) are UTC
with their offset (`2026-09-23T16:41:27+00:00`); event times carry the zone they are in.

Two pairs of names are close on purpose: `/api/booking` is a member's own booking-page
settings and `/api/book/{slug}` is the public page a visitor opens; `/api/boards` is the
owner's list of paired screens and `/api/board/*` is what a screen calls.

Member object:
```json
{"id":1,"username":"robin","email":"…","display_name":"Robin","timezone":"America/New_York",
 "language":"auto","is_owner":true,"last_seen":"2026-09-11T14:00:00+00:00"}
```
Event object:
```json
{"id":"abc","title":"Dentist","start":"2026-09-16T15:00:00-04:00","end":"2026-09-16T15:45:00-04:00",
 "all_day":false,"location":"","description":"","recurrence":[],"recurring_event_id":"",
 "occurrence":false,"html_link":"https://…","creator":"…","updated":"…"}
```
All-day events carry `start`/`end` as `YYYY-MM-DD` (end exclusive, Google style).

## Auth
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/auth/status | | `{users_exist, authenticated, member?, mail:{enabled,sender,own_domain,limitation,offline_reset}, sso:{enabled,label}, household}`; `mail.limitation` says in a sentence what mail cannot do ("" when it works; without mail it names the offline reset, `offline_reset`); `household` is the household's name (`LUACH_HOUSEHOLD_NAME`, "" when unnamed), for the sign-in screen |
| POST | /api/auth/register | `{setup_code,username,email,password,display_name?,timezone?}` | member; **only while no users exist** (bootstrap), else 403. `setup_code` is the one-time code the server logs at startup while it has no accounts (or `LUACH_SETUP_CODE`); missing or wrong is a 403, and repeated wrong codes a 429. Only one owner is ever made, however many arrive at once |
| POST | /api/auth/login | `{username,password}` (username or email) | member; 401 bad; 429 `{error,retry_after}` |
| POST | /api/auth/logout | | `{ok:true}` — open, so a stale cookie can always be cleared |
| GET | /api/auth/me | | member |
| PATCH | /api/auth/me | `{display_name?,timezone?,language?,email?,model?}` | member (`email` only to one of your confirmed addresses, as `/api/auth/emails/primary`; a new one is added and confirmed first; 400 otherwise, and nothing is changed) |
| POST | /api/auth/password | `{current,new}` | `{ok}`; 401 when `current` is wrong. Every other session of the member is signed out |
| DELETE | /api/auth/me | `{password}` | `{ok}`, signed out: the member deletes their own account. 401 when `password` is wrong (counted like a wrong sign-in: 429 `{error,retry_after}` after too many); 409 for the owner while anyone else belongs (remove the others first). Their sessions, addresses, passkeys, conversations, reminders, busy feeds, booking page, Gmail connection (revoked at Google) and remembered facts go; holds they caused stay as nobody's, and their family entry stays for the owner. The owner deleting the last account returns luach to first-run setup |
| POST | /api/auth/forgot | `{email}` | `{ok:true}` always |
| POST | /api/auth/reset | `{token,password}` | member (signed in) |
| GET | /api/auth/invite/{token} | | `{email,inviter,expires_at}` or 404 |
| POST | /api/auth/accept | `{token,username,password,display_name?,timezone?}` | member (signed in). `timezone` (IANA) is where the new member starts; an unknown one is a 400, none means the default |

Deep links the mails use: `/?invite=<token>`, `/?reset=<token>`.

## Single sign-on (OIDC)
Additive to passwords and passkeys: an existing member may also sign in through
an OpenID Connect provider. It never creates an account. All three paths are
open (no session needed); while single sign-on is not configured `config` says
`enabled:false` and the other two return 404.

| Method | Path | Returns |
|---|---|---|
| GET | /api/auth/oidc/config | `{enabled, label}` (same as `sso` in `/api/auth/status`) |
| GET | /api/auth/oidc/start | 302 to the provider (code flow, PKCE S256); sets the short-lived `luach_oidc` cookie |
| GET | /api/auth/oidc/callback?code&state | 302 to `/` signed in, or to `/?sso=failed` (the reason is only in the server log) |

The callback requires the `luach_oidc` cookie and a matching `state`, exchanges
the code at the token endpoint (HTTP Basic client auth), reads userinfo, requires
the required group in the groups claim, and matches the email claim
(case-insensitively, primary or extra address) to a member.

| Variable | Default | Meaning |
|---|---|---|
| `LUACH_OIDC_ISSUER` | — | Issuer exactly as the provider publishes it, trailing slash included; discovery is `{issuer}.well-known/openid-configuration` and its `issuer` must match |
| `LUACH_OIDC_CLIENT_ID` | — | OAuth client id |
| `LUACH_OIDC_CLIENT_SECRET` | — | OAuth client secret (secrets.env) |
| `LUACH_OIDC_REQUIRED_GROUP` | `admins` | Group the member must hold; set but empty switches single sign-on off (never "anyone") |
| `LUACH_OIDC_LABEL` | `Sign in with single sign-on` | Button text on the sign-in page |
| `LUACH_OIDC_SCOPES` | `openid email profile groups` | Requested scopes |
| `LUACH_OIDC_GROUPS_CLAIM` | `groups` | Userinfo claim holding the group list |
| `LUACH_OIDC_EMAIL_CLAIM` | `email` | Userinfo claim holding the email |
| `LUACH_OIDC_REDIRECT_URI` | `{LUACH_APP_URL}/api/auth/oidc/callback` | Override for the registered redirect URI |
| `LUACH_OIDC_HTTP_TIMEOUT` | `10` | Seconds for each call to the provider |

Single sign-on is enabled only when issuer, client id and secret are set and the
required group is not empty.

## Members (owner only)
| GET | /api/members | | `{members:[member…], invites:[{email,created_at,expires_at,expired}]}` |
| POST | /api/members/invite | `{email}` | `{sent:bool, link?, mail?, warning?}`. Unsent: `link` to pass on, `mail` is `not_configured` (no `RESEND_API_KEY`) or `failed` (the log says why); `warning` when the link is not built from `LUACH_APP_URL` (unset or localhost: the request's origin is used) or that address differs from the one in use |
| DELETE | /api/members/{id} | | `{ok}` (owner cannot be removed) |
| DELETE | /api/members/invite/{email} | | `{ok, revoked:n}`; 404 when no invitation is waiting for it |

## Calendar (any member; a click is the approval, these are audited as human actions)
| GET | /api/calendar/events?start=YYYY-MM-DD&end=YYYY-MM-DD | | `{events:[Event…], timezone, start, end}` — any dates, past or future; at most 400 days per request (400 otherwise), so page month by month |
| GET | /api/calendar/events/{id}?calendar= | | Event (`calendar` narrows the lookup to one of the household's calendars, and is a 400 for any other id, on GET, PATCH and DELETE here and under `/api/board/events`; otherwise every household calendar is tried) |
| POST | /api/calendar/events | `{title,start,end?,location?,description?,recurrence?:string,calendar_id?,attendees?:string[],leader?}` | Event |
| PATCH | /api/calendar/events/{id}?calendar=&scope=this\|series | any of `{title,start,end,location,description,recurrence,attendees,leader}` | Event — on an occurrence with `scope=series`, the series |
| DELETE | /api/calendar/events/{id}?calendar=&scope=this\|series | | `{ok, guest_told}` — `guest_told` is whether a booked visitor was told it is off |
| GET | /api/calendar/identity | | `{backend,auth,service_account,calendar,calendars}` |

`start`/`end` for POST/PATCH: `YYYY-MM-DDTHH:MM` in the member's zone, or `YYYY-MM-DD` for all-day.
On PATCH a new `start` alone keeps the event's length, and a new `end` alone keeps its start.
A `start`/`end` equal to what the event has is no change (a form sends them either way).

### Repeating events
A repeating event is a series: one event whose `recurrence` holds its rule. The
list (`GET /api/calendar/events`) never shows the series itself: it shows each
**occurrence** in the window, as Google does, with
- `id`: the occurrence's own (`<series id>_<its original start>`);
- `occurrence: true` and `recurring_event_id`: the series' id;
- `recurrence`: **the series' rule** (so a form opened on one shows how it repeats).

`GET /api/calendar/events/{id}` answers an occurrence's id with that occurrence,
and the series' id with the series (`occurrence: false`).

On an occurrence, PATCH and DELETE take `scope`:
- `this` (the default): that occurrence alone. A PATCH moves or changes it on its
  own (Google keeps it as an exception to the series); a DELETE cancels it, and the
  rest of the series stays. One occurrence cannot repeat on its own: a
  `recurrence` other than the series' rule (or `""`, which older clients sent
  for an occurrence they showed as not repeating, and which is ignored) is
  refused with 400.
- `series`: every occurrence. The change is made to the series, translated from
  the occurrence it was made on: a new start or end moves the series' own by as
  many days as the occurrence moved, to the occurrence's new time of day, and a
  weekly rule's `BYDAY` moves with it (every Tuesday, moved from one Tuesday to
  a Thursday, becomes every Thursday) unless the PATCH sets its own `recurrence`.
  A DELETE deletes the series.

On the series' own id, or an event that does not repeat, `scope` changes nothing.
Any other `scope` is refused with 400. There is no "this and following": in
Google it means ending the series with an `UNTIL` and starting a new series with
the changes, carrying over the exceptions after the split, and luach does not do
it yet.

`recurrence` on POST and PATCH is one RRULE (`FREQ=WEEKLY;BYDAY=TU`, with or
without `RRULE:`), `""` (none), or one of the words a Repeats menu offers:
`daily`, `weekly`, `biweekly`, `monthly`, `yearly`, `none`. The server makes a
word into a rule on the event's own day in the member's zone (its new `start`,
or the one it has), so `weekly` on an all-day event on Thursday 17 September is
`RRULE:FREQ=WEEKLY;BYDAY=TH` wherever the client is. Clients send `recurrence`
only when the person changed how it repeats.

An Event carries `calendar_id`, `color_id` (Google's event colour, `""` for the
calendar's own) and `attendees` (emails, the account itself excluded).
`recurrence` (see Repeating events) is refused with 400 when it cannot be read; so
is any `attendees` entry that is not an email address. On POST, `calendar_id` must be one of the household's calendars
(default: the household's default calendar) and `attendees` absent means
"the household's default invitees" while `[]` means nobody. Attendees get a
Google invitation. `invite_error` is set on the returned Event when the
event was saved but the credential could not invite anyone (a service
account without domain-wide delegation; `LUACH_CALENDAR_AUTH=oauth` fixes it).

`leaders` is everyone in the family an event is for (their `key`s, `[]` for the
whole family), and `leader` is the first of them, for clients that read one. On
POST/PATCH send `leaders: [key…]`, or `leader` as one key or a comma list
(`"ruby,lily"`); `""` makes it nobody's. An event for several people shows in each
of their columns on the house board, wears the first one's colour, and invites
every one of them who has an address. They are kept on the Google event as `extendedProperties.shared.luach_leader` (a comma list)
with that person's `colorId`, and the leader is invited when they have an
address. An event made in Google Calendar without luach is read as someone's,
in this order: the leader luach marked (`"-"` means nobody's, and is final);
the one person whose colour it wears; the people its title names
(`Ruby: …`, `Ruby and Lily: …`, `Ruby - …`, `… (Ruby)`, `Ruby's …`); the one
family member invited. Colours are one person each, so a colour always means somebody.

## Family (any member reads; the owner writes)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/family | | `{people:[Person…], colors:[{id,name,hex}…]}` |
| POST | /api/family | `{name, kind?:"adult"\|"kid", color?, email?}` | Person |
| PATCH | /api/family/{key} | any of `{name,kind,color,email,position}` | Person |
| DELETE | /api/family/{key} | | `{ok}` |

A Person is `{key,name,color,hex,kind,email,user_id,position}`. People are not
accounts: a child needs none. A person with an address is linked to the account
that signs in with it. `color` is one of Google Calendar's eleven event colours
(`"1"`–`"11"`), so luach and Google show the same one. A new box starts with one
person per existing account.

## Tasks (anyone ticks; the grown-ups decide)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/tasks?day=YYYY-MM-DD&person= | | `{day, tasks:[Task…], may_assign}` — day defaults to today in the member's zone; a `person` not in the family is a 400 |
| GET | /api/tasks/all | | `{tasks:[Task…], may_assign}` — every open to-do and every chore |
| POST | /api/tasks | `{title, person?, due?:YYYY-MM-DD, days?:["MO"…"SU"], notes?}` | Task |
| PATCH | /api/tasks/{id} | any of `{title,person,due,days,notes}` | Task |
| DELETE | /api/tasks/{id} | | `{ok}` |
| POST | /api/tasks/{id}/done | `{day?, done?:bool}` | Task |

A Task is `{id,title,person,due,days,notes,done,overdue,chore}`. With `days` it is
a **chore**: it falls on those weekdays and is done for a day, not for ever. Without,
it is a **to-do**: it shows from its due day (or at once, undated) until ticked, and
is `overdue` after its day. A day's list also keeps the to-dos ticked that day.

Ticking is open to every member. Adding, changing and removing are for the owner
and the adults of the family (`may_assign`); a member whose family entry is a
child gets 403.

## House board (a paired screen; not a member)
| Method | Path | Body / header | Returns |
|---|---|---|---|
| POST | /api/board/pair | | `{code, secret, expires_at}` — the screen shows `code`, keeps `secret` |
| GET | /api/board/pair/{code} | `x-luach-pair: <secret>` | `{waiting:true}` until claimed, then `{token}` once; 404 when expired or already collected |
| GET | /api/board/today?day= | `x-luach-board: <token>` | `{board, viewer, can_edit, language, timezone, now, today, day, people, events, tomorrow, tasks}` — `day` is today or up to 30 days ahead (`tomorrow` is the day after it); events carry `leaders` (and `leader`, the first) |
| POST | /api/board/tasks/{id}/done | `x-luach-board`; `{done?:bool, day?}` | Task — ticked for the day on the screen |
| GET | /api/board/events/{id}?calendar= | | Event — to a paired screen without `html_link` or `attendees` |
| GET | /api/board/calendars | `x-luach-board` | `{calendars, default_calendar, default_attendees:[], available}` — only the calendars the household uses, for the board's own event form |
| POST · PATCH · DELETE | /api/board/events[/{id}] | as `/api/calendar/events`, `scope` too | the same answers — the same code, so the same checks |
| POST · PATCH · DELETE | /api/board/tasks[/{id}] | as `/api/tasks` | Task, or `{ok}` |
| PATCH | /api/boards/{id} | owner; `{can_edit?, name?, language?}` | `{boards}` — `language` is `auto` (follow the screen's browser), `en`, `es` or `he`; anything else is a 400 |

Changing things from the board needs a member's session or a screen whose owner left
`can_edit` on (the default for a paired screen); otherwise 403. A screen acts with the
owner's authority and is named on the audit trail as `board:<name>`. Because it does, a screen
invites nobody: `attendees` it sends are ignored (a new event gets none beyond the family
people it is for), and an event's guests stay as they are.
| GET | /api/boards | owner | `{boards:[{id,name,created_at,last_seen,can_edit,language}]}` |
| POST | /api/boards | owner; `{code, name?}` | `{id, name}` — pairs the screen showing `code` |
| DELETE | /api/boards/{id} | owner | `{ok}` — the screen goes back to showing a code |

A board never holds a session. `/api/board/*` is open at the auth wall and each
route checks for a board token or a member's session itself; a board token opens
nothing outside `/api/board/*`. A signed-in member gets the same day (with
`board: ""` and `viewer` set) and their ticks are recorded as theirs — the board
on their own phone or laptop, with nothing to pair. Codes are six characters without 0/O/1/I/L and live ten minutes.
The web app serves the board at `/board`, keeping its token in localStorage; opened
by someone signed in it shows the day straight away. The app has a Board tab too.

`LUACH_FAMILY` (e.g. `Robin; Alex; Ruby:kid; Lily:kid:lily@example.com`) adds whoever is
missing from the family at startup, by name. It never changes or removes anyone.

## Household (any member reads; the owner writes)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/household | | `{calendars:[id…], default_calendar, default_attendees:[email…]}` |
| GET | /api/household/calendars | | the same plus `available:[{id,name,color,primary,writable,enabled,default}]` — for the owner every calendar the credential can see; for anyone else only the household's own |
| PATCH | /api/household | any of `{calendars:[id…], default_calendar, default_attendees:[email…]}` | the snapshot; 400 on an invalid email, an empty calendar list, a calendar the credential cannot see (one already in use is always kept), or nothing to change; 502 when the calendar cannot be reached to check |

The list of calendars is what luach reads, searches and de-duplicates
against; the default calendar is where new events go unless one is named;
the default invitees are added to every new event unless the person says
who to invite (the agent's `attendees="none"` invites nobody).

## Models (any member reads; the owner manages)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/models | | `{models:[id…], default, configured, catalogue:[{id,name,about,local,provider,health:{status,since,reason}}], chosen}` |

The members' menu: the household's default first, then every model the owner has
enabled, in the owner's order. `local` is a model on the household's own computer
(nothing leaves the house); `provider` says who answers a cloud one ("Google, through
OpenRouter"), `""` for a local one. `health.status` is `ok` or `not_answering` (with
`since` and the provider's `reason`); a model not answering cannot be picked.
`configured` is false while there is no endpoint (`OPENAI_BASE_URL`) or no default
model: every turn then answers that no model is set up.
`chosen` is the member's own pick, `""` for the default.

A member saves their pick with `PATCH /api/auth/me {"model": id}` (`""` for the
default; 400 for a model not on the menu, or not answering). It follows them to every
door — the web, the kitchen screen, the email door. `POST /agent` and `/agent/stream`
also take an optional `model`; a name that is not on the menu is passed over
(the member's pick answers, then the default) and never reaches the model server,
which would serve any model in its catalogue. The stream says which model is
answering in a `{"type":"model","name":…}` frame; it is not stored on the
thread.

### The owner's routes

Only the owner, signed in. A member gets 403, and so do both keys: the agent
platform's key at the wall, and the trusted service's key (`LUACH_API_KEY`) here —
which models the family's questions go to is decided by a person. Every write is on
the audit trail (`models.added`, `models.changed`, `models.removed`,
`models.reordered`, `models.default`, `model.trial`, `model.not_answering`).

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/models/manage | | the snapshot (below) |
| POST | /api/models/manage | `{id, name?, about?, local?, provider?, try?}` | the snapshot, plus `{added, trial_started, note}`; the model is on the list but **not enabled**; "Try it" starts unless `try:false` (`note` says why it did not) |
| PATCH | /api/models/manage | `{id, name?, about?, provider?, enabled?, local?}` | the snapshot; disabling the default is refused |
| POST | /api/models/manage/remove | `{id}` | the snapshot; removing the default is refused |
| PUT | /api/models/manage/order | `{ids:[every id on the list, in the new order]}` | the snapshot |
| PUT | /api/models/manage/default | `{id}` | the snapshot; the model is enabled; one not answering is refused |
| GET | /api/models/manage/trial | | `{trial, trials_left_today}` |
| POST | /api/models/manage/trial | `{id}` | `{trial, trials_left_today}`; 409 while one runs, or when the day's trials are used |
| POST | /api/models/manage/trial/cancel | `{}` | `{cancelled, trial}` |
| POST | /api/models/manage/check | `{id}` | `{ok, reason, health, models}`: one tiny request to the model |
| GET | /api/models/catalogue?q=&fresh= | | `{configured, source, models:[{id,name,context_length,tools,price_in,price_out,alias,recommended,alias_of_it,provider,on_menu}], error}` |

The snapshot: `{default, configured, models:[{id, name, about, local, provider,
provider_set, enabled, position, is_default, meta:{context_length?, tools?, price_in?,
price_out?}, health, failures, last_ok_at, trial:{passed,total,verdict,at}|null}], trial,
trials_left_today, catalogue:{configured, source}}`. `provider_set` is what the owner
typed (`""`: worked out from the id).

Ids are up to 128 characters of letters, digits and `. _ ~ / @ + - :`, starting with a
letter, digit or `~`; no spaces, no `//`, and a colon only between two parts, as in Ollama's
`qwen3:8b` (400 otherwise). A name is at most 60
characters, `about` 300, `provider` 80; the list holds at most 30 models.

**The catalogue** is the endpoint's own `GET {OPENAI_BASE_URL}/models`, or
`LUACH_MODEL_CATALOGUE_URL` with `LUACH_MODEL_CATALOGUE_PREFIX` put before each id.
Only that configured address is fetched (no request parameter names a URL), with a
6-second timeout, no redirects, 8 MB at most, and kept for ten minutes (`fresh=true`
fetches it again). The endpoint's key is sent only to the endpoint's own host. Prices
are US dollars per million tokens, when the catalogue gives them; `tools` is whether
the model takes tools (`null`: the catalogue does not say). `alias` marks a name that
moves with the provider's newest version (OpenRouter's `~…` ids, `…-latest`); these are
`recommended`, because a retired version cannot strand them, and `alias_of_it` on a
pinned version names the alias that would follow it. A catalogue that cannot be read
answers 200 with `error` set.

**Trial** ("Try it"): `{id, model, status: running|done|failed|cancelled, requested_by,
started_at, finished_at, done, passed, total, verdict: good|fair|low|null, cases:[{case,
about, ok, problems, tools}], error}`. Twelve of luach's own cases — greetings in three
languages, reading the week and a day, a free time, adding an event, a correction, a
follow-up, a cancellation the gate must hold, an event for a child in Spanish — scored by
the tools each turn called and what ended up on the calendar. It runs in a child process
on a fake calendar and a throwaway database (or schema), with none of the household's
credentials. One at a time, at most `LUACH_MODEL_TRIALS_PER_DAY` (6) in 24 hours, 15
minutes at most. A model the provider refuses fails at once, before any case. `good` is
every case, `fair` at least 80%, `low` below: advice, the owner decides what to enable.

**Not answering.** A model the provider refuses (404, or a 400 that says the model is
not found or has no endpoint) is marked at once; any model is marked after three failed
turns in a row. The owner is pushed (and mailed, when mail is set up), members who had
picked it go back to the default and their next answer begins by saying so, and the
menu shows it. Any answer, a check, a trial that completes, or the hourly re-check of
models marked this way clears it.

## Agent
`POST /api/agent/stream` `{text, thread_id?}` → `text/event-stream`; each line `data: <json>`:

| type | fields |
|---|---|
| session | `thread_id` |
| model | `name` — the model answering; sent again if the router hands the turn to another |
| token | `text` (assistant text delta) |
| retract | — take back every token since the last `retract`: a later model call is about to speak and its words replace them |
| thinking | `text` (reasoning delta, optional) |
| tool_start | `tool, args` |
| tool_result | `tool, result, error?` |
| held | `id, tool, summary, reason:[…], reason_text` — render an approval card |
| done | `reply, thread_id, tool_calls:[…], held:[…], created:[compact events], widgets:[…], model` — `reply` is the answer: show it in place of what streamed when they differ |
| error | `message` |

`POST /api/agent` `{text, thread_id?, model?, approved?:bool}` → the `done` payload as JSON (plus `error`). This is the one a trusted service uses; `approved` (the person already said yes) counts only from the service key. Both answer 403 before any turn starts when `thread_id` is another member's. An unknown `thread_id` starts a new conversation under that id (letters, digits, `-`, `_`; at most 64); omit it and luach makes one. A turn stopped mid-way (the browser's Stop, a closed tab) is kept in its thread, its reply ending `(stopped)`.

Threads: `GET /api/threads?limit=50&before=` → `{threads:[{id,title,door,turns:n,created_at,updated_at}], more, retention_days}` — newest first, `limit` 1–200; when `more`, pass the last `updated_at` as `before` for the next page; `GET /api/threads/{id}` → `{id, turns:[{role,content,events,created_at}]}`; `PATCH /api/threads/{id}` `{title}` → `{id,title}`; `DELETE /api/threads/{id}` (drops the model-side checkpoint too). All four are scoped to the caller — a household shares a calendar, not its conversations. A thread nobody comes back to is swept after `LUACH_THREAD_RETENTION_DAYS` (60; 0 turns the sweep off).

A turn can take several model calls, and a model may answer, call a tool and answer again; without `retract` a client that only appends tokens shows the answer two or more times. Words before a tool that nothing replaces stay. luach also rewrites an answer that is not true (a write held for approval, a turn that called no tool), so `done.reply` has the last word.

The stream carries `: keepalive` comment lines while a turn is quiet, so a hop between the browser and the app does not close it. They are not frames: skip any line that starts with `:`.

## Memory
What luach remembers about a member outlives every thread. Storage is tulip's `PgMemory` (Postgres + pgvector) with a local ONNX embedder, keyed `(member-<id>, "luach", "facts")`; `namespace[0]` is PgMemory's tenant boundary, so one member's facts are not another's. Unset `LUACH_MEMORY_DSN` means no memory at all: the tools are not offered and these routes answer 503.

Every turn starts with the member's facts, fenced as reported speech, after the `[context]` line; slow or broken memory never holds a turn up. The model saves with `remember` and drops with `forget`. The member manages their own:

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/memory | | `{facts:[{key, topic, fact, saved_at}]}` — the caller's own only |
| POST | /api/memory | `{fact, topic?}` | the listing; saying the same topic again replaces it |
| DELETE | /api/memory/{key} | | `{ok, facts}`; 404 when luach does not remember it |

## Your email (each member, their own mailbox only)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/mail | | `{connected, address, via:"own"\|"household"\|"", can_connect, scan:{available, enabled, since, minutes}, lost}` — `lost` is `{address, since, via:"own"\|"household"}` once Google refused the grant (expired, revoked; `household` is the email door's, shown to the owner), until the member reconnects or dismisses it; else `null`. The member is told once, by push and (when luach sends mail) email |
| GET | /api/mail/connect | | 302 to Google's consent screen (`gmail.readonly`, PKCE) |
| POST | /api/mail/connect/app | | `{url}`: the same consent, for the iPhone app's browser sheet, which has no luach session. The member and the PKCE verifier travel in `state`, sealed with the mail key for ten minutes; no cookie is set. 409 when connecting is not set up |
| GET | /api/mail/callback | | 302 back to Settings, `?mail=connected` or `?mail=failed` (`&reason=not-yours` when the Gmail signed in to is not one of the member's confirmed addresses; the grant is then revoked at Google) — or, for a connect the app started, to `luach://mail?mail=confirm&nonce=<nonce>` / `luach://mail?mail=failed[&reason=not-yours]`. Nothing is stored for an app connect until the app claims the nonce. Open at the auth wall: a web connect is still checked against the session it began in |
| POST | /api/mail/connect/app/finish | `{nonce}` | the status, once the grant held under `nonce` is stored. Needs the session of the member who started the connect; the nonce works once and for ten minutes. 409 otherwise (claimed by another member: the grant is revoked too) |
| DELETE | /api/mail | | `{ok, …status}`: forgotten here, revoked at Google, and the scan switched off. With nothing connected it dismisses `lost` instead; 404 when there is neither |
| PATCH | /api/mail/scan | `{enabled: bool}` | the status; 409 when no mailbox is connected or the scan is off on this luach (`LUACH_MAIL_SCAN_MIN=0`) |

**The email scan.** With it on, every `LUACH_MAIL_SCAN_MIN` minutes (10) luach reads
what has arrived in that member's inbox since they turned it on — not Gmail's
promotions, social or forums tabs, not their sent mail, not mail luach sent, and
not mail whose sender Gmail could not authenticate — and runs one turn per
message that can only propose (`door: "email-scan"`). That turn is offered the
calendar reads and `create_event`, nothing else, and every call it makes is held
with the reason `from-your-email`. A message is read once per member, whatever
came of it, so a proposal turned down is never offered again. When it finds
something, only that member gets the push.

## Control (any member; the household shares one calendar so everyone sees holds)
| GET | /api/control/pending?all=1 | | `{pending:[{id,tool,args,summary,reason:[…],principal,door,status,created_at,decided_at,decided_by,result,source}]}` |
| POST | /api/control/pending/{id}/approve | | the row, status `approved` (executes the held call), or `failed` with `result.error` when the call was refused and nothing changed; 409 `already <status>` once decided, or `already decided: someone is approving it now` while another approval of it runs; 502 when the calendar raised |
| POST | /api/control/pending/{id}/deny | | the row, status `denied`; 409 once decided |

A row's `status` is `pending`, `running` (an approval's call is running now; it never
goes back to `pending`), `approved`, `failed` (approved, but the call was refused) or `denied`.

The one exception to "everyone sees holds": a proposal the email scan found in
someone's own mail (`door: "email-scan"`) is listed, approved and denied by that
member only — for anyone else it is a 404, not a 403. Its `source` is
`{kind:"email", id, subject, from, when}`; `null` for everything else.

`/api/control/approve/{id}` and `/api/control/deny/{id}` still answer, for callers that
used them.
| GET | /api/control/audit?limit=200 | | `{entries:[{seq,ts,event_type,payload,hash}], total, chain_total, chain_verified, head, scope}`. The owner reads every record (`scope:"household"`); a member only their own (`scope:"yours"`: what they did, said, asked for or approved, and bookings with them). What someone said (`text`, `said`, `source_text`) and the details of a proposal from someone's own mail show as `…` to everyone else, the owner included; addresses lose their local part for anyone but the owner. `total` counts what this reader may read, `chain_total` the whole chain; `chain_verified` is checked over the whole chain |

## Voice
`GET /api/transcribe/status` → `{available}`.
`POST /api/transcribe` raw audio body (Content-Type `audio/webm`, `audio/mp4`, `audio/ogg`…), ≤ 12 MB → `{text}`; 503 when no transcriber is configured.

## Push
`GET /api/push/key` → `{public_key}` (empty when unconfigured); `POST /api/push/subscribe` `{subscription}` (the endpoint must be a public `https` address and the subscription carry `keys.p256dh` and `keys.auth`, 400 otherwise; 409 when that endpoint is another member's device); `POST /api/push/unsubscribe` `{endpoint}` (stops only the caller's own device; `{ok:true}` either way).

## Health
`GET /api/health` → `{ok, version, build}` (no auth). `build` is the web app's entry script
(`/assets/index-<hash>.js`, `""` without a built app); a wall board reloads itself when it changes.
Nothing else is public: what follows names the household's calendars and accounts.

`GET /api/health/details` → `{ok, version, build, calendar:{backend,auth,service_account,calendar,calendars}, model:{id,base_url} (or `"not configured"`), memory:{configured,ok,error,checked_at, backend?,semantic?}, members:n}` for a signed-in member or the service key (401 without; the tulip key is refused with 403). `backend` and `semantic` only when a memory database is configured.

`memory.ok` is the last probe's verdict, not a live check: the endpoint never waits on one, because the first probe after a start loads an ONNX model, and a readiness check usually allows only a few seconds. `configured:false` means no memory database; `ok:false` means there is one and recall is broken — which is worth an alert, because a memory tool that raises still produces a friendly reply and nothing else will say so. `ok` at the top level stays true either way: a household whose memory is down should still get its calendar.

## Widgets (stream frames the UI renders as cards)

After a read tool completes, the stream emits one `widget` frame; the `done`
payload also carries them all as `widgets: [...]` so a reloaded thread and
a trusted service see the same data. The assistant's text deliberately does NOT repeat
what the widget shows.

| kind | data | when |
|---|---|---|
| `agenda` | `{title, events:[Compact…], truncated}` | `list_events`, `find_events` (title e.g. "Fri 11 – Thu 17 Sep" or "Search: dentist") |
| `availability` | `{start, end, free, clashes:[Compact…]}` | `check_availability` |
| `event` | `{event: Compact}` | `get_event` |

Compact event: `{id, title, when, start, end, all_day?, location?, recurring?, description?, link?}` —
`when` is a human line in the member's zone ("Fri 11 Sep 2026, 12:30–13:30"); `link` is the Google Calendar URL.
Frame: `{"type":"widget","kind":"agenda","data":{…}}`. Stored turns (`GET /api/threads/{id}`) carry them in `events` as `{"widget": {kind, data}}` entries.

## Multiple emails per member
A member has one primary email (`member.email`) plus any number of extra addresses; login accepts any of them, invitations refuse any of them, and the email door attributes a labelled message to the member who sent it.

| GET | /api/auth/emails | | `{primary, emails:[{email, added_at}]}` |
| POST | /api/auth/emails | `{email}` | the same listing (400 if it belongs to someone) |
| DELETE | /api/auth/emails/{email} | | `ok` and the same listing (400 for the primary, 404 for an address that is not yours) |
| POST | /api/auth/emails/primary | `{email}` | the same listing (must already be one of yours) |

`member` objects gain `emails: [string…]` (all addresses, primary first).

## Confirming an address
An address a member adds — a sign-in alias or an also-notify inbox — is a claim until the
link mailed to it is followed. Until then it cannot sign in, cannot be made primary, does
not name its claimant to the email door or to SSO, and is invited to nothing.

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | /api/auth/emails/resend | `{email}` | `{sent, email}` (400 when nothing is waiting) |
| POST | /api/auth/verify | `{token}` | `{email, kind}` — **open**: the link is read on whichever device opened the mail |

`GET /api/auth/emails` rows carry `verified`; `member` objects carry `notify_pending`
beside `notify_emails`. At most 10 extra addresses per member.

## Also-notify addresses
Inboxes that get a Google Calendar invitation to every event the member creates — a work
address, say. They are not sign-in addresses. `PATCH /api/auth/me` takes
`notify_emails: [string…]` (at most 10, replaces the list) alongside the profile fields, and
every `member` object carries `notify_emails`.

Only confirmed addresses are ever invited. They ride along when the invitee list is *defaulted*: `POST /api/calendar/events` without
`attendees`, and the agent's `create_event` with an empty or named `attendees` — but never
when the caller passes an explicit list from the UI, and never for `attendees="none"`.

## Booking (a member publishes hours; anyone with the link takes a slot)
`/api/book/*` is the only part of the API open to a stranger. Slots are the member's weekly
hours minus every timed event on the household's calendars (all-day events do not block),
minus the buffer around each, minus the notice period, and a day disappears once
`max_per_day` bookings sit on it. Taking one re-checks all of that before it writes, so a
race loses with `400 that time has just been taken`. Both public calls are throttled per IP.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/booking | | the member's settings + `link`, `timezone` (signed in) |
| PATCH | /api/booking | any of `enabled, slug, slot_minutes, max_per_day, buffer_minutes, lead_hours, horizon_days, title, location, note, calendar_id, conferencing, notify_host, hours` | the same shape (400 with a sentence) |
| GET | /api/booking/upcoming | | `{bookings:[{start, day, name, email, note, event_id}]}` |
| GET | /api/book/{slug} | | `{host, slug, timezone, slot_minutes, note, location, days:[{day, slots:[{start,end}]}]}` (404 when the link is off) |
| POST | /api/book/{slug} | `{start, name, email, note?, timezone?}` | `{booked, start, end, when, host, manage, confirmation_sent, invite_error}` — `manage` is the visitor's link to move or cancel |
| GET | /api/book/{slug}/manage/{token} | | `{host, slug, timezone, slot_minutes, name, start, when, their_timezone, cancelled, past, days}` — `days` are the slots it could move to |
| POST | /api/book/{slug}/manage/{token}/move | `{start}` | `{moved, start, when}` |
| POST | /api/book/{slug}/manage/{token}/cancel | | `{cancelled}` (plus `already:true` the second time) |

The token in a manage link is the only key to that meeting. Booking, reading a page, and
moving or cancelling are throttled per visitor separately, so failed attempts to book never
stop someone cancelling the meeting they have.

`hours` maps `mon`…`sun` to a list of `["HH:MM","HH:MM"]` windows in the member's timezone;
`start` values in the response carry that zone's offset, so a visitor's browser can render
them locally. `calendar_id` picks one of the household's calendars (`""` = the default).
`conferencing` is `"none"` or `"zoom"`; with `"zoom"` each booking gets a fresh meeting on the
account behind `LUACH_ZOOM_ACCOUNT_ID` / `LUACH_ZOOM_CLIENT_ID` / `LUACH_ZOOM_CLIENT_SECRET`
(a Server-to-Server OAuth app with `meeting:write:admin`), and the join URL becomes the event's
location. If Zoom cannot be reached the booking still stands, with `location` as written.
The settings response carries read-only `zoom_ready`, which is whether the box has those
credentials at all. `notify_host` controls the member's own copy of each booking.
A booking writes an ordinary calendar event on that calendar, with the
visitor and the member's also-notify addresses as attendees, records `booking.created` on
the audit trail, and (when Resend is configured) mails the visitor a confirmation and the
member a note.

## Reminders (each member their own)
| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/reminders | | `{lead_minutes, evening_hour, weekly_day, weekly_hour, by_email}` |
| PATCH | /api/reminders | any of those | the same (400 on an unknown setting or a number out of range) |

`lead_minutes` before each event (0 = off); the evening list at `evening_hour` (−1 = off);
the week ahead on `weekly_day` (0 = Monday … 6, −1 = never) at `weekly_hour`. Push always
when subscribed; email too with `by_email`.

## Busy calendars (a member's read-only feeds)
Another calendar — a work one, say — read from its secret iCal address so its busy time
blocks booking slots and, if asked, shows in the agenda. Nothing is ever written to it.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/busy | | `{sources:[Source…]}` |
| POST | /api/busy | `{url, name?, show_in_agenda?}` | the listing (400 when it is not a calendar feed address, not at a public internet address, or past the limit of feeds). Feeds are fetched from public addresses only: every redirect (at most 3) and the address actually connected to are checked. `last_error` is luach's own sentence, never the feed's text; a feed of more than 5000 events in the next six months is refused |
| PATCH | /api/busy/{id} | any of `{enabled, show_in_agenda, name}` | the listing |
| DELETE | /api/busy/{id} | | `ok` and the listing |
| POST | /api/busy/refresh | | `{read, sources}` — every feed read again now |

A Source is `{id, name, url, enabled, show_in_agenda, last_fetched, last_error, blocks}`.
A feed that is not the caller's is a 404.

## Calendar feed (each member their own; read by the phone's calendar app)
A member's events in their phone's own calendar app (Apple Calendar, Google Calendar,
Outlook), read-only, through a secret link the app subscribes to. Off until the member
turns it on. Signed-in routes; a service key may read the status but not make, reset or
drop a link (403).

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/feed | | `{enabled, scope, created_at, last_read}` — never the link |
| POST | /api/feed | `{scope?}` (`household`, the default, or `mine`) | the status plus `{url, webcal}`, this once (409 when it is already on: reset it instead) |
| POST | /api/feed/reset | | a new `{url, webcal}`; the old link is dead from now (404 when it is off) |
| PATCH | /api/feed | `{scope}` | the status; same link (400 on another scope, 404 when off) |
| DELETE | /api/feed | | `ok` and the status; the link is dead |

The link is `<LUACH_APP_URL>/feed/<token>.ics`; `webcal` is the same with `webcal://`,
which a phone opens in its calendar app. The token is 32 random bytes (43 base64url
characters) and only its SHA-256 is stored, so the link is shown when it is made and
never again. `household` is every event; `mine` is the events the member is one of the
people for, and those for nobody in particular. `last_read` is when a calendar app last
read it (written at most every five minutes).

**`GET /feed/<token>.ics`** is open: no session, no cookie, no key; the token is the
proof. Exactly that path (anything else under `/feed/` is a 404 before any route), and
only `GET` or `HEAD` (405). It answers:

- `200 text/calendar; charset=utf-8`, with an `ETag` (`If-None-Match` gives `304`),
  `Cache-Control: private, max-age=600`, and no `Set-Cookie`;
- `404 {"error": "no such calendar feed"}` for every token that opens nothing (wrong,
  reset, turned off, or a member who was removed), the same answer each time;
- `429` with `Retry-After`: after 20 wrong tokens from one address, 30 reads of one link
  or 60 reads from one address, per five minutes (`LUACH_LOGIN_LOCKOUT_SECS`);
- `503` with `Retry-After` when the calendar cannot be read; the phone keeps what it had.

The calendar covers 30 days back to a year ahead, in the household's zone (`TZID` with a
`VTIMEZONE`; all-day events as `DATE`). Each event is a `VEVENT` with a stable `UID`
(`<event id>@luach`), `LAST-MODIFIED` where luach knows it, the title, place and notes,
and whom it is for: in `household`, `SUMMARY` starts with their names ("Ruby and Lily:
Swimming") unless the title already says them, and `DESCRIPTION` starts with "For Ruby
and Lily", in the member's language. A repeating event is one `VEVENT` with its `RRULE`
cut to the window (its `COUNT` written as an `UNTIL`), an `EXDATE` for each deleted
occurrence (or, in `mine`, one that is someone else's), and a `RECURRENCE-ID` override for
each occurrence changed on its own; a rule that cannot be said exactly is listed one
occurrence at a time. Never in it: attendee or organizer addresses, links to Google,
anything held for approval or proposed by the email scan, and busy calendars. The path is
redacted from the access log (`/feed/…`).

## Passkeys (WebAuthn)
Passkeys are a second way to sign in; username + password stays. Payloads are the browser's own JSON shapes: options come from py_webauthn's `options_to_json` (fields base64url-encoded: `challenge`, `user.id`, `excludeCredentials[].id`, `allowCredentials[].id`), and verify calls take the `PublicKeyCredential` serialised the standard way (`id`, `rawId`, `type`, `response.{clientDataJSON, attestationObject | authenticatorData, signature, userHandle}`, all base64url; `credential.toJSON()` where supported). Every options call returns a `challenge_id` that must be echoed to the matching verify call.

| Method | Path | Body | Returns |
|---|---|---|---|
| GET | /api/auth/passkeys | | `{passkeys:[{id, name, created_at, last_used}]}` (signed in) |
| POST | /api/auth/passkeys/register/options | `{}` | `{challenge_id, options}` (signed in; `options` is the `publicKey` object for `navigator.credentials.create`) |
| POST | /api/auth/passkeys/register/verify | `{challenge_id, credential, name?}` | the passkey listing (400 with a sentence on failure) |
| DELETE | /api/auth/passkeys/{id} | | `ok` and the passkey listing (404 when it is not yours) |
| POST | /api/auth/passkeys/login/options | `{}` | `{challenge_id, options}` (open; discoverable credentials, no username needed) |
| POST | /api/auth/passkeys/login/verify | `{challenge_id, credential}` | member (signed in, cookie set); 401 on failure |

The relying-party id is the app's hostname (from `LUACH_APP_URL`, or `LUACH_RP_ID`): a passkey belongs to that name and works at any address on it. `LUACH_EXTRA_ORIGINS` adds origins a passkey may be used from when luach is reached under more than one address.

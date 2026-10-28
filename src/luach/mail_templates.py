"""Plain text first, an HTML card second. Tables and inline styles only — that
is what mail clients render.

The card is luach's own: the gold logo and the לוח wordmark at the top, a
headline that says what the mail is about, a warm light page, and what matters
(when, where, the list) in a box of its own rather than in a paragraph. The
logo is the app's icon, served by luach itself; with no LUACH_APP_URL there is
no address to load it from, and the wordmark stands alone.
"""

from __future__ import annotations

import html as _html

from luach import config

GOLD = "#f4b942"
INK = "#1d1a14"
BODY = "#3b3628"
MUTED = "#8a8270"
PAGE = "#f6f1e7"
PANEL = "#fbf6ea"

_PAGE = """\
<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">
<title>{title}</title></head>
<body style="margin:0;padding:0;background:{page};-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;opacity:0">{preheader}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{page}">
<tr><td align="center" style="padding:28px 12px">
<!--[if mso]><table role="presentation" width="560" cellpadding="0" cellspacing="0"><tr><td><![endif]-->
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="width:100%;max-width:560px">
<tr><td style="padding:0 4px 18px">{brand}</td></tr>
<tr><td style="background:#ffffff;border-radius:20px;border:1px solid #ece4d2;overflow:hidden">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">
<tr><td style="height:6px;background:{gold};font-size:0;line-height:0">&nbsp;</td></tr>
<tr><td style="padding:30px 32px 8px;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
{kicker}<div style="font-size:24px;line-height:1.3;font-weight:700;color:{ink};margin:0 0 14px">{title}</div>
<div style="font-size:16px;line-height:1.6;color:{body}">{body_html}</div>
</td></tr>
{panel}
{button}
<tr><td style="padding:10px 32px 30px">&nbsp;</td></tr>
</table></td></tr>
<tr><td style="padding:18px 8px 0;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:12px;line-height:1.6;color:{muted};text-align:center">
{footer}<span style="color:#b3aa94">{signature}</span>
</td></tr>
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table></body></html>"""


def signature() -> str:
    """The last line of every mail, the same in all of them."""
    return f"לוח · luach — {config.household_calendar()}"


def _calendar() -> str:
    """The calendar in an invitation: "the <name> calendar", or "the household
    calendar" without a name."""
    name = config.household_name()
    return f"the {name} calendar" if name else "the household calendar"


_BRAND_LOGO = """<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="padding-right:12px"><a href="{home}" style="text-decoration:none"><img src="{logo}" width="44" height="44" alt="luach" style="display:block;border:0;border-radius:12px"></a></td>
<td style="font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"><a href="{home}" style="text-decoration:none"><span lang="he" dir="rtl" style="font-size:24px;font-weight:800;color:{ink}">לוח</span>
<span style="font-size:11px;letter-spacing:3px;color:{muted};padding-left:6px">LUACH</span></a></td>
</tr></table>"""

_BRAND_WORD = """<span style="font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"><span lang="he" dir="rtl" style="font-size:24px;font-weight:800;color:{ink}">לוח</span>
<span style="font-size:11px;letter-spacing:3px;color:{muted};padding-left:6px">LUACH</span></span>"""

_BUTTON = """<tr><td style="padding:18px 32px 0;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
<table role="presentation" cellpadding="0" cellspacing="0"><tr><td style="border-radius:12px;background:{gold}">
<a href="{link}" style="display:inline-block;padding:14px 24px;font-size:16px;font-weight:700;color:{ink};text-decoration:none;border-radius:12px">{label}</a>
</td></tr></table>
<div style="font-size:12px;line-height:1.5;color:{muted};margin-top:12px;word-break:break-all">Or paste this link: <a href="{link}" style="color:{muted}">{link}</a></div>
</td></tr>"""

_PANEL = """<tr><td style="padding:18px 32px 0">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{panel};border-left:4px solid {gold};border-radius:10px">
{rows}</table></td></tr>"""

_DETAIL = """<tr><td style="padding:10px 16px 0 16px;width:84px;vertical-align:top;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:12px;letter-spacing:1px;text-transform:uppercase;color:{muted}">{label}</td>
<td style="padding:10px 16px 0 0;vertical-align:top;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:16px;line-height:1.5;color:{ink};font-weight:600">{value}</td></tr>"""

_ITEM = """<tr><td style="padding:10px 0 0 16px;width:10px;vertical-align:top"><div style="width:8px;height:8px;border-radius:4px;background:{gold};margin-top:7px"></div></td>
<td style="padding:10px 8px 0 10px;width:1%;white-space:nowrap;vertical-align:top;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:15px;color:{muted}">{when}</td>
<td style="padding:10px 16px 0 0;vertical-align:top;font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:16px;line-height:1.5;color:{ink};font-weight:600">{what}</td></tr>"""

#: Space under the last row of a panel, which padding-top alone leaves out.
_PANEL_END = '<tr><td colspan="3" style="height:12px;font-size:0;line-height:0">&nbsp;</td></tr>'


def _e(text: str) -> str:
    return _html.escape(text or "")


def _brand() -> str:
    home = config.app_url()
    colours = {"ink": INK, "muted": MUTED}
    if not home:
        return _BRAND_WORD.format(**colours)
    return _BRAND_LOGO.format(home=_e(home), logo=_e(f"{home}/icon-192.png"), **colours)


def _details(pairs: list[tuple[str, str]]) -> str:
    rows = "".join(
        _DETAIL.format(label=_e(k), value=_e(v), muted=MUTED, ink=INK) for k, v in pairs if v
    )
    return _PANEL.format(panel=PANEL, gold=GOLD, rows=rows + _PANEL_END) if rows else ""


def _items(lines: list[str]) -> str:
    """Reminder lines are "07:10 · Breakfast": the time gets a column of its own."""
    rows = []
    for line in lines:
        when, sep, what = line.partition(" · ")
        if not sep:
            when, what = "", line
        rows.append(_ITEM.format(when=_e(when), what=_e(what), gold=GOLD, muted=MUTED, ink=INK))
    return _PANEL.format(panel=PANEL, gold=GOLD, rows="".join(rows) + _PANEL_END) if rows else ""


def _card(
    preheader: str,
    body: str,
    link: str | None,
    label: str,
    footer: str = "",
    *,
    title: str = "",
    kicker: str = "",
    panel: str = "",
) -> str:
    """`body` is HTML the caller has escaped; everything else is text.

    `footer` says why this person got this mail, when that needs saying; the
    signature under it is the same on every mail."""
    button = (
        _BUTTON.format(link=_e(link), label=_e(label), gold=GOLD, ink=INK, muted=MUTED)
        if link
        else ""
    )
    kick = (
        f'<div style="font-size:12px;letter-spacing:2px;text-transform:uppercase;'
        f'font-weight:700;color:#b8861b;margin:0 0 8px">{_e(kicker)}</div>'
        if kicker
        else ""
    )
    return _PAGE.format(
        preheader=_e(preheader),
        title=_e(title or preheader),
        brand=_brand(),
        kicker=kick,
        body_html=body,
        panel=panel,
        button=button,
        footer=f"{_e(footer)}<br>" if footer else "",
        signature=_e(signature()),
        page=PAGE,
        gold=GOLD,
        ink=INK,
        body=BODY,
        muted=MUTED,
    )


def _hours(n: int) -> str:
    return f"{n} hour{'s' if n != 1 else ''}"


def invitation_subject(inviter: str) -> str:
    return f"{inviter} invited you to {_calendar()}"


def invitation(inviter: str, link: str, hours: int = 48) -> tuple[str, str]:
    text = (
        f"{inviter} invited you to {_calendar()} on luach.\n\n"
        f"Pick a username and password here (the link works for {_hours(hours)}):\n{link}\n\n"
        "luach lets the household add events by typing, talking or forwarding an email. "
        "Everything lands on the one shared calendar."
    )
    body = (
        f"<b>{_e(inviter)}</b> invited you to the family's shared calendar. Pick a username "
        "and a password and you are in.<br><br>Ask luach what is coming up, add something by "
        "typing or talking, or forward it an email — everything lands on the one calendar, "
        "and on the board by the kitchen."
    )
    return text, _card(
        invitation_subject(inviter),
        body,
        link,
        "Accept the invitation",
        "You are receiving this because someone you know typed your address into luach. "
        "If that is a surprise, ignore it and nothing happens.",
        kicker="You're invited",
        title=f"Join {_calendar()}",
        panel=_details([("From", inviter), ("Link works", _hours(hours))]),
    )


def recovery(username: str, link: str, minutes: int = 30) -> tuple[str, str]:
    text = (
        f"Your luach username is {username}.\n\n"
        f"Set a new password here (the link works for {minutes} minutes):\n{link}\n\n"
        "If you did not ask for this, ignore it; your password stays as it is."
    )
    body = "Set a new password with the button below and you are back in."
    return text, _card(
        "Getting you back into luach",
        body,
        link,
        "Set a new password",
        "If you did not ask for this, ignore it; your password stays as it is.",
        kicker="Password",
        title="Getting you back in",
        panel=_details([("Username", username), ("Link works", f"{minutes} minutes")]),
    )


#: Why a reminder arrived, and where to stop it.
REMINDER_FOOTER = "You asked for these in Settings › Reminders, which is also where they stop."


def digest(subject: str, lines: list[str]) -> tuple[str, str]:
    """Several things coming up, one line each ("07:10 · Breakfast")."""
    empty = "Nothing is on the calendar for this stretch."
    text = subject + "\n\n" + ("\n".join(f"- {line}" for line in lines) or empty)
    home = config.app_url()
    return text, _card(
        subject,
        "Here is what is coming up." if lines else empty,
        home or None,
        "Open luach",
        REMINDER_FOOTER,
        kicker="Coming up",
        title=subject,
        panel=_items(lines),
    )


def mail_lost(address: str, link: str | None) -> tuple[str, str]:
    """Google took back luach's access to a member's Gmail: say so, and how to fix it."""
    which = address or "your Gmail"
    text = (
        f"Google stopped luach reading {which}, so new mail is no longer looked through "
        "for things to add.\n\n"
        "Reconnect it in Settings to keep it going"
        + (f":\n{link}" if link else ".")
        + "\n\nGoogle does this when access is revoked, a password changes, or — for a "
        "personal Gmail — about once a week while luach's Google app is in testing."
    )
    body = (
        f"Google stopped luach reading <b>{_e(which)}</b>, so new mail is no longer looked "
        "through for things to add. Reconnect it in Settings to keep it going."
    )
    return text, _card(
        "Gmail disconnected — reconnect",
        body,
        link,
        "Reconnect Gmail",
        "Google does this when access is revoked, a password changes, or — for a personal "
        "Gmail — about once a week while luach's Google app is in testing.",
        kicker="Gmail",
        title="Gmail disconnected",
    )


def event_reminder(title: str, when: str, where: str = "") -> tuple[str, str]:
    """One thing about to start: what, when and where, each on its own line."""
    text = f"{title}\n\nWhen: {when}" + (f"\nWhere: {where}" if where else "")
    home = config.app_url()
    return text, _card(
        f"{title}, {when}",
        "This is starting soon.",
        home or None,
        "Open luach",
        REMINDER_FOOTER,
        kicker="Reminder",
        title=title,
        panel=_details([("When", when), ("Where", where)]),
    )


def booking_host_notice(
    kicker: str, title: str, guest: str, when: str, where: str = ""
) -> tuple[str, str]:
    """To the member whose booking link was used: who, and when, in their hours."""
    text = f"{title}\n\nWho: {guest}\nWhen: {when}" + (f"\nWhere: {where}" if where else "")
    home = config.app_url()
    return text, _card(
        title,
        "It is on your calendar." if kicker != "Cancelled" else "It is off your calendar.",
        home or None,
        "Open luach",
        "You get these because notifications are on in Settings › Meetings.",
        kicker=kicker,
        title=title,
        panel=_details([("Who", guest), ("When", when), ("Where", where)]),
    )


def booking_confirmed(
    host: str,
    when: str,
    tz: str,
    location: str,
    manage: str = "",
    *,
    host_when: str = "",
    invited: bool = True,
) -> tuple[str, str]:
    """`host_when` is the same moment in the host's hours, when theirs differ."""
    where = f"\nWhere: {location}" if location else ""
    theirs = f"\nFor {host}: {host_when}" if host_when else ""
    change = (
        f"\n\nNeed a different time, or cannot make it? Move or cancel it here:\n{manage}"
        if manage
        else "\n\nNeed a different time? Just reply to this message."
    )
    invitation = (
        "A calendar invitation is on its way — accept it and it lands in your own calendar."
        if invited
        else "Add it to your own calendar: the invitation could not be sent this time."
    )
    text = (
        f"Your meeting with {host} is confirmed.\n\n"
        f"When: {when} ({tz}){theirs}{where}\n\n{invitation}{change}"
    )
    body = f"Your meeting with <b>{_e(host)}</b> is booked. {_e(invitation)}" + (
        "" if manage else "<br><br>Need a different time? Just reply to this message."
    )
    return text, _card(
        f"{when} with {host}",
        body,
        manage or None,
        "Move or cancel this meeting",
        kicker="Confirmed",
        title=f"You're meeting {host}",
        panel=_details(
            [("When", when), ("Time zone", tz), (f"For {host}", host_when), ("Where", location)]
        ),
    )


def booking_moved(host: str, when: str, tz: str, manage: str = "") -> tuple[str, str]:
    """The visitor moved it themselves; this is their record of the new time."""
    text = (
        f"Your meeting with {host} is now {when} ({tz}). The invitation in your calendar "
        "has been updated." + (f"\n\nMove or cancel it here:\n{manage}" if manage else "")
    )
    body = (
        f"Your meeting with <b>{_e(host)}</b> has a new time. The invitation in your "
        "calendar has been updated."
    )
    return text, _card(
        f"Moved: {when} with {host}",
        body,
        manage or None,
        "Move or cancel this meeting",
        kicker="Moved",
        title=f"Your meeting with {host} has moved",
        panel=_details([("Now", when), ("Time zone", tz)]),
    )


def verification(who: str, link: str, kind: str, hours: int = 48) -> tuple[str, str]:
    """Confirming an address. `kind` says what it will be used for."""
    what = (
        "sign in to luach and receive mail as you"
        if kind == "alias"
        else "receive an invitation to every event you add"
    )
    text = (
        f"{who or 'Someone'} added this address to their luach account so it can {what}.\n\n"
        f"Confirm it here (the link works for {_hours(hours)}):\n{link}\n\n"
        "If this was not you, ignore this message — the address does nothing until "
        "the link is followed."
    )
    body = (
        f"<b>{_e(who or 'Someone')}</b> added this address to their luach account so it can "
        f"{_e(what)}.<br><br>If this was not you, ignore this message — the address does "
        "nothing until the link is followed."
    )
    return text, _card(
        "Confirm your address",
        body,
        link,
        "Confirm this address",
        kicker="One step",
        title="Confirm this address",
        panel=_details([("Added by", who or "Someone"), ("Link works", _hours(hours))]),
    )


def booking_cancelled(
    host: str, when: str, tz: str, *, by_guest: bool = False, book: str = ""
) -> tuple[str, str]:
    """Called off, by the visitor (`by_guest`) or by the member. `book` is the
    booking page, offered when it was the member who cancelled."""
    if by_guest:
        said = f"Your meeting with {host} on {when} ({tz}) is cancelled. Nothing else is needed."
        body = f"Your meeting with <b>{_e(host)}</b> is cancelled. Nothing else is needed."
        book = ""
    else:
        said = (
            f"Your meeting with {host} on {when} ({tz}) has been cancelled.\n\n"
            "Nothing else is needed. If you still want to meet, book another time"
            + (f" here:\n{book}" if book else ".")
        )
        body = f"<b>{_e(host)}</b> had to cancel. Nothing else is needed." + (
            " If you still want to meet, book another time." if book else ""
        )
    return said, _card(
        f"Cancelled: {when} with {host}",
        body,
        book or None,
        "Book another time",
        kicker="Cancelled",
        title=f"Your meeting with {host} is off",
        panel=_details([("Was", when), ("Time zone", tz)]),
    )

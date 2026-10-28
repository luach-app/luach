"""The public About and Privacy pages, filled in for whoever runs this luach.

They are static pages (web/public/about/index.html, web/public/privacy/index.html)
with ``{{placeholders}}`` where the household, the person who runs it and how to
reach them belong. The server fills them each time it serves one, from
``LUACH_HOUSEHOLD_NAME``, ``LUACH_OPERATOR_NAME``, ``LUACH_CONTACT_EMAIL``,
``LUACH_APP_URL`` and the model menu (``model_menu.privacy_paragraph``: each model
members can be answered by and who runs it, so the page cannot go stale), which
``LUACH_PRIVACY_MODELS`` overrides. Every inserted value is escaped. Unset, each
one falls back to wording that names nobody.
"""

from __future__ import annotations

import hashlib
import html
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

from luach import config, model_menu

#: The pages under the static directory that are filled in rather than sent as they are.
PAGES = ("about", "privacy")

#: Said of the operator where LUACH_OPERATOR_NAME is unset.
SOMEONE = "the person who runs this luach"

#: The privacy page's paragraph on the AI model, where neither LUACH_PRIVACY_MODELS nor
#: the menu says more.
DEFAULT_MODELS = (
    "To answer you, the assistant sends your message — and any email text it read to "
    "answer it — to an AI model: the one this luach is set up with, or another from the "
    "list in Settings if you choose one. A model may run on the household's own computer, "
    "and then nothing leaves the house, or at a cloud provider; then that text is sent to "
    "that provider to produce the answer, under their API terms, and not kept by luach "
    "anywhere else."
)

logger = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def page_for(static: Path, candidate: Path) -> bool:
    """Whether ``candidate`` is one of the pages this module fills in."""
    resolved = candidate.resolve()
    return any(resolved == (static / name / "index.html").resolve() for name in PAGES)


def _e(text: str) -> str:
    """Escaped for text and for the pages' double-quoted attributes. An apostrophe
    stays one ("the Rivera family's"), as it was written in the pages."""
    return html.escape(text, quote=False).replace('"', "&quot;")


def _mailto(address: str) -> str:
    return f'<a href="mailto:{_e(address)}">{_e(address)}</a>'


def values() -> dict[str, str]:
    """Every placeholder's HTML, read from the settings now."""
    name = config.household_name()
    operator = config.operator_name()
    email = config.contact_email()
    host = urlparse(config.app_url()).hostname or ""
    calendar = config.household_calendar()
    who = _e(operator) if operator else SOMEONE
    if operator:
        runs = f"This luach is run by {_e(operator)} for their household"
    else:
        runs = "This luach is run for one household"
    return {
        "household_calendar": _e(calendar),
        "household_title": _e(calendar[:1].upper() + calendar[1:]),
        "household_described": _e(
            f"the {name} family's private household calendar"
            if name
            else "a private household calendar"
        ),
        "who_runs_it": runs + (f" at {_e(host)}" if host else ""),
        "site": f" · {_e(host)}" if host else "",
        "operator": who + (f" ({_mailto(email)})" if email else ""),
        "contact_footer": f" · Contact: {_mailto(email)}" if email else "",
        "delete_account": f"email {_mailto(email)}" if email else f"ask {who}",
        "contact": _mailto(email) if email else f"ask {who}",
        "models": _e(config.privacy_models() or _menu_paragraph() or DEFAULT_MODELS),
    }


def _menu_paragraph() -> str:
    """The menu's own account of itself; "" when the store cannot be read, so the
    public page still serves."""
    try:
        return model_menu.privacy_paragraph()
    except Exception:
        logger.exception("could not read the model menu for the privacy page")
        return ""


def render(template: str) -> str:
    """The page with its placeholders filled in. One this module does not know is
    left as it is, so a typo shows on the page rather than vanishing."""
    filled = values()
    return _PLACEHOLDER.sub(lambda m: filled.get(m.group(1), m.group(0)), template)


def etag(body: str) -> str:
    return '"' + hashlib.sha256(body.encode()).hexdigest()[:32] + '"'

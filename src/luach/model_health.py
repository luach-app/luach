"""Whether each model on the menu is answering, and what happens when one stops.

A provider retired the model a menu entry pointed at, and that choice failed on
every turn for days with nothing noticing. Now a model the provider refuses
(400/404, "not found", "no endpoint") is marked not answering at once; one that
fails ``MAX_FAILURES`` turns in a row, for any reason, is marked too. Either way
the owner is told (push, and mail when luach can send it), the members who had
picked it go back to the household's model and are told on their next turn
(model_menu.note_for), and the menu shows it as not answering. A later answer,
a "Check" from the owner or a "Try it" run that gets answers clears it.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import or_, update

from luach import config, db, model_menu

logger = logging.getLogger(__name__)

#: Failed turns in a row that mark a model not answering, whatever the failure.
MAX_FAILURES = 3

#: How a provider says it does not serve a model any more (or never did).
_REFUSAL = re.compile(
    r"not.?found|no endpoints?|does not exist|doesn't exist|invalid model|unknown model|"
    r"model.{0,40}(not (available|supported)|deprecated|retired|decommissioned)|"
    r"no such model|is not a valid model|no deployments? configured",
    re.I,
)
#: What could be a credential in a provider's words.
_SECRETISH = re.compile(
    r"(sk|pk|rk|key|token|bearer)[-_ :=]*[A-Za-z0-9_\-]{12,}|[A-Za-z0-9_\-]{32,}", re.I
)
_URL_CREDENTIALS = re.compile(r"//[^/@\s]+@")


def status_of(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def refused(exc: BaseException) -> bool:
    """A provider turning the model down, as against being slow or busy."""
    status = status_of(exc)
    if status == 404:
        return True
    return status == 400 and bool(_REFUSAL.search(_message(exc)))


def _message(exc: BaseException) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        inner = body.get("error", body)
        if isinstance(inner, dict) and inner.get("message"):
            return str(inner["message"])
        if isinstance(inner, str):
            return inner
    return str(getattr(exc, "message", "") or exc)


def redact(text: str) -> str:
    """A provider's words with anything that could be a key taken out."""
    key = config.model_api_key()
    if key and len(key) >= 6:
        text = text.replace(key, "[key]")
    text = _URL_CREDENTIALS.sub("//", text)
    return _SECRETISH.sub("[hidden]", text)


def reason_for(exc: BaseException) -> str:
    """Why a model failed, in a line the owner can read: the status and the
    provider's own words, cut short, never a key."""
    status = status_of(exc)
    words = redact(" ".join(_message(exc).split()))[:160]
    if status:
        return f"{status}: {words}" if words else str(status)
    return f"{type(exc).__name__}: {words}"[:180]


def failed(model_id: str, exc: BaseException, *, user_id: int | None = None) -> bool:
    """A turn on ``model_id`` failed. Returns whether this marked it not answering."""
    if not model_id:
        return False
    if refused(exc):
        return mark_unhealthy(model_id, "its provider refused it — " + reason_for(exc), user_id)
    with db.session() as s:
        row = s.get(db.MenuModel, model_id)
        if row is None:
            return False
        row.failures = (row.failures or 0) + 1
        count = row.failures
        already = row.unhealthy_since is not None
    if count >= MAX_FAILURES and not already:
        return mark_unhealthy(
            model_id, f"{count} turns in a row failed — the last: {reason_for(exc)}", user_id
        )
    return False


def answered(model_id: str) -> None:
    """A turn on ``model_id`` got an answer: it is answering. Writes only when that
    is news, so an ordinary turn costs one indexed update that changes nothing."""
    if not model_id:
        return
    with db.session() as s:
        cleared = s.execute(
            update(db.MenuModel)
            .where(
                db.MenuModel.id == model_id,
                or_(db.MenuModel.failures > 0, db.MenuModel.unhealthy_since.is_not(None)),
            )
            .values(failures=0, unhealthy_since=None, unhealthy_reason="", last_ok_at=db.utcnow())
            .returning(db.MenuModel.id)
        ).first()
    if cleared:
        logger.info("model %s is answering again", model_id)


def mark_unhealthy(model_id: str, reason: str, by_user: int | None = None) -> bool:
    """Not answering, from now. The first time: the owner is told and the members
    on it move back to the household's model. Returns whether it was news."""
    with db.session() as s:
        row = s.get(db.MenuModel, model_id)
        if row is None:
            return False
        if row.unhealthy_since is not None:
            row.unhealthy_reason = reason
            return False
        row.unhealthy_since = db.utcnow()
        row.unhealthy_reason = reason
        name = row.name or model_id
    logger.warning("model %s is not answering: %s", model_id, reason)
    from luach.agent.control import trail

    trail().record("model.not_answering", {"model": model_id, "reason": reason[:300]})
    is_default = model_id == model_menu.default_id()
    moved = [] if is_default else model_menu.move_members_off(model_id, "not answering")
    # The member whose own turn found it out is told by that turn's answer.
    if by_user in moved:
        model_menu.clear_note(by_user)
    tell_owner(name, reason, is_default=is_default, moved=len(moved))
    return True


def tell_owner(name: str, reason: str, *, is_default: bool, moved: int) -> None:
    """The owner hears about a model that stopped answering: push, and mail."""
    from luach import mailer, push
    from luach.auth import users

    owner = db.owner_id()
    if owner is None:
        return
    if is_default:
        then = "It is the household's model, so luach cannot answer anyone until it is fixed or another is the default."
    elif moved:
        then = f"{moved} member{'s' if moved != 1 else ''} who picked it are back on the household's model."
    else:
        then = "Nobody had picked it."
    body = f"{name} is not answering ({reason}). {then} Settings › Household › Models."
    try:
        push.notify_user(owner, "A model stopped answering", body, "/?tab=settings")
    except Exception:
        logger.exception("could not push the model warning")
    member = users.member(owner)
    if member is not None and mailer.configured():
        mailer.send(member.email, f"luach: {name} is not answering", body)


async def probe(model_id: str) -> tuple[bool, str]:
    """One tiny request to ``model_id``: (answering, why not). Costs a few tokens.

    Only the configured endpoint is asked, with its own key, and only for an id
    that passes the menu's check: nothing here takes a URL from a request.
    """
    import httpx

    base = config.model_base_url()
    if not base:
        return False, "no model server is set up (OPENAI_BASE_URL)"
    if not model_menu.valid_id(model_id):
        return False, "not a model id"
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": [{"role": "user", "content": "Reply with the word ok."}],
        "max_tokens": 16,
        "temperature": 0,
    }
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            r = await client.post(
                f"{base}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {config.model_api_key()}"},
            )
    except httpx.HTTPError as exc:
        return False, f"could not reach the model server ({type(exc).__name__})"
    if r.status_code == 200:
        return True, ""
    try:
        detail = r.json()
    except ValueError:
        detail = r.text
    words = detail.get("error", detail) if isinstance(detail, dict) else detail
    if isinstance(words, dict):
        words = words.get("message", "")
    return False, f"{r.status_code}: {redact(' '.join(str(words).split()))[:160]}"


async def check(model_id: str) -> dict[str, Any]:
    """The owner's "Check": a probe, and the menu brought up to date with it."""
    ok, why = await probe(model_id)
    if ok:
        answered(model_id)
    elif why.startswith(("400", "404")) or "not found" in why.lower():
        mark_unhealthy(model_id, "its provider refused it — " + why)
    found = model_menu.get(model_id)
    return {"ok": ok, "reason": why, "health": found.health() if found else None}


async def recheck_unhealthy() -> int:
    """Probe every model that is marked not answering; returns how many recovered."""
    recovered = 0
    for choice in model_menu.everything():
        if choice.healthy:
            continue
        ok, _ = await probe(choice.id)
        if ok:
            answered(choice.id)
            recovered += 1
    return recovered

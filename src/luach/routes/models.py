"""The models a member may choose from, and the owner's management of them.

Members read the menu (GET /api/models): the enabled models, the household's
default first, each with whether it is answering. Their choice is saved on the
member (PATCH /api/auth/me ``{"model": …}``), so it follows them from the phone to
the kitchen screen and to the email door.

The owner manages the menu under /api/models/manage: add from the catalogue (or
by id), edit, remove, reorder, enable, set the default, "Try it", "Check". Only
the owner, signed in as themselves: a member is refused, and so are both service
keys (the agent platform's at the wall, the trusted service's here) — which
models the family's questions are sent to is a person's decision.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Request

from luach import model_catalogue, model_health, model_menu, model_trials
from luach.agent.control import trail
from luach.auth import users
from luach.routes.shared import body, error, require_caller, require_member, require_owner

router = APIRouter()


@router.get("/api/models")
def models() -> dict:
    """The menu, the default, and the member's own choice ("" for the default)."""
    member = require_member()
    menu = model_menu.choices()
    return {
        "models": [c.id for c in menu],
        "default": model_menu.default_id(),
        "configured": model_menu.ready(),
        "catalogue": [c.as_dict() for c in menu],
        "chosen": model_menu.pick(member.model),
    }


def require_owner_in_person() -> users.Member:
    """The owner, signed in: not a member, not a key acting for the owner."""
    if require_caller().via_key:
        raise error(403, "the model menu is changed by the owner, signed in")
    return require_owner()


def _snapshot() -> dict[str, Any]:
    scores = model_trials.scores()
    default = model_menu.default_id()
    src = model_catalogue.source()
    return {
        "default": default,
        "configured": model_menu.ready(),
        "models": [
            {**c.as_owner_dict(), "is_default": c.id == default, "trial": scores.get(c.id)}
            for c in model_menu.everything()
        ],
        "trial": model_trials.latest(),
        "trials_left_today": model_trials.left_today(),
        "catalogue": {"configured": src is not None, "source": src.host if src else ""},
    }


def _bool(data: dict[str, Any], key: str) -> bool | None:
    if key not in data:
        return None
    if not isinstance(data[key], bool):
        raise error(400, f"{key} must be true or false")
    return bool(data[key])


def _text(data: dict[str, Any], key: str) -> str | None:
    if key not in data or data[key] is None:
        return None
    if not isinstance(data[key], str):
        raise error(400, f"{key} must be text")
    return str(data[key])


def _id(data: dict[str, Any]) -> str:
    try:
        return model_menu.check_id(data.get("id"))
    except model_menu.MenuError as exc:
        raise error(400, str(exc)) from exc


@router.get("/api/models/manage")
def manage() -> dict:
    require_owner_in_person()
    return _snapshot()


@router.post("/api/models/manage")
async def add(request: Request) -> dict:
    """Add a model to the list (not yet the members' menu) and try it."""
    owner = require_owner_in_person()
    data = await body(request)
    model_id = _id(data)
    name, about, provider = _text(data, "name"), _text(data, "about"), _text(data, "provider")
    local, wants_trial = _bool(data, "local"), _bool(data, "try")
    listed = await asyncio.to_thread(model_catalogue.lookup, model_id)
    try:
        added = model_menu.add(
            model_id,
            name=name or (listed or {}).get("name") or "",
            about=about or "",
            local=bool(local),
            provider=provider or "",
            meta=listed or {},
        )
    except model_menu.MenuError as exc:
        raise error(400, str(exc)) from exc
    trail().record("models.added", {"by": owner.username, "model": added.id})
    started = False
    note = ""
    if wants_trial is not False:
        try:
            model_trials.start(added.id, owner.username)
            started = True
        except model_trials.TrialError as exc:
            note = str(exc)
    return {**_snapshot(), "added": added.id, "trial_started": started, "note": note}


@router.patch("/api/models/manage")
async def edit(request: Request) -> dict:
    owner = require_owner_in_person()
    data = await body(request)
    model_id = _id(data)
    texts = {k: _text(data, k) for k in ("name", "about", "provider")}
    flags = {k: _bool(data, k) for k in ("enabled", "local")}
    fields: dict[str, Any] = {**texts, **flags}
    if all(v is None for v in fields.values()):
        raise error(400, "nothing to change")
    try:
        model_menu.update(
            model_id,
            name=texts["name"],
            about=texts["about"],
            provider=texts["provider"],
            enabled=flags["enabled"],
            local=flags["local"],
        )
    except model_menu.MenuError as exc:
        raise error(400, str(exc)) from exc
    changed = {k: v for k, v in fields.items() if v is not None}
    trail().record("models.changed", {"by": owner.username, "model": model_id, **changed})
    return _snapshot()


@router.post("/api/models/manage/remove")
async def remove(request: Request) -> dict:
    owner = require_owner_in_person()
    model_id = _id(await body(request))
    try:
        model_menu.remove(model_id)
    except model_menu.MenuError as exc:
        raise error(400, str(exc)) from exc
    trail().record("models.removed", {"by": owner.username, "model": model_id})
    return _snapshot()


@router.put("/api/models/manage/order")
async def reorder(request: Request) -> dict:
    owner = require_owner_in_person()
    ids = (await body(request)).get("ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise error(400, "ids must be a list of model ids")
    try:
        model_menu.reorder(ids)
    except model_menu.MenuError as exc:
        raise error(400, str(exc)) from exc
    trail().record("models.reordered", {"by": owner.username})
    return _snapshot()


@router.put("/api/models/manage/default")
async def set_default(request: Request) -> dict:
    owner = require_owner_in_person()
    model_id = _id(await body(request))
    try:
        model_menu.set_default(model_id)
    except model_menu.MenuError as exc:
        raise error(400, str(exc)) from exc
    trail().record("models.default", {"by": owner.username, "model": model_id})
    return _snapshot()


@router.get("/api/models/manage/trial")
def trial() -> dict:
    require_owner_in_person()
    return {"trial": model_trials.latest(), "trials_left_today": model_trials.left_today()}


@router.post("/api/models/manage/trial")
async def try_it(request: Request) -> dict:
    owner = require_owner_in_person()
    model_id = _id(await body(request))
    try:
        started = model_trials.start(model_id, owner.username)
    except model_menu.MenuError as exc:
        raise error(400, str(exc)) from exc
    except model_trials.TrialError as exc:
        raise error(409, str(exc)) from exc
    return {"trial": started, "trials_left_today": model_trials.left_today()}


@router.post("/api/models/manage/trial/cancel")
async def cancel_trial(request: Request) -> dict:
    require_owner_in_person()
    await body(request)
    cancelled = await model_trials.cancel()
    return {"cancelled": cancelled, "trial": model_trials.latest()}


@router.post("/api/models/manage/check")
async def check(request: Request) -> dict:
    """One tiny request to the model: is it answering? Clears or sets its health."""
    require_owner_in_person()
    model_id = _id(await body(request))
    if model_menu.get(model_id) is None:
        raise error(404, "that model is not on the list")
    return {**(await model_health.check(model_id)), "models": _snapshot()["models"]}


@router.get("/api/models/catalogue")
async def catalogue(q: str = "", fresh: bool = False) -> dict:
    """Search the models the endpoint (or LUACH_MODEL_CATALOGUE_URL) lists."""
    require_owner_in_person()
    src = model_catalogue.source()
    if src is None:
        return {"configured": False, "source": "", "models": [], "error": ""}
    try:
        if fresh:
            await asyncio.to_thread(model_catalogue.models, fresh=True)
        found = await asyncio.to_thread(model_catalogue.search, q[:100])
    except model_catalogue.CatalogueError as exc:
        return {"configured": True, "source": src.host, "models": [], "error": str(exc)}
    return {"configured": True, "source": src.host, "models": found, "error": ""}

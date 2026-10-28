"""The models a member may choose from: a short list the owner keeps in the app.

A household does not choose between the hundreds of models a server can reach;
it chooses between a few the owner added, tried ("Try it", luach.model_trials)
and put on the menu. The menu is the ``menu_models`` table, managed through the
owner's routes (routes/models.py). ``LUACH_MODELS`` (JSON
``[{"id", "name", "about", "local"}]``) only seeds it, once, when it is empty, so a
deployment that had a menu in its settings keeps it on its first start.

The household's default is a setting too: the owner's choice in the app
(``settings`` row ``models.default``) and, until they make one, ``LUACH_MODEL``.
``default_id`` is the one place that says which model answers a turn nobody
chose a model for. A model the menu does not name is never used: a request's
choice and a member's saved one both go through ``pick``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from luach import config, db

logger = logging.getLogger(__name__)

#: A model id as a model server names one: "qwen3.6-35b", "openrouter/google/gemini-3.8-flash",
#: "~deepseek/deepseek-flash-latest". No colon (tulip reads "provider:model", so a colon
#: would choose a provider), no spaces, nothing that is not plausibly a name.
MODEL_ID = re.compile(r"^[A-Za-z0-9~][A-Za-z0-9._~/@+-]{0,127}$")
MAX_MODELS = 30
MAX_NAME = 60
MAX_ABOUT = 300
MAX_PROVIDER = 80

KEY_DEFAULT = "models.default"
KEY_SEEDED = "models.seeded"
#: A member moved back to the default, waiting to be told on their next turn.
KEY_MOVED = "models.moved:{user_id}"

DEFAULT_ABOUT = "The household's default."


def valid_id(model_id: str) -> bool:
    return bool(MODEL_ID.fullmatch(model_id or "")) and "//" not in model_id


@dataclass(frozen=True)
class Choice:
    id: str
    name: str
    about: str
    local: bool = False
    provider: str = ""
    enabled: bool = True
    position: int = 0
    meta: dict[str, Any] = field(default_factory=dict)
    unhealthy_since: datetime | None = None
    unhealthy_reason: str = ""
    failures: int = 0
    last_ok_at: datetime | None = None
    #: Whether it has a row of its own (a default set only by LUACH_MODEL may not).
    stored: bool = True

    @property
    def healthy(self) -> bool:
        return self.unhealthy_since is None

    def health(self) -> dict[str, Any]:
        if self.healthy:
            return {"status": "ok", "since": None, "reason": ""}
        return {
            "status": "not_answering",
            "since": db.iso(self.unhealthy_since),
            "reason": self.unhealthy_reason,
        }

    def as_dict(self) -> dict[str, Any]:
        """What a member sees of it."""
        return {
            "id": self.id,
            "name": self.name,
            "about": self.about,
            "local": self.local,
            "provider": provider_label(self),
            "health": self.health(),
        }

    def as_owner_dict(self) -> dict[str, Any]:
        """What the owner manages."""
        return {
            **self.as_dict(),
            "provider_set": self.provider,
            "enabled": self.enabled,
            "position": self.position,
            "meta": self.meta,
            "failures": self.failures,
            "last_ok_at": db.iso(self.last_ok_at),
        }


def _choice(row: db.MenuModel) -> Choice:
    return Choice(
        id=row.id,
        name=row.name or row.id,
        about=row.about or "",
        local=bool(row.local),
        provider=row.provider or "",
        enabled=bool(row.enabled),
        position=row.position,
        meta=db.loads(row.meta_json, {}) or {},
        unhealthy_since=row.unhealthy_since,
        unhealthy_reason=row.unhealthy_reason or "",
        failures=row.failures or 0,
        last_ok_at=row.last_ok_at,
    )


# --- the seed ---------------------------------------------------------------


def from_env() -> list[dict[str, Any]]:
    """The entries ``LUACH_MODELS`` lists, in its order; [] when unset or unreadable.

    A setting that is not a JSON list of objects with a valid id is ignored as a
    whole, with a warning, rather than half-read: a menu missing the entry its
    operator meant to add is worse than the default alone, which they will notice.
    """
    raw = config.models()
    if not raw:
        return []
    try:
        items = json.loads(raw)
        if not isinstance(items, list):
            raise ValueError("not a list")
        menu = []
        for item in items:
            model = str(item["id"]).strip()
            if not valid_id(model):
                raise ValueError(f"{model!r} is not a model id")
            menu.append(
                {
                    "id": model,
                    "name": " ".join(str(item.get("name") or model).split())[:MAX_NAME],
                    "about": " ".join(str(item.get("about") or "").split())[:MAX_ABOUT],
                    "local": item.get("local") is True,
                }
            )
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning(
            "LUACH_MODELS is not a JSON list of {id, name, about, local}; ignored (%s)", exc
        )
        return []
    return menu


def _setting(key: str) -> Any:
    with db.session() as s:
        row = s.get(db.Setting, key)
        return db.loads(row.value) if row is not None else None


def _put_setting(key: str, value: Any) -> None:
    with db.session() as s:
        s.execute(
            insert(db.Setting)
            .values(key=key, value=db.dumps(value), enabled=True)
            .on_conflict_do_update(index_elements=["key"], set_={"value": db.dumps(value)})
        )


def seed() -> int:
    """Fill an empty menu from LUACH_MODELS and LUACH_MODEL, once; then keep the
    deployment's default on the menu while the owner has not chosen one. Returns
    how many models were added. Safe to run from two copies at once."""
    added = 0
    with db.session() as s:
        empty = s.execute(select(func.count()).select_from(db.MenuModel)).scalar_one() == 0
        seeded = s.get(db.Setting, KEY_SEEDED) is not None
    if empty and not seeded:
        entries = from_env()
        env_default = config.model_id()
        if env_default and valid_id(env_default) and env_default not in {e["id"] for e in entries}:
            entries.insert(0, {"id": env_default, "name": env_default, "about": DEFAULT_ABOUT})
        for n, entry in enumerate(entries[:MAX_MODELS]):
            added += _insert(entry, position=n, enabled=True)
        if added:
            _put_setting(KEY_SEEDED, db.iso(db.utcnow()))
            logger.info("model menu: %d models from LUACH_MODELS/LUACH_MODEL", added)
    default = default_id()
    if default and valid_id(default) and _row(default) is None:
        added += _insert(
            {"id": default, "name": default, "about": DEFAULT_ABOUT},
            position=-1,
            enabled=True,
        )
    return added


def _insert(entry: dict[str, Any], *, position: int, enabled: bool) -> int:
    with db.session() as s:
        result = s.execute(
            insert(db.MenuModel)
            .values(
                id=entry["id"],
                name=entry.get("name") or entry["id"],
                about=entry.get("about") or "",
                position=position,
                enabled=enabled,
                local=bool(entry.get("local")),
                provider=entry.get("provider") or "",
                meta_json=db.dumps(entry.get("meta") or {}),
                added_at=db.utcnow(),
                failures=0,
                unhealthy_reason="",
            )
            .on_conflict_do_nothing(index_elements=["id"])
            .returning(db.MenuModel.id)
        ).first()
        return 1 if result is not None else 0


# --- reading it -------------------------------------------------------------


def _row(model_id: str) -> Choice | None:
    with db.session() as s:
        row = s.get(db.MenuModel, model_id)
        return _choice(row) if row is not None else None


def get(model_id: str) -> Choice | None:
    return _row(model_id)


def everything() -> list[Choice]:
    """Every model on the list, enabled or not, in the owner's order."""
    with db.session() as s:
        rows = s.execute(
            select(db.MenuModel).order_by(db.MenuModel.position, db.MenuModel.added_at)
        ).scalars()
        return [_choice(r) for r in rows]


def default_id() -> str:
    """The household's model: the owner's choice in the app, else LUACH_MODEL, else ""."""
    stored = _setting(KEY_DEFAULT)
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    return config.model_id()


def ready() -> bool:
    """Whether a model can answer at all: an endpoint and a default to ask."""
    return bool(config.model_base_url() and default_id())


def choices() -> list[Choice]:
    """The members' menu: the default first, then every enabled model in the owner's
    order. A default with no row (LUACH_MODEL moved by an operator) is still offered."""
    default = default_id()
    menu = [c for c in everything() if c.enabled]
    if not default:
        return menu
    first = next((c for c in menu if c.id == default), None)
    if first is None:
        stored = _row(default)
        first = stored or Choice(default, default, DEFAULT_ABOUT, stored=False)
    else:
        menu.remove(first)
    return [first, *menu]


def name_of(model_id: str) -> str:
    found = _row(model_id)
    return found.name if found else model_id


def allowed(name: str) -> bool:
    """On the members' menu and answering. The default is always allowed: it is
    what everyone falls back to."""
    if not name:
        return False
    if name == default_id():
        return True
    return any(c.id == name and c.healthy for c in choices())


def pick(*names: str) -> str:
    """The first name that is on the menu, or "" for the household default.

    A request's own choice, then the member's saved one: a name that is not on
    the menu is passed over rather than sent to the model server, because the
    server would answer to any model in its catalogue.
    """
    default = default_id()
    for name in names:
        name = (name or "").strip()
        if name and allowed(name):
            return "" if name == default else name
    return ""


# --- the owner's changes ------------------------------------------------------


class MenuError(ValueError):
    """A change the menu refuses, said so a person can act on it."""


def _clean_text(value: Any, what: str, limit: int, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise MenuError(f"{what} must be text")
    text = " ".join(value.split())
    if required and not text:
        raise MenuError(f"{what} is required")
    if len(text) > limit:
        raise MenuError(f"{what} is at most {limit} characters")
    return text


def check_id(model_id: Any) -> str:
    if not isinstance(model_id, str) or not valid_id(model_id.strip()):
        raise MenuError(
            "that is not a model id: up to 128 letters, digits and . _ ~ / @ + -, "
            "no spaces or colons"
        )
    return model_id.strip()


def add(
    model_id: str,
    *,
    name: str = "",
    about: str = "",
    local: bool = False,
    provider: str = "",
    meta: dict[str, Any] | None = None,
) -> Choice:
    """A model on the list, not yet on the members' menu: the owner enables it."""
    model_id = check_id(model_id)
    name = _clean_text(name, "name", MAX_NAME) or model_id[:MAX_NAME]
    about = _clean_text(about, "about", MAX_ABOUT)
    provider = _clean_text(provider, "provider", MAX_PROVIDER)
    if _row(model_id) is not None:
        raise MenuError("that model is already on the list")
    if len(everything()) >= MAX_MODELS:
        raise MenuError(f"the list holds at most {MAX_MODELS} models; remove one first")
    with db.session() as s:
        last = s.execute(select(func.max(db.MenuModel.position))).scalar_one_or_none()
    _insert(
        {
            "id": model_id,
            "name": name,
            "about": about,
            "local": bool(local),
            "provider": provider,
            "meta": clean_meta(meta or {}),
        },
        position=(last if last is not None else -1) + 1,
        enabled=False,
    )
    found = _row(model_id)
    assert found is not None
    return found


def clean_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """Only what the catalogue's numbers mean, as numbers: nothing else is kept."""
    out: dict[str, Any] = {}
    for key in ("context_length", "price_in", "price_out"):
        value = meta.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool) and 0 <= value < 1e9:
            out[key] = value
    if isinstance(meta.get("tools"), bool):
        out["tools"] = meta["tools"]
    return out


def update(
    model_id: str,
    *,
    name: str | None = None,
    about: str | None = None,
    enabled: bool | None = None,
    local: bool | None = None,
    provider: str | None = None,
) -> Choice:
    model_id = check_id(model_id)
    if _row(model_id) is None:
        raise MenuError("that model is not on the list")
    if enabled is False and model_id == default_id():
        raise MenuError("that is the household's default: choose another default first")
    clean: dict[str, Any] = {}
    if name is not None:
        clean["name"] = _clean_text(name, "name", MAX_NAME, required=True)
    if about is not None:
        clean["about"] = _clean_text(about, "about", MAX_ABOUT)
    if provider is not None:
        clean["provider"] = _clean_text(provider, "provider", MAX_PROVIDER)
    if local is not None:
        clean["local"] = bool(local)
    if enabled is not None:
        clean["enabled"] = bool(enabled)
    with db.session() as s:
        row = s.get(db.MenuModel, model_id)
        assert row is not None
        for key, value in clean.items():
            setattr(row, key, value)
    if enabled is False:
        move_members_off(model_id, "taken off the menu")
    found = _row(model_id)
    assert found is not None
    return found


def remove(model_id: str) -> None:
    model_id = check_id(model_id)
    if model_id == default_id():
        raise MenuError("that is the household's default: choose another default first")
    if _row(model_id) is None:
        raise MenuError("that model is not on the list")
    # Told first, while the name is still known.
    move_members_off(model_id, "taken off the menu")
    with db.session() as s:
        row = s.get(db.MenuModel, model_id)
        if row is not None:
            s.delete(row)


def reorder(ids: list[str]) -> list[Choice]:
    """The owner's order: every id on the list, each once."""
    current = [c.id for c in everything()]
    if sorted(ids) != sorted(current) or len(set(ids)) != len(ids):
        raise MenuError("send every model on the list, each once, in the new order")
    with db.session() as s:
        for n, model_id in enumerate(ids):
            row = s.get(db.MenuModel, model_id)
            assert row is not None
            row.position = n
    return everything()


def set_default(model_id: str) -> str:
    model_id = check_id(model_id)
    found = _row(model_id)
    if found is None:
        raise MenuError("that model is not on the list")
    if not found.healthy:
        raise MenuError("that model is not answering: check it, or choose another")
    with db.session() as s:
        row = s.get(db.MenuModel, model_id)
        assert row is not None
        row.enabled = True
    _put_setting(KEY_DEFAULT, model_id)
    # A member whose pick is now the default follows the default, as if they had chosen it.
    with db.session() as s:
        for user in s.execute(select(db.User).where(db.User.model == model_id)).scalars():
            user.model = ""
    return model_id


# --- members moved back to the default ------------------------------------------


def move_members_off(model_id: str, why: str) -> list[int]:
    """Every member who picked ``model_id`` goes back to the household's model, and
    is told on their next turn (``note_for``): no silent switch."""
    name = name_of(model_id)
    moved: list[int] = []
    with db.session() as s:
        users = s.execute(select(db.User).where(db.User.model == model_id)).scalars().all()
        for user in users:
            user.model = ""
            moved.append(user.id)
    for user_id in moved:
        _put_setting(
            KEY_MOVED.format(user_id=user_id), {"from": model_id, "name": name, "why": why}
        )
    if moved:
        logger.info("model menu: %d members moved off %s (%s)", len(moved), model_id, why)
    return moved


def note_for(user_id: int | None) -> str:
    """The sentence a moved member's next answer starts with, or ""."""
    if user_id is None:
        return ""
    moved = _setting(KEY_MOVED.format(user_id=user_id))
    if not isinstance(moved, dict):
        return ""
    default = default_id()
    house = name_of(default) if default else "the household's model"
    return (
        f"(A note first: {moved.get('name') or moved.get('from')}, the model you picked, was "
        f"{moved.get('why') or 'taken off the menu'}, so {house}, the household's model, is "
        "answering you now. You can choose another in Settings.)"
    )


def clear_note(user_id: int | None) -> None:
    if user_id is None:
        return
    with db.session() as s:
        row = s.get(db.Setting, KEY_MOVED.format(user_id=user_id))
        if row is not None:
            s.delete(row)


# --- who answers, as the privacy page says it -------------------------------------

#: The first part of an id, as the company behind it is called.
ORGS = {
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "deepseek": "DeepSeek",
    "meta-llama": "Meta",
    "mistralai": "Mistral AI",
    "qwen": "Alibaba (Qwen)",
    "x-ai": "xAI",
    "moonshotai": "Moonshot AI",
    "z-ai": "Z.ai",
    "cohere": "Cohere",
    "nvidia": "NVIDIA",
    "microsoft": "Microsoft",
    "amazon": "Amazon",
    "perplexity": "Perplexity",
    "minimax": "MiniMax",
}
#: Services that pass a request on to the company that makes the model.
GATEWAYS = {
    "openrouter": "OpenRouter",
    "together": "Together AI",
    "together_ai": "Together AI",
    "groq": "Groq",
    "fireworks": "Fireworks AI",
    "fireworks_ai": "Fireworks AI",
    "deepinfra": "DeepInfra",
    "bedrock": "Amazon Bedrock",
    "vertex_ai": "Google Vertex AI",
    "azure": "Microsoft Azure",
}


def _org(part: str) -> str:
    part = part.lstrip("~").lower()
    return ORGS.get(part) or GATEWAYS.get(part) or part.replace("-", " ").replace("_", " ").title()


def provider_label(choice: Choice) -> str:
    """Who answers a model: "" for one at home, the owner's words when they gave
    some, else worked out from the id ("openrouter/google/…" is "Google, through
    OpenRouter"; "google/…" asked through OpenRouter's own endpoint is the same)."""
    if choice.local:
        return ""
    if choice.provider:
        return choice.provider
    parts = [p for p in choice.id.split("/") if p]
    if len(parts) >= 3 and parts[0].lower() in GATEWAYS:
        return f"{_org(parts[1])}, through {GATEWAYS[parts[0].lower()]}"
    if len(parts) >= 2:
        if parts[0].lower() in GATEWAYS:
            return GATEWAYS[parts[0].lower()]
        if "openrouter.ai" in config.model_base_url():
            return f"{_org(parts[0])}, through OpenRouter"
        return _org(parts[0])
    return ""


def privacy_paragraph() -> str:
    """The privacy page's paragraph on the models, from the menu as it is now: each
    model a member can be answered by, and where what they ask goes. "" when there
    is no menu to describe (the page then says it in general terms)."""
    menu = choices() if ready() else []
    if not menu:
        return ""
    parts = []
    for c in menu:
        if c.local:
            parts.append(
                f"{c.name}, which runs on the household's own computer, so nothing leaves the house"
            )
        else:
            who = provider_label(c)
            parts.append(f"{c.name}, at {who}" if who else f"{c.name}, at a cloud provider")
    lead = (
        "To answer you, the assistant sends your message — and any email text it read to "
        "answer it — to an AI model: the household's own, or another from the list in "
        "Settings if you choose one. "
        if len(menu) > 1
        else "To answer you, the assistant sends your message — and any email text it read "
        "to answer it — to an AI model. "
    )
    tail = (
        " A model at a cloud provider is sent that text to produce the answer, under the "
        "provider's API terms; luach keeps it nowhere else."
        if any(not c.local for c in menu)
        else ""
    )
    return f"{lead}This luach uses: {'; '.join(parts)}.{tail}"

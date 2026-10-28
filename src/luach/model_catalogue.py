"""The models the owner can add: the model server's own list, searched.

By default ``GET {OPENAI_BASE_URL}/models``, the OpenAI-compatible listing every
server has. A router whose wildcard route (LiteLLM's ``openrouter/*``) lists
nothing behind it points ``LUACH_MODEL_CATALOGUE_URL`` at the real catalogue
(``https://openrouter.ai/api/v1/models``) and ``LUACH_MODEL_CATALOGUE_PREFIX``
at what the router puts before those ids (``openrouter/``).

Only those configured addresses are ever fetched — nothing in a request names a
URL — with a short timeout, no redirects, and a cap on what is read. The
endpoint's key goes only to the endpoint's own host: a catalogue elsewhere is
asked without it. The list is kept for ``TTL`` seconds.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from luach import config, model_menu

logger = logging.getLogger(__name__)

TTL = 600
TIMEOUT = 6.0
#: OpenRouter's whole catalogue is about a megabyte.
MAX_BYTES = 8_000_000
MAX_RESULTS = 60

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}


class CatalogueError(RuntimeError):
    """The list could not be read; the message is safe to show."""


@dataclass(frozen=True)
class Source:
    url: str
    prefix: str

    @property
    def host(self) -> str:
        return urlparse(self.url).hostname or ""


def source() -> Source | None:
    url = config.model_catalogue_url()
    parsed = urlparse(url)
    if not url or parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    return Source(url, config.model_catalogue_prefix())


def _same_origin(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.scheme, pa.hostname, pa.port) == (pb.scheme, pb.hostname, pb.port)


def _fetch(src: Source) -> Any:
    import httpx

    headers = {"Accept": "application/json", "User-Agent": config.user_agent()}
    base = config.model_base_url()
    # The endpoint's key, only to the endpoint's own host.
    if base and _same_origin(src.url, base):
        headers["Authorization"] = f"Bearer {config.model_api_key()}"
    try:
        with (
            httpx.Client(timeout=TIMEOUT, follow_redirects=False) as client,
            client.stream("GET", src.url, headers=headers) as r,
        ):
            if r.status_code != 200:
                raise CatalogueError(f"{src.host} answered {r.status_code}")
            chunks: list[bytes] = []
            size = 0
            for chunk in r.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise CatalogueError(f"{src.host} sent a list too large to read")
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise CatalogueError(f"could not reach {src.host} ({type(exc).__name__})") from exc
    import json

    try:
        return json.loads(b"".join(chunks))
    except ValueError as exc:
        raise CatalogueError(f"{src.host} did not send a list of models") from exc


def _per_million(value: Any) -> float | None:
    """OpenRouter prices a token in dollars, as text; a person reads per million."""
    try:
        price = float(value)
    except (TypeError, ValueError):
        return None
    if price < 0:
        return None
    return round(price * 1_000_000, 4)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def is_alias(model_id: str) -> bool:
    """A name that moves with the provider's newest version: OpenRouter's ``~…``
    ids and ``…-latest``. Recommended: a retired version cannot strand them."""
    bare = model_id.rsplit("/", 1)[-1]
    return model_id.startswith("~") or "/~" in model_id or bare.endswith("latest")


def parse(raw: Any, prefix: str = "") -> list[dict[str, Any]]:
    """An OpenAI-style ``{"data": [...]}`` (or a bare list) as luach's entries."""
    items = raw.get("data") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise CatalogueError("the catalogue did not send a list of models")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            continue
        model_id = prefix + item["id"].strip()
        # A wildcard route ("openrouter/*") is not a model, and an id luach would
        # refuse to send is not one to offer.
        if "*" in model_id or not model_menu.valid_id(model_id) or model_id in seen:
            continue
        # A batch variant answers in minutes to hours, for bulk jobs: no use to a family
        # waiting on a reply, so it is not offered.
        if model_id.endswith(":batch"):
            continue
        seen.add(model_id)
        pricing: dict[str, Any] = _dict(item.get("pricing"))
        top: dict[str, Any] = _dict(item.get("top_provider"))
        params = item.get("supported_parameters")
        context = item.get("context_length")
        if not isinstance(context, int):
            context = top.get("context_length")
            context = context if isinstance(context, int) else None
        raw_name = item.get("name")
        name: str = raw_name if isinstance(raw_name, str) else ""
        out.append(
            {
                "id": model_id,
                "name": " ".join(name.split())[:120] or item["id"],
                "context_length": context,
                "tools": ("tools" in params) if isinstance(params, list) else None,
                "price_in": _per_million(pricing.get("prompt")),
                "price_out": _per_million(pricing.get("completion")),
                "alias": is_alias(model_id),
                "provider": model_menu.provider_label(model_menu.Choice(model_id, "", "")),
            }
        )
    return out


def models(*, fresh: bool = False) -> list[dict[str, Any]]:
    src = source()
    if src is None:
        raise CatalogueError(
            "no catalogue is set up: set OPENAI_BASE_URL, or LUACH_MODEL_CATALOGUE_URL"
        )
    now = time.monotonic()
    key = f"{src.url}|{src.prefix}"
    cached = _cache.get(key)
    if cached and not fresh and now - cached[0] < TTL:
        return cached[1]
    listed = parse(_fetch(src), src.prefix)
    _cache[key] = (now, listed)
    return listed


def _stem(model_id: str) -> str:
    """An id with its alias marks taken off, to find the alias of a pinned version."""
    bare = model_id.replace("~", "")
    for tail in ("-latest", ":latest", "latest"):
        if bare.endswith(tail):
            return bare[: -len(tail)].rstrip("-_.")
    return bare


def search(query: str = "", *, limit: int = MAX_RESULTS) -> list[dict[str, Any]]:
    """Entries matching every word of ``query`` in their id or name: moving aliases
    first, then those that take tools, each marked with whether it is on the menu
    and, for a pinned version, the alias that would follow it."""
    listed = models()
    words = [w for w in query.lower().split() if w][:8]
    on_menu = {c.id for c in model_menu.everything()}
    aliases = [m for m in listed if m["alias"]]
    found = []
    for m in listed:
        hay = f"{m['id']} {m['name']}".lower()
        if words and not all(w in hay for w in words):
            continue
        newer = ""
        if not m["alias"]:
            stem = _stem(m["id"])
            matching = [
                a["id"] for a in aliases if _stem(a["id"]) and stem.startswith(_stem(a["id"]))
            ]
            # The closest alias: the longest name that the pinned one begins with.
            newer = max(matching, key=lambda a: len(_stem(a)), default="")
        found.append(
            {**m, "on_menu": m["id"] in on_menu, "recommended": m["alias"], "alias_of_it": newer}
        )
    found.sort(key=lambda m: (not m["alias"], m["tools"] is False, m["name"].lower()))
    return found[:limit]


def lookup(model_id: str) -> dict[str, Any] | None:
    """What the catalogue says of one id, when it is reachable and lists it."""
    try:
        return next((m for m in models() if m["id"] == model_id), None)
    except CatalogueError:
        return None


def reset() -> None:
    _cache.clear()

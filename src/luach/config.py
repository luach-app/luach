"""Configuration — environment first, systemd credentials second.

Everything is read at call time so tests can point the app at temp paths
without an import-order dance. Secrets can arrive as a plain environment
(local dev, .env via EnvironmentFile) or through systemd's
``$CREDENTIALS_DIRECTORY`` (a systemd unit, or a mounted secret):
``load_credentials()`` merges a ``secrets.env`` found there into the process
environment and resolves the Google key files that live beside it.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_TIMEZONE = "America/New_York"


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def flag(name: str, default: bool = False) -> bool:
    raw = env(name)
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def load_credentials() -> None:
    """Fold systemd credentials into the environment, once, at startup.

    ``secrets.env`` is ``KEY=value`` lines (no shell quoting); values already
    in the environment win so a developer override is never clobbered.
    """
    cred_dir = env("CREDENTIALS_DIRECTORY")
    if not cred_dir:
        return
    root = Path(cred_dir)
    secrets = root / "secrets.env"
    if secrets.is_file():
        for line in secrets.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())
    for key, filename in (
        ("LUACH_GOOGLE_SA_KEY", "google-sa.json"),
        ("LUACH_GOOGLE_OAUTH_CLIENT", "google-oauth-client.json"),
        ("LUACH_GOOGLE_OAUTH_TOKENS", "google-oauth-tokens.json"),
    ):
        candidate = root / filename
        if candidate.is_file():
            os.environ.setdefault(key, str(candidate))
    logger.info("credentials loaded from %s", root)


# --- paths ----------------------------------------------------------------


def database_url() -> str:
    """The store: Postgres, as its owner (CloudNativePG's luach-db-app ``uri`` in
    the cluster). luach-migrate brings it to head before the app starts."""
    return env("LUACH_DATABASE_URL")


def state_dir() -> Path:
    """mail.key, the agent's threads/ and the loops' lock: the data volume in the
    image (/var/lib/luach), the working directory when run by hand."""
    return Path(env("LUACH_STATE_DIR", "."))


def checkpoint_dir() -> Path:
    return Path(env("LUACH_CHECKPOINT_DIR", str(state_dir() / "threads")))


# --- conversations --------------------------------------------------------


def thread_retention_days() -> int:
    """How long a conversation is kept before it is swept up.

    A thread is working memory, not an archive — what is worth keeping about a
    person is saved deliberately by the memory tool and outlives every thread.
    Longer than a chat app's ten days because a household calendar conversation is
    often picked back up a month later ("what did we decide about the dentist");
    0 turns the sweep off.
    """
    return int(env("LUACH_THREAD_RETENTION_DAYS", "60"))


def history_turns() -> int:
    """How many of a thread's latest turns, whole, the model is sent (agent/history.py).

    Twenty is a long conversation for a household calendar, and each turn is a
    question, its tool calls and results, and the answer.
    """
    return max(1, int(env("LUACH_HISTORY_TURNS", "20")))


# --- memory ---------------------------------------------------------------


def memory_dsn() -> str:
    """Postgres for what luach remembers about a member, across every thread.

    Unset means no memory tool at all, the same way an unset search URL means
    no search: a household that has not been given a database should hear "I
    cannot remember things" rather than watch facts vanish into a store that
    is not there.
    """
    return env("LUACH_MEMORY_DSN")


def memory_table() -> str:
    return env("LUACH_MEMORY_TABLE", "member_facts")


def embedding_cache_dir() -> Path:
    """Where the ONNX embedder keeps its model.

    The root filesystem is read-only and $HOME is not writable, so the default
    has to be on the data volume. A model download that fails there does not
    fail loudly: recall dies quietly, because a failing tool still produces a
    reply.
    """
    return Path(env("LUACH_EMBED_CACHE", str(state_dir() / "fastembed")))


def embedding_model() -> str:
    return env("LUACH_EMBED_MODEL", "BAAI/bge-small-en-v1.5")


# --- web ------------------------------------------------------------------


def app_url() -> str:
    """Where links in mail point. No fallback: a wrong host is worse than none."""
    return env("LUACH_APP_URL").rstrip("/")


def household_name() -> str:
    """The household's name, as in "the Rivera household calendar".

    It names the calendar in mail, on the sign-in screen and on the public About
    and Privacy pages. Empty (the default) leaves it unnamed: "the household
    calendar".
    """
    return env("LUACH_HOUSEHOLD_NAME")


def household_calendar() -> str:
    """The calendar in a sentence: "the <name> household calendar", or "the
    household calendar" without a name."""
    name = household_name()
    return f"the {name} household calendar" if name else "the household calendar"


def operator_name() -> str:
    """Who runs this luach, as the public About and Privacy pages name them.
    Empty: the pages speak of "the person who runs this luach"."""
    return env("LUACH_OPERATOR_NAME")


def contact_email() -> str:
    """Where the public pages send questions and requests to delete an account.
    Empty: the pages give no address."""
    return env("LUACH_CONTACT_EMAIL")


def privacy_models() -> str:
    """The privacy page's paragraph on which AI models see what members ask, and
    where they run. Plain text. Empty: a general paragraph that names no provider,
    since only the person who runs luach knows which ones it uses."""
    return env("LUACH_PRIVACY_MODELS")


def user_agent() -> str:
    """How luach names itself to other servers: with its address when it has one,
    so the owner of a feed it fetches can find out who is asking."""
    home = app_url()
    return f"luach/0.1 (+{home})" if home else "luach/0.1"


def cookie_secure() -> bool:
    return flag("LUACH_COOKIE_SECURE", True)


#: The shortest service key luach accepts: 32 characters is what ``openssl rand -hex 16``
#: prints, and anything a person types is shorter.
MIN_KEY_LENGTH = 32

#: Values that ship in the example settings and in documentation. A copied ``.env.example``
#: once carried one of these straight into a running household, where it let anyone who
#: had read the example act as the owner. Compared lowercased.
PLACEHOLDER_KEYS = frozenset(
    {
        "replace-with-a-long-random-string",
        "replace-with-another-long-random-string",
        "changeme",
        "change-me",
        "secret",
        "your-key",
        "your-api-key",
    }
)

KEY_ADVICE = "generate one with `openssl rand -hex 32`"


class WeakKey(RuntimeError):
    """A service key that must not open anything; luach refuses to start with it."""


def weak_key(value: str) -> str | None:
    """Why ``value`` is not good enough to be a service key, or None if it is."""
    lowered = value.lower()
    if lowered in PLACEHOLDER_KEYS or lowered.startswith("replace-with"):
        return "is the placeholder from the example settings"
    if not value.isascii() or not value.isprintable():
        return "must be printable ASCII"
    if len(value) < MIN_KEY_LENGTH:
        return f"is shorter than {MIN_KEY_LENGTH} characters"
    if len(set(value)) < 8:
        return "repeats too few characters to be random"
    return None


def check_service_keys() -> None:
    """Refuse to start on a placeholder or short service key. Called at startup.

    The key acts as the owner, so a guessable one is the household's front door left
    open; a server that will not start says so where the person who set it will look.
    """
    for name in ("LUACH_API_KEY", "LUACH_TULIP_KEY"):
        value = env(name)
        if value and (why := weak_key(value)):
            raise WeakKey(f"{name} {why}; {KEY_ADVICE}, or leave it unset to switch it off")


def api_key() -> str:
    """The trusted-service key, for a service (a chat bot, say) that acts as the
    owner. Empty disables the header path, and so does a weak value (``weak_key``),
    which startup refuses anyway."""
    key = env("LUACH_API_KEY")
    return "" if key and weak_key(key) else key


def api_key_name() -> str:
    """The name the trusted-service key carries on the audit trail, and the door
    its requests arrive through."""
    return env("LUACH_API_KEY_NAME", "service")


#: The name the read-only agent-platform key carries on the audit trail. Fixed, not
#: configurable: a record that says "tulip" must always mean this key and nothing else.
TULIP_PRINCIPAL = "tulip"


def tulip_key() -> str:
    """A second key, for an agent platform that calls luach (``LUACH_TULIP_KEY``).
    Empty disables it.

    A narrower door than the service key: it reads, and it talks to the agent, whose
    gate still decides every write. It never approves anything -- not with
    ``approved``, not with a "yes" -- and it cannot reach a write route directly
    (``luach.auth.api_key.TULIP_ALLOWED``). A value equal to ``LUACH_API_KEY``
    disables it, since the same secret cannot be two callers.
    """
    key = env("LUACH_TULIP_KEY")
    if key and (key == env("LUACH_API_KEY") or weak_key(key)):
        return ""
    return key


# --- single sign-on (OIDC) -------------------------------------------------

DEFAULT_OIDC_LABEL = "Sign in with single sign-on"
DEFAULT_OIDC_SCOPES = "openid email profile groups"
DEFAULT_OIDC_GROUP = "admins"


@dataclass(frozen=True)
class OidcSettings:
    """Every ``LUACH_OIDC_*`` setting, read together at call time."""

    issuer: str
    client_id: str
    client_secret: str
    required_group: str
    label: str
    scopes: str
    groups_claim: str
    email_claim: str
    redirect_uri: str
    http_timeout: float

    @property
    def enabled(self) -> bool:
        """Offered only when the client is configured AND a group gates it.

        An explicitly empty ``LUACH_OIDC_REQUIRED_GROUP`` never means "anyone
        the provider knows": it switches single sign-on off.
        """
        return bool(self.issuer and self.client_id and self.client_secret and self.required_group)


def oidc_settings() -> OidcSettings:
    issuer = env("LUACH_OIDC_ISSUER")
    client_id = env("LUACH_OIDC_CLIENT_ID")
    client_secret = env("LUACH_OIDC_CLIENT_SECRET")
    group_raw = os.environ.get("LUACH_OIDC_REQUIRED_GROUP")
    required_group = DEFAULT_OIDC_GROUP if group_raw is None else group_raw.strip()
    if issuer and client_id and client_secret and not required_group:
        logger.warning("LUACH_OIDC_REQUIRED_GROUP is empty: single sign-on is disabled")
    try:
        timeout = float(env("LUACH_OIDC_HTTP_TIMEOUT", "10"))
    except ValueError:
        logger.warning("LUACH_OIDC_HTTP_TIMEOUT is not a number; using 10 seconds")
        timeout = 10.0
    if timeout <= 0:
        timeout = 10.0
    return OidcSettings(
        issuer=issuer,
        client_id=client_id,
        client_secret=client_secret,
        required_group=required_group,
        label=env("LUACH_OIDC_LABEL") or DEFAULT_OIDC_LABEL,
        scopes=env("LUACH_OIDC_SCOPES") or DEFAULT_OIDC_SCOPES,
        groups_claim=env("LUACH_OIDC_GROUPS_CLAIM") or "groups",
        email_claim=env("LUACH_OIDC_EMAIL_CLAIM") or "email",
        redirect_uri=env("LUACH_OIDC_REDIRECT_URI") or f"{app_url()}/api/auth/oidc/callback",
        http_timeout=timeout,
    )


# --- calendar -------------------------------------------------------------


def timezone() -> str:
    return env("LUACH_TIMEZONE", DEFAULT_TIMEZONE)


def google_sa_key() -> str:
    return env("LUACH_GOOGLE_SA_KEY")


def google_calendar_id() -> str:
    return env("LUACH_GOOGLE_CALENDAR_ID")


def google_oauth_client() -> str:
    return env("LUACH_GOOGLE_OAUTH_CLIENT")


def google_oauth_tokens() -> str:
    return env("LUACH_GOOGLE_OAUTH_TOKENS")


def calendar_auth() -> str:
    """Which Google credential the calendar uses: ``oauth`` (the owner's grant —
    it can list their calendars and send invitations), ``sa`` (the service
    account), or ``auto``: the grant when it is on disk, the key otherwise."""
    return env("LUACH_CALENDAR_AUTH", "auto").lower()


CALENDAR_BACKENDS = ("local", "google", "fake")


def calendar_backend() -> str:
    """Where events live (``LUACH_CALENDAR``): ``local``, luach's own database, unless
    the deployment says otherwise; ``google``; or ``fake``, in memory, for tests.

    ``local`` is the default because it needs nothing else and keeps what a family adds.
    The default used to be Google, which without a credential fell back to the fake with
    a warning only on first use, and a new household lost its events at the next restart.
    A value that is none of these is returned as written, for calendar_problem() to refuse.
    """
    return env("LUACH_CALENDAR", "local").lower() or "local"


def has_google_credential() -> bool:
    """Whether the Google credential LUACH_CALENDAR_AUTH picks is set."""
    has_oauth = bool(google_oauth_client() and google_oauth_tokens())
    auth = calendar_auth()
    if auth == "sa":
        return bool(google_sa_key())
    if auth == "oauth":
        return has_oauth
    return bool(google_sa_key()) or has_oauth


def calendar_problem() -> str:
    """Why the configured calendar cannot be used, as a sentence for the log; "" when it can.

    Checked at startup, after load_credentials(): a Google calendar with no credential
    stops the server with this message instead of quietly keeping events in memory."""
    backend = calendar_backend()
    if backend not in CALENDAR_BACKENDS:
        return (
            f"LUACH_CALENDAR={backend!r} is not a calendar luach knows: use local "
            "(events in luach's own database), google, or fake (memory only, for tests)"
        )
    if backend == "google" and not has_google_credential():
        need = {
            "sa": "LUACH_GOOGLE_SA_KEY",
            "oauth": "LUACH_GOOGLE_OAUTH_CLIENT and LUACH_GOOGLE_OAUTH_TOKENS",
        }.get(
            calendar_auth(),
            "LUACH_GOOGLE_SA_KEY, or LUACH_GOOGLE_OAUTH_CLIENT and LUACH_GOOGLE_OAUTH_TOKENS",
        )
        return (
            "LUACH_CALENDAR=google, but no Google credential is set: set "
            f"{need} (docs/SELF-HOSTING.md, The calendar), or set LUACH_CALENDAR=local "
            "to keep events in luach's own database"
        )
    return ""


# --- model ----------------------------------------------------------------


def model_id() -> str:
    """The household's model as the deployment sets it: the starting value of the
    default, which the owner can change in the app (``model_menu.default_id``,
    the one place that says which model answers). No default of its own: every
    household brings its own model, and unset, luach says no model is set up."""
    return env("LUACH_MODEL")


def models() -> str:
    """The menu a fresh database starts with (``luach.model_menu.seed``): a JSON
    list of ``{"id", "name", "about", "local"}``, ids as the model server names
    them. Read once, into the database, the first time the menu is empty; after
    that the owner manages the menu in the app."""
    return env("LUACH_MODELS")


def model_base_url() -> str:
    """The OpenAI-compatible endpoint every model is asked through, ending in /v1.
    No default: unset, no model answers (and luach says so)."""
    return env("OPENAI_BASE_URL").rstrip("/")


def model_catalogue_url() -> str:
    """Where the owner's Models screen lists the models it can add: the endpoint's
    own ``/models`` unless ``LUACH_MODEL_CATALOGUE_URL`` names another list (a
    router whose wildcard route lists nothing behind it, say). Only a configured
    address is ever fetched; "" when there is neither."""
    url = env("LUACH_MODEL_CATALOGUE_URL")
    if url:
        return url
    base = model_base_url()
    return f"{base}/models" if base else ""


def model_catalogue_prefix() -> str:
    """Put before every id the catalogue lists, to make it the name the endpoint
    answers to: ``openrouter/`` for a LiteLLM router whose ``openrouter/*`` route
    reaches OpenRouter's catalogue."""
    return env("LUACH_MODEL_CATALOGUE_PREFIX")


def model_trials_per_day() -> int:
    """How many "Try it" runs the owner may start in 24 hours: each one is about
    fifteen model turns, paid for where the model is a cloud one."""
    try:
        return max(0, int(env("LUACH_MODEL_TRIALS_PER_DAY", "6")))
    except ValueError:
        return 6


def model_api_key() -> str:
    return env("OPENAI_API_KEY", "not-needed")


def enable_thinking() -> bool:
    """Whether the model reasons out loud before answering.

    Off, and measured rather than assumed. The chat renders reasoning as a
    foldable line and the backend has always streamed it, so turning this on
    costs nothing in the UI — but on qwen3.6-35b behind an OpenAI-compatible
    router it costs the tool calls. Asked "when does Chelsea play next?", the
    model spent its turn thinking and returned no content and
    no tool call at all ("Completed 1 iterations with 0 tool calls"), where the
    same question with this off read the calendar and answered. Turn it on per
    environment once a model handles both.

    Measured again through OpenRouter (whose own ``reasoning``
    switch, not this template flag, is what reaches the model there): with
    reasoning on, the mail eval passed 56 of 64 cases against 93 of 96 with it
    off, chat turns took 9.9 s against 2.9 s and an email 25.8 s against 3.2 s,
    and most misses were the same turn as above — all reasoning, no call, no
    words. The 2048-token reply budget (``get_model``) is spent on thinking
    before an answer starts. Off it stays.
    """
    return flag("LUACH_ENABLE_THINKING", False)


def max_iterations() -> int:
    """How many model calls one turn may take.

    Eight was enough while every tool was a calendar tool. A web search costs a
    call to search, a call to read what came back and a call to act on it, so a
    question like "mark the Brazil game and find who streams it" ran out
    mid-sentence and the turn ended with nothing done.
    """
    return int(env("LUACH_MAX_ITERATIONS", "16"))


# --- doors ----------------------------------------------------------------


def transcribe_cmd() -> str:
    """A command that takes one audio file and prints its transcript."""
    return env("LUACH_TRANSCRIBE_CMD")


def transcribe_url() -> str:
    """An OpenAI-compatible ``/v1/audio/transcriptions`` endpoint.

    When set it wins over ``LUACH_TRANSCRIBE_CMD``: a container usually has no GPU
    and no whisper binary, so voice becomes a call to a transcription server.
    """
    return env("LUACH_TRANSCRIBE_URL")


def transcribe_key() -> str:
    """Bearer key for ``LUACH_TRANSCRIBE_URL``; empty sends no Authorization header."""
    return env("LUACH_TRANSCRIBE_KEY")


def transcribe_model() -> str:
    return env("LUACH_TRANSCRIBE_MODEL", "whisper-1")


DEFAULT_TRUSTED_PROXIES = "127.0.0.1/32,::1/128"


def trusted_proxies() -> list[str]:
    """Networks whose forwarded-client headers are believed (CIDRs, comma separated).

    Loopback by default, for a reverse proxy on the same host. In a cluster, or
    behind Docker's network, the proxy connects from another address, so the
    deployment lists that range instead.
    """
    raw = env("LUACH_TRUSTED_PROXIES", DEFAULT_TRUSTED_PROXIES)
    return [part.strip() for part in raw.split(",") if part.strip()]


def gmail_label() -> str:
    return env("LUACH_GMAIL_LABEL", "luach")


def gmail_api() -> str:
    """Where the Gmail API lives. Only a test environment moves it.

    The email door is the one integration that cannot be rehearsed: there is a
    single Google account, so a test environment either polls the household's
    real inbox or tests nothing. Pointing it at a fixture service keeps the door
    itself — labels, threading, the agent turn, relabelling — under test.
    """
    return env("LUACH_GMAIL_API", "https://gmail.googleapis.com/gmail/v1/users/me").rstrip("/")


def google_token_url() -> str:
    """The OAuth refresh endpoint, moved alongside gmail_api() in a test environment."""
    return env("LUACH_GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")


def mail_oauth_client() -> str:
    """The Google OAuth client ("web application" type) a member connects their own
    Gmail through. Its redirect URI must be <LUACH_APP_URL>/api/mail/callback. Unset
    means connecting is not offered: the door's client has no such redirect, and a
    button that ends on Google's error page is worse than none."""
    return env("LUACH_MAIL_OAUTH_CLIENT")


def mail_domain() -> str:
    """The Google Workspace domain members connect their mail from (e.g. example.com).

    luach's mail client is an Internal app there: no "unverified app" screen, and
    only that domain's accounts may connect. Set, Google's account chooser offers
    only those accounts, with the member's own address first; unset, any account."""
    return env("LUACH_MAIL_DOMAIN").lower().lstrip("@")


def google_auth_url() -> str:
    return env("LUACH_GOOGLE_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth")


def google_revoke_url() -> str:
    return env("LUACH_GOOGLE_REVOKE_URL", "https://oauth2.googleapis.com/revoke")


def mail_key() -> str:
    """Encrypts each member's Gmail grant at rest. Unset: a key file luach makes beside
    the database (mail.key) — outside the database and outside its backups, so a copy
    of either alone opens no one's mail."""
    return env("LUACH_MAIL_KEY")


def gmail_poll_minutes() -> int:
    return int(env("LUACH_GMAIL_POLL_MIN", "0"))


def mail_scan_minutes() -> int:
    """How often the email scan reads the inboxes of members who turned it on
    (ingest/mail_scan.py). Every message it reads is a model turn, so not more
    often than the mail is worth; 0 switches the scan off and hides its setting."""
    return int(env("LUACH_MAIL_SCAN_MIN", "10"))


# --- mail -----------------------------------------------------------------


def search_url() -> str:
    """The household's SearXNG, which must answer JSON. Unset or empty means no
    web search: the model is not offered the search tools at all.
    """
    return env("LUACH_SEARCH_URL").rstrip("/")


def zoom_account_id() -> str:
    return env("LUACH_ZOOM_ACCOUNT_ID")


def zoom_client_id() -> str:
    return env("LUACH_ZOOM_CLIENT_ID")


def zoom_client_secret() -> str:
    return env("LUACH_ZOOM_CLIENT_SECRET")


def resend_key() -> str:
    return env("RESEND_API_KEY")


def mail_from() -> str:
    return env("LUACH_MAIL_FROM")


def mail_reply_to() -> str:
    return env("LUACH_MAIL_REPLY_TO")


# --- push -----------------------------------------------------------------


def vapid_public() -> str:
    return env("LUACH_VAPID_PUBLIC")


def vapid_private() -> str:
    return env("LUACH_VAPID_PRIVATE")


def vapid_subject() -> str:
    """How a push service reaches whoever runs this luach (RFC 8292): a mailto: or
    https: URI. Unset: the app's own address when it is https, else a local mailbox."""
    explicit = env("LUACH_VAPID_SUBJECT")
    if explicit:
        return explicit
    home = app_url()
    return home if home.startswith("https://") else "mailto:admin@localhost"


# --- passkeys -------------------------------------------------------------


def rp_id() -> str:
    """The WebAuthn relying-party id: the app's hostname unless overridden."""
    explicit = env("LUACH_RP_ID")
    if explicit:
        return explicit
    from urllib.parse import urlparse

    return urlparse(app_url()).hostname or "localhost"


def rp_origins() -> list[str]:
    """Origins a passkey response may come from (the app URL, plus LUACH_EXTRA_ORIGINS)."""
    origins = [app_url()] if app_url() else []
    origins += [o.strip() for o in env("LUACH_EXTRA_ORIGINS").split(",") if o.strip()]
    return origins or ["http://localhost:8004"]

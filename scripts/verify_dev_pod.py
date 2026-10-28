"""The half of a deployment check that runs inside luach's container, fed on stdin.

    kubectl exec -i deploy/luach -c luach -- python - mint < scripts/verify_dev_pod.py
    docker compose exec -T luach python - door < scripts/verify_dev_pod.py

    python - mint    print `<cookie name> <token>`: a session for the owner, the first account,
                     for scripts/verify_dev.py. Log it out (POST /api/auth/logout) when done.
    python - door    the email door against a test deployment's Gmail stand-in
                     (fixtures/gmail-fake): it is configured, luach's grant refreshes against the
                     stand-in, the stand-in answers a search with its fixture flight, and the door
                     has handled the fixture appointment. Read-only: nothing is relabelled, no turn
                     is run.

Imports only luach.config and luach.db. Loading the agent here would load a second copy of the
memory embedder beside the app's in one container, which can push a container with a tight memory
limit over it and get the app killed.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from luach import config

config.load_credentials()

from luach import db  # noqa: E402  (after the credentials: the database may be named in them)


def mint() -> int:
    from luach.auth import sessions

    owner = db.owner_id()
    if owner is None:
        print("dev has no accounts", file=sys.stderr)
        return 1
    print(sessions.COOKIE_NAME, sessions.mint_session(owner))
    return 0


def _get(url: str, token: str, query: dict | None = None) -> dict:
    if query:
        url += "?" + urllib.parse.urlencode(query, doseq=True)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read() or b"{}")


def door() -> int:
    ok = True

    def check(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        ok = ok and passed
        print(f"{'ok  ' if passed else 'FAIL'} {name}{'  ' + detail if detail else ''}", flush=True)

    api = config.gmail_api()
    configured = bool(
        config.google_oauth_client()
        and config.google_oauth_tokens()
        and config.gmail_poll_minutes()
    )
    check("the email door is configured", configured, f"every {config.gmail_poll_minutes()} min")
    stand_in = "googleapis.com" not in api
    check("and points at the stand-in, not Google", stand_in, api)
    if not (configured and stand_in):
        return 1

    # The door's own refresh: the grant in dev's credential, against the stand-in's token URL.
    with open(config.google_oauth_tokens()) as fh:
        tokens = json.load(fh)
    with open(config.google_oauth_client()) as fh:
        client = json.load(fh)
    body = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": client["client_id"],
            "client_secret": client["client_secret"],
        }
    ).encode()
    # A refused connection is retried for a minute: luach and the stand-in roll out together,
    # and for a few seconds after the stand-in's Recreate its Service can still point at the pod
    # that is gone. Half of 2026-10-26's runs failed on exactly that, and blocked luach's
    # promotion. Anything else -- a refusal that lasts, a bad grant, a bad answer -- still fails.
    for attempt in range(13):
        try:
            with urllib.request.urlopen(config.google_token_url(), data=body, timeout=30) as resp:
                token = str(json.loads(resp.read())["access_token"])
            check("the grant refreshes", True, f"after {attempt} retries" if attempt else "")
            break
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, ConnectionRefusedError) and attempt < 12:
                time.sleep(5)
                continue
            check("the grant refreshes", False, f"{type(exc).__name__}: {exc}")
            return 1
        except Exception as exc:  # any failure is the finding
            check("the grant refreshes", False, f"{type(exc).__name__}: {exc}")
            return 1

    try:
        labels = {lab["name"] for lab in _get(f"{api}/labels", token).get("labels", [])}
        check("the door's label is there", config.gmail_label() in labels, ",".join(sorted(labels)))
        hits = (
            _get(f"{api}/messages", token, {"q": "madrid", "maxResults": 5}).get("messages") or []
        )
        check(
            "a search finds the fixture flight",
            any(h.get("id") == "msg-flight" for h in hits),
            f"{len(hits)} found",
        )
    except Exception as exc:
        check("the stand-in answers", False, f"{type(exc).__name__}: {exc}")

    with db.session() as s:
        row = s.get(db.ProcessedMail, "msg-appointment")
        outcome = (row.outcome or "")[:80] if row is not None else ""
    check("the door has handled the fixture appointment", row is not None, outcome)
    return 0 if ok else 1


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "mint":
        sys.exit(mint())
    if mode == "door":
        sys.exit(door())
    print("usage: python - mint|door", file=sys.stderr)
    sys.exit(2)

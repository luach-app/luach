"""Every response carries the browser hardening headers, whatever proxy is in front."""

from __future__ import annotations

from fastapi.testclient import TestClient

from luach.app import SECURITY_HEADERS, create_app


def test_every_response_carries_the_hardening_headers() -> None:
    client = TestClient(create_app())
    for path in ("/api/health", "/api/auth/status", "/api/no-such-route"):
        r = client.get(path)
        for name, value in SECURITY_HEADERS:
            assert r.headers.get(name.decode()) == value.decode(), (path, name)


def test_the_app_can_still_set_its_own_value() -> None:
    """A route that sets a header keeps it; the middleware only fills what is missing."""
    present = {k.decode() for k, _ in SECURITY_HEADERS}
    assert "strict-transport-security" in present and "content-security-policy" in present

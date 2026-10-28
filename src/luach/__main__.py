"""`python -m luach` — run the service."""

from __future__ import annotations

import logging
import os
import sys


def main() -> None:
    import uvicorn

    logging.basicConfig(
        level=os.getenv("LUACH_LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s: %(message)s"
    )
    host = os.getenv("LUACH_HOST", "127.0.0.1")
    port = int(os.getenv("LUACH_PORT", "8004"))
    try:
        from luach import config

        # Forwarded headers are believed only from the front doors (loopback for a
        # reverse proxy on the same host, the pod network in a cluster), the same
        # list client_ip() uses.
        uvicorn.run(
            "luach.app:app",
            host=host,
            port=port,
            log_level="info",
            proxy_headers=True,
            forwarded_allow_ips=config.trusted_proxies(),
        )
    except OSError as exc:  # port taken: exit 78 so systemd stops instead of looping
        print(f"luach: cannot bind {host}:{port}: {exc}", file=sys.stderr)
        sys.exit(78)


if __name__ == "__main__":
    main()

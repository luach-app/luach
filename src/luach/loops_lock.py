"""Only one copy of luach runs the background loops.

A rolling deploy starts the new copy before it stops the old one, so for a few seconds two
copies share the data volume. Both may serve requests — SQLite in WAL mode takes
two processes on one host, and the audit chain reloads when another writer moves
it — but the loops check "already sent?" and then send, with nothing claimed in
between: two copies would send a reminder twice, or read the same email twice.

So the loops belong to whoever holds an exclusive lock on a file beside the
database. The kernel lets go of it when the holder exits, however it exits, and
the new copy picks it up on its next try.
"""

from __future__ import annotations

import asyncio
import fcntl
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

RETRY_SECONDS = 5.0

#: The open file whose lock this process holds; kept so it is never closed.
_held: int | None = None


def try_take(path: Path) -> bool:
    """Take the lock if nobody holds it. True when this process holds it now."""
    global _held
    if _held is not None:
        return True
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return False
    _held = fd
    return True


def release() -> None:
    global _held
    if _held is not None:
        os.close(_held)  # closing the last descriptor drops the flock
        _held = None


async def wait_for(path: Path, retry: float = RETRY_SECONDS) -> None:
    """Return once this process holds the lock — at once, unless an older copy
    still does, and then as soon as it has gone."""
    said = False
    while not try_take(path):
        if not said:
            logger.info("loops: another copy is running them; waiting for it to stop")
            said = True
        await asyncio.sleep(retry)
    if said:
        logger.info("loops: the other copy has stopped; running them here")

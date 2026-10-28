"""During a deploy two copies of luach share the data volume for a few seconds;
only one of them may run the loops that send reminders and read the mail."""

from __future__ import annotations

import asyncio
import subprocess
import sys

import pytest

from luach import loops_lock

HOLD = (
    "import fcntl, os, sys, time\n"
    "fd = os.open(sys.argv[1], os.O_RDWR | os.O_CREAT)\n"
    "fcntl.flock(fd, fcntl.LOCK_EX)\n"
    "print('held', flush=True)\n"
    "sys.stdin.readline()\n"
)


@pytest.fixture(autouse=True)
def fresh():
    loops_lock.release()
    yield
    loops_lock.release()


@pytest.fixture
def older_copy(tmp_path):
    """Another process — the pod being replaced — holding the lock until told to stop."""
    path = tmp_path / "loops.lock"
    p = subprocess.Popen(
        [sys.executable, "-c", HOLD, str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert p.stdout is not None and p.stdout.readline().strip() == "held"
    yield path, p
    p.kill()
    p.wait()


def test_the_first_copy_takes_it(tmp_path):
    assert loops_lock.try_take(tmp_path / "loops.lock")


def test_not_while_the_older_copy_runs_them(older_copy):
    path, _ = older_copy
    assert not loops_lock.try_take(path)


async def test_the_new_copy_takes_over_once_the_old_one_stops(older_copy):
    path, old = older_copy
    waiting = asyncio.create_task(loops_lock.wait_for(path, retry=0.05))
    await asyncio.sleep(0.2)
    assert not waiting.done(), "the old copy still runs them"
    old.kill()  # however it stops, the kernel drops its lock
    old.wait()
    await asyncio.wait_for(waiting, timeout=5)
    assert loops_lock.try_take(path)


def test_release_hands_it_on(tmp_path):
    path = tmp_path / "loops.lock"
    assert loops_lock.try_take(path)
    loops_lock.release()
    check = subprocess.run(
        [
            sys.executable,
            "-c",
            "import fcntl, os, sys\n"
            "fd = os.open(sys.argv[1], os.O_RDWR)\n"
            "fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)\n",
            str(path),
        ],
        check=False,
    )
    assert check.returncode == 0

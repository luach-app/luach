"""Voice in. Either an OpenAI-compatible transcription endpoint
(LUACH_TRANSCRIBE_URL, a whisper server on a private network, say) or one command
that takes an audio file and prints text (LUACH_TRANSCRIBE_CMD, whisper.cpp on a
local GPU, for example). The URL wins when both are set."""

from __future__ import annotations

import contextlib
import logging
import os
import shlex
import shutil
import subprocess
import tempfile

import requests

from luach import config

logger = logging.getLogger(__name__)

MAX_BYTES = 12 * 1024 * 1024
TIMEOUT = 120


SUFFIXES = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
}


def _suffix(content_type: str) -> str:
    return SUFFIXES.get(content_type.split(";")[0].strip(), ".bin")


def available() -> bool:
    if config.transcribe_url():
        return True
    cmd = config.transcribe_cmd()
    if not cmd:
        return False
    exe = shlex.split(cmd)[0]
    return shutil.which(exe) is not None or os.access(exe, os.X_OK)


def transcribe(data: bytes, content_type: str = "") -> str:
    if not available():
        raise RuntimeError("transcription is not configured")
    if len(data) > MAX_BYTES:
        raise ValueError("audio is too large")
    suffix = _suffix(content_type)
    if config.transcribe_url():
        return _over_http(data, content_type, suffix)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as fh:
        fh.write(data)
        path = fh.name
    try:
        proc = subprocess.run(
            [*shlex.split(config.transcribe_cmd()), path],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            check=False,
        )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)
    if proc.returncode != 0:
        logger.error("transcribe failed (%s): %s", proc.returncode, proc.stderr[-400:])
        raise RuntimeError("transcription failed")
    return " ".join(proc.stdout.split())


def _over_http(data: bytes, content_type: str, suffix: str) -> str:
    headers = {}
    if config.transcribe_key():
        headers["Authorization"] = f"Bearer {config.transcribe_key()}"
    try:
        resp = requests.post(
            config.transcribe_url(),
            headers=headers,
            files={"file": (f"audio{suffix}", data, content_type or "application/octet-stream")},
            data={"model": config.transcribe_model(), "response_format": "json"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        logger.error("transcribe endpoint unreachable: %s", exc)
        raise RuntimeError("transcription failed") from exc
    if resp.status_code != 200:
        logger.error("transcribe endpoint returned %s: %s", resp.status_code, resp.text[-400:])
        raise RuntimeError("transcription failed")
    return " ".join(str(resp.json().get("text", "")).split())

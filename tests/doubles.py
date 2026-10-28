"""Scripted tulip model doubles. tulip is real in tests; only the model is faked."""

from __future__ import annotations

import base64

from tulip.core.events import ModelChunkEvent
from tulip.core.messages import Message, ToolCall
from tulip.models.base import ModelResponse


def say(text: str) -> ModelChunkEvent:
    return ModelChunkEvent(content=text)


def call(name: str, **arguments) -> ModelChunkEvent:
    return ModelChunkEvent(tool_calls=[ToolCall(name=name, arguments=arguments)])


class ScriptedModel:
    """Each turn is a list of chunks; tool-call chunks are emitted last, then done."""

    def __init__(self, turns):
        self.turns = [list(t) for t in turns]
        self.calls: list[dict] = []

    async def stream(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        tool_calls: list[ToolCall] = []
        for c in self.turns.pop(0) if self.turns else []:
            if c.tool_calls:
                tool_calls.extend(c.tool_calls)
            else:
                yield c
        if tool_calls:
            yield ModelChunkEvent(tool_calls=tool_calls)
        yield ModelChunkEvent(done=True, stop_reason="stop")

    async def complete(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, **kwargs})
        content: list[str] = []
        tool_calls: list[ToolCall] = []
        for c in self.turns.pop(0) if self.turns else []:
            if c.content:
                content.append(c.content)
            if c.tool_calls:
                tool_calls.extend(c.tool_calls)
        return ModelResponse(
            message=Message.assistant(content="".join(content) or None, tool_calls=tool_calls),
            stop_reason="tool_calls" if tool_calls else "stop",
        )


class FailingModel:
    async def complete(self, messages, tools=None, **kwargs):
        raise RuntimeError("model gone")

    async def stream(self, messages, tools=None, **kwargs):
        raise RuntimeError("model gone")
        yield  # pragma: no cover


def confirm_address(user_id: int, email: str, kind: str = "notify") -> None:
    """Follow the confirmation link luach just mailed, without reading the mail."""
    from luach.auth import users

    users.verify_address(users.start_verification(user_id, email, kind))


def pdf_bytes(text: str) -> bytes:
    """A one-page PDF holding ``text``, written by hand: enough for a reader."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return out


def with_pdf(message: dict, name: str, pdf: bytes, size: int | None = None) -> dict:
    data = base64.urlsafe_b64encode(pdf).decode()
    body = message["payload"]
    message["payload"] = {
        "headers": body["headers"],
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/plain", "body": body["body"]},
            {
                "mimeType": "application/pdf",
                "filename": name,
                "body": {"attachmentId": "a1", "size": size or len(pdf)},
            },
        ],
    }
    message["_attachments"] = {"a1": data}
    return message

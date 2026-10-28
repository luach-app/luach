#!/usr/bin/env python3
"""A tiny OpenAI-compatible model for integration tests (stdlib only).

Serves /v1/models and /v1/chat/completions, streaming or not. Agents built on tulip may insist on a
tool call first (tool_choice="required"), so: while the conversation has no tool result yet and
tools are offered, it calls the first offered tool whose parameters need no arguments; after that
(or with no usable tool) it answers with FAKE_LLM_REPLY. Every request is appended to
FAKE_LLM_LOG as one JSON line, so tests can assert the app really called the model.

    python3 fake_llm.py [PORT] [HOST]   (default 18080 on 127.0.0.1)
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = os.environ.get("FAKE_LLM_REPLY", "pong")
LOG = os.environ.get("FAKE_LLM_LOG", "/tmp/fake-llm.jsonl")


def choose_tool(body: dict) -> dict | None:
    messages = body.get("messages") or []
    if any(m.get("role") == "tool" for m in messages):
        return None
    for tool in body.get("tools") or []:
        fn = tool.get("function") or {}
        params = fn.get("parameters") or {}
        if not params.get("required"):
            return fn
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: object) -> None:
        pass

    def _json(self, code: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path.rstrip("/").endswith("/models"):
            self._json(200, {"object": "list", "data": [{"id": "fake", "object": "model"}]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        with open(LOG, "a") as fh:
            fh.write(json.dumps({"path": self.path, "body": body}) + "\n")
        if not self.path.rstrip("/").endswith("/chat/completions"):
            self._json(404, {"error": "only chat/completions"})
            return
        tool = choose_tool(body)
        model = body.get("model", "fake")
        now = int(time.time())
        if tool:
            message = {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": tool["name"], "arguments": "{}"}}]}
            finish = "tool_calls"
        else:
            message = {"role": "assistant", "content": REPLY}
            finish = "stop"
        usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        if not body.get("stream"):
            self._json(200, {"id": "fake-1", "object": "chat.completion", "created": now, "model": model,
                             "choices": [{"index": 0, "message": message, "finish_reason": finish}], "usage": usage})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        delta = dict(message)
        if tool:
            delta["tool_calls"] = [dict(message["tool_calls"][0], index=0)]
        chunks = [
            {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
            {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}], "usage": usage},
        ]
        for c in chunks:
            c.update({"id": "fake-1", "object": "chat.completion.chunk", "created": now, "model": model})
            self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"
    ThreadingHTTPServer((host, port), Handler).serve_forever()

"""A letter sent as a PDF is read wherever luach reads mail: the "luach" label and chat."""

from __future__ import annotations

import base64

from luach import push
from luach.agent import runtime
from luach.ingest import gmail
from tests.doubles import ScriptedModel, call, pdf_bytes, say, with_pdf

LETTER = "Grade 3 visits the farm. Return the signed form by Friday."


def _letter() -> dict:
    body = base64.urlsafe_b64encode(b"Please see the attached letter.").decode()
    message = {
        "id": "m1",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Farm trip"},
                {"name": "From", "value": "School <office@school.example>"},
                {
                    "name": "Authentication-Results",
                    "value": "mx.google.com; dkim=pass header.i=@school.example",
                },
            ],
            "mimeType": "text/plain",
            "body": {"data": body},
        },
    }
    return with_pdf(message, "farm-trip.pdf", pdf_bytes(LETTER))


def _gmail_serving(message: dict):
    def fake_api(path, method="GET", payload=None, query=None, token=None):
        if path == "labels":
            return {"labels": [{"name": "luach", "id": "L1"}, {"name": "luach/done", "id": "L2"}]}
        if path == "messages":
            return {"messages": [{"id": message["id"]}]}
        if path.endswith("/modify"):
            return {}
        if "/attachments/" in path:
            return {"data": message["_attachments"][path.rsplit("/", 1)[1]]}
        if path.startswith("messages/"):
            return message
        raise AssertionError(path)

    return fake_api


async def test_a_letter_under_the_label_is_read_with_its_pdf(monkeypatch, calendar):
    monkeypatch.setattr(gmail, "_api", _gmail_serving(_letter()))
    monkeypatch.setattr("luach.mail_accounts.access_token", lambda uid: "owner-token")
    monkeypatch.setattr(push, "notify", lambda *a, **k: 1)
    model = ScriptedModel([[call("just_talking")], [say("nothing to schedule")]])
    runtime.set_model(model)

    await gmail.process_once()
    said = str(model.calls[0]["messages"])
    assert "--- ATTACHMENT: farm-trip.pdf ---" in said and "Return the signed form" in said


def test_an_email_opened_from_chat_carries_its_pdf(monkeypatch):
    monkeypatch.setattr(gmail, "_api", _gmail_serving(_letter()))
    monkeypatch.setattr("luach.mail_accounts.access_token", lambda uid: "member-token")

    mail = gmail.read(1, "m1")
    assert mail["subject"] == "Farm trip"
    assert "Please see the attached letter." in mail["text"]
    assert "--- ATTACHMENT: farm-trip.pdf ---" in mail["text"] and LETTER in mail["text"]

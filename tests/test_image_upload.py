"""send_image tải thẳng file ảnh lên Messenger (multipart `filedata`), không bắt Facebook tự tải ảnh qua URL công khai.

Thử thật trên Render 2026-10-24: URL ảnh mở được trong trình duyệt, /capnhatanh báo "Link ảnh: OK", mà Graph vẫn trả
"(#100) Upload failed" cho `attachment.payload.url`. Bot gửi file, Graph trả attachment_id, lần sau gửi bằng id đó.
"""

import asyncio
import json
import logging
import os
from email import policy
from email.parser import BytesParser
from io import BytesIO

import httpx
import pytest
from PIL import Image

from app import messenger
from app.config import settings
from app.messenger import build_quick_replies

SENDER = "9000000000000801"
PAGE_TOKEN = "EAAG-page-token-image-upload"


def jpeg(color=(200, 30, 30)) -> bytes:
    out = BytesIO()
    Image.new("RGB", (40, 30), color).save(out, "JPEG")
    return out.getvalue()


def parse(request: httpx.Request) -> dict:
    """Body of a /me/messages request: the JSON, or the multipart form fields (a file: (name, type, bytes))."""
    content_type = request.headers["content-type"]
    if content_type.startswith("application/json"):
        return {"json": json.loads(request.content)}
    assert content_type.startswith("multipart/form-data"), content_type
    message = BytesParser(policy=policy.HTTP).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + request.content
    )
    fields = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        data = part.get_payload(decode=True)
        fields[name] = (part.get_filename(), part.get_content_type(), data) if part.get_filename() else data.decode()
    return {"form": fields}


class FakeGraph:
    """graph.facebook.com /me/messages: an upload gets a new attachment_id; ids in `refused` are refused."""

    def __init__(self):
        self.requests: list[dict] = []
        self.refused: set[str] = set()
        self.ids = 0

    async def respond(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "graph.facebook.com" and request.url.path.endswith("/me/messages")
        assert request.url.params["access_token"] == PAGE_TOKEN
        await request.aread()
        body = parse(request)
        self.requests.append(body)
        if "form" in body:
            self.ids += 1
            return httpx.Response(200, json={"recipient_id": SENDER, "message_id": "m_1", "attachment_id": f"att-{self.ids}"})
        attachment_id = body["json"]["message"]["attachment"]["payload"].get("attachment_id")
        if attachment_id in self.refused:
            error = {"message": f"(#100) Invalid attachment_id access_token={PAGE_TOKEN}", "code": 100}
            return httpx.Response(400, json={"error": error})
        return httpx.Response(200, json={"recipient_id": SENDER, "message_id": "m_2"})

    def sent(self) -> list[tuple]:
        """("upload", file name) or ("id", attachment_id) per request."""
        return [
            ("upload", r["form"]["filedata"][0]) if "form" in r
            else ("id", r["json"]["message"]["attachment"]["payload"]["attachment_id"])
            for r in self.requests
        ]


@pytest.fixture
def graph(monkeypatch):
    fake = FakeGraph()

    async def handle(self, request):
        return await fake.respond(request)

    monkeypatch.setattr(settings, "FB_PAGE_ACCESS_TOKEN", PAGE_TOKEN)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle)
    monkeypatch.setattr(messenger, "_attachment_ids", {})
    return fake


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "km-tkb-36-72.jpg"
    path.write_bytes(jpeg())
    return path


def test_an_image_file_is_uploaded_as_multipart_filedata_with_the_quick_replies(graph, photo):
    quick_replies = build_quick_replies("campus")

    asyncio.run(messenger.send_image(SENDER, photo, quick_replies=quick_replies))

    (request,) = graph.requests
    form = request["form"]
    assert sorted(form) == ["filedata", "message", "messaging_type", "recipient"]
    assert json.loads(form["recipient"]) == {"id": SENDER}
    assert json.loads(form["message"]) == {
        "attachment": {"type": "image", "payload": {"is_reusable": True}},
        "metadata": "casa-bot",
        "quick_replies": quick_replies,
    }
    assert form["messaging_type"] == "RESPONSE"
    assert form["filedata"] == ("km-tkb-36-72.jpg", "image/jpeg", photo.read_bytes())
    assert "url" not in form["message"]


def test_a_png_file_goes_with_its_own_content_type(graph, tmp_path):
    path = tmp_path / "thuc-don.png"
    Image.new("RGB", (4, 4)).save(path, "PNG")

    asyncio.run(messenger.send_image(SENDER, path))

    (request,) = graph.requests
    assert request["form"]["filedata"][:2] == ("thuc-don.png", "image/png")
    assert "quick_replies" not in json.loads(request["form"]["message"])


def test_the_same_file_goes_by_its_attachment_id_the_next_time(graph, photo):
    quick_replies = build_quick_replies("age")

    asyncio.run(messenger.send_image(SENDER, photo))
    asyncio.run(messenger.send_image("9000000000000802", photo, quick_replies=quick_replies))

    assert graph.sent() == [("upload", "km-tkb-36-72.jpg"), ("id", "att-1")]
    assert graph.requests[1]["json"] == {
        "recipient": {"id": "9000000000000802"},
        "message": {
            "attachment": {"type": "image", "payload": {"attachment_id": "att-1"}},
            "metadata": "casa-bot",
            "quick_replies": quick_replies,
        },
        "messaging_type": "RESPONSE",
    }


def test_a_refused_attachment_id_is_forgotten_and_the_file_uploaded_again_once(graph, photo, caplog):
    asyncio.run(messenger.send_image(SENDER, photo))
    graph.refused = {"att-1"}

    with caplog.at_level(logging.DEBUG):
        asyncio.run(messenger.send_image(SENDER, photo))
    asyncio.run(messenger.send_image(SENDER, photo))

    assert graph.sent() == [("upload", "km-tkb-36-72.jpg"), ("id", "att-1"), ("upload", "km-tkb-36-72.jpg"), ("id", "att-2")]
    assert PAGE_TOKEN not in caplog.text
    assert "Invalid attachment_id" in caplog.text


def test_upload_failing_after_a_refused_attachment_id_raises_without_trying_again(graph, photo, monkeypatch):
    asyncio.run(messenger.send_image(SENDER, photo))
    graph.refused = {"att-1"}
    respond = graph.respond

    async def uploads_fail(request):
        response = await respond(request)
        if "form" in graph.requests[-1]:
            return httpx.Response(400, json={"error": {"message": "(#100) Upload failed", "code": 100}})
        return response

    monkeypatch.setattr(graph, "respond", uploads_fail)

    with pytest.raises(messenger.GraphError) as raised:
        asyncio.run(messenger.send_image(SENDER, photo))

    assert raised.value.message == "(#100) Upload failed (code 100)"
    assert graph.sent() == [("upload", "km-tkb-36-72.jpg"), ("id", "att-1"), ("upload", "km-tkb-36-72.jpg")]


def test_a_changed_file_is_uploaded_again(graph, photo):
    asyncio.run(messenger.send_image(SENDER, photo))
    photo.write_bytes(jpeg(color=(10, 200, 10)))
    stat = photo.stat()
    os.utime(photo, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

    asyncio.run(messenger.send_image(SENDER, photo))
    asyncio.run(messenger.send_image(SENDER, photo))

    assert graph.sent() == [("upload", "km-tkb-36-72.jpg"), ("upload", "km-tkb-36-72.jpg"), ("id", "att-2")]
    assert graph.requests[1]["form"]["filedata"][2] == photo.read_bytes()


def test_a_refused_upload_is_logged_and_raised_without_the_access_token(graph, photo, monkeypatch, caplog):
    async def refuse(request):
        await request.aread()
        error = {"message": f"(#100) Upload failed access_token={PAGE_TOKEN}", "code": 100}
        return httpx.Response(400, json={"error": error})

    monkeypatch.setattr(graph, "respond", refuse)

    with caplog.at_level(logging.DEBUG), pytest.raises(messenger.GraphError) as raised:
        asyncio.run(messenger.send_image(SENDER, photo))

    assert (raised.value.status, raised.value.message) == (400, "(#100) Upload failed access_token=*** (code 100)")
    assert PAGE_TOKEN not in str(raised.value) and PAGE_TOKEN not in caplog.text
    assert "Upload failed" in caplog.text
    assert messenger._attachment_ids == {}


def test_a_url_still_goes_as_a_url_facebook_downloads(graph):
    asyncio.run(messenger.send_image(SENDER, "https://cdn.example/b.jpg"))

    (request,) = graph.requests
    assert request["json"]["message"]["attachment"] == {
        "type": "image", "payload": {"url": "https://cdn.example/b.jpg", "is_reusable": True}
    }

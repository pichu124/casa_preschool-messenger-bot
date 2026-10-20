"""Sự kiện lead (SĐT mới, đổi SĐT, hẹn tham quan/học thử) sang nhóm Telegram và Google Sheet.

Telegram và Google Sheet chạy thật tới tầng httpx; transport giả trả lời như api.telegram.org và như web app
Apps Script (POST /exec → 302 → JSON ở script.googleusercontent.com). process_message gọi bằng asyncio.run.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.config import settings
from app.leads_sheet import post_lead_row

CUSTOMER_ID = "9000000000000401"
PHONE = "0900000401"
SHEET_DEPLOYMENT = "AKfycb-test-deployment"
SHEET_URL = f"https://script.google.com/macros/s/{SHEET_DEPLOYMENT}/exec"
SHEET_ECHO_URL = "https://script.googleusercontent.com/macros/echo?user_content_key=test-key&lib=test-lib"
SHEET_TOKEN = "sheet-token-test"
TELEGRAM_TOKEN = "123456:telegram-token-test"
VN = timezone(timedelta(hours=7))


# --- Telegram + Google Sheet giả ---


class Network:
    """api.telegram.org và web app Apps Script giả; ghi lại tin Telegram và body POST tới Google Sheet."""

    def __init__(self):
        self.telegram = []
        self.sheet = []
        self.sheet_response = lambda: httpx.Response(200, json={"ok": True})
        self.unexpected = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url == f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage":
            self.telegram.append(json.loads(request.content)["text"])
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 7000 + len(self.telegram)}})
        if request.method == "POST" and url == SHEET_URL:
            self.sheet.append(json.loads(request.content))
            return httpx.Response(302, headers={"Location": SHEET_ECHO_URL})
        if request.method == "GET" and url == SHEET_ECHO_URL:
            return self.sheet_response()
        self.unexpected.append(f"{request.method} {url}")
        return httpx.Response(404)


@pytest.fixture
def net(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", TELEGRAM_TOKEN)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "-1001")
    monkeypatch.setattr(settings, "LEADS_SHEET_WEBHOOK_URL", SHEET_URL)
    monkeypatch.setattr(settings, "LEADS_SHEET_TOKEN", SHEET_TOKEN)
    network = Network()

    async def handle_async_request(self, request):
        return await network.handle(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle_async_request)
    yield network
    assert network.unexpected == []


def sheet_down(request=None):
    raise httpx.ConnectError(f"cannot connect to {SHEET_URL} for {PHONE}")


SHEET_FAILURES = [
    lambda: httpx.Response(200, json={"ok": False}),
    lambda: httpx.Response(200, json={"ok": "true"}),
    lambda: httpx.Response(200, html="<html>Đăng nhập Google</html>"),
    lambda: httpx.Response(500, html="<html>Lỗi script</html>"),
    sheet_down,
]
SHEET_FAILURE_IDS = ["ok false", "ok không phải true", "trang HTML", "HTTP 500", "mất kết nối"]


def leaked(caplog) -> list[str]:
    secrets = (PHONE, SHEET_DEPLOYMENT, SHEET_TOKEN, TELEGRAM_TOKEN)
    return [r.getMessage() for r in caplog.records if any(s in r.getMessage() for s in secrets)]


def assert_vietnam_now(sheet_time: str):
    sent_at = datetime.strptime(sheet_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=VN)
    assert abs(datetime.now(VN) - sent_at) < timedelta(minutes=5)


# --- post_lead_row ---


def test_post_lead_row_without_url_makes_no_request(monkeypatch, net):
    monkeypatch.setattr(settings, "LEADS_SHEET_WEBHOOK_URL", "")

    assert asyncio.run(post_lead_row("new_phone", {"phone": PHONE})) is False
    assert net.sheet == []


@pytest.mark.parametrize(
    ("sheet_response", "ok"),
    [(lambda: httpx.Response(200, json={"ok": True}), True)] + [(failure, False) for failure in SHEET_FAILURES],
    ids=["ok true", *SHEET_FAILURE_IDS],
)
def test_post_lead_row_succeeds_only_on_ok_true(net, caplog, sheet_response, ok):
    net.sheet_response = sheet_response
    row = {"customer_id": CUSTOMER_ID, "phone": PHONE, "token": "giả", "event": "giả"}

    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(post_lead_row("visit_request", row)) is ok

    assert len(net.sheet) == 1
    body = net.sheet[0]
    assert (body["token"], body["event"], body["customer_id"], body["phone"]) == (
        SHEET_TOKEN,
        "visit_request",
        CUSTOMER_ID,
        PHONE,
    )
    assert_vietnam_now(body["time"])
    warnings = [r for r in caplog.records if r.name == "app.leads_sheet" and r.levelno == logging.WARNING]
    assert len(warnings) == int(not ok)
    assert leaked(caplog) == []

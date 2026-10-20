"""Phễu xin SĐT nối với tư vấn viên.

Phụ huynh để lại SĐT lần đầu thì nhóm Telegram nhận đúng một tin lead; câu chuyển tư vấn viên chỉ
mời để lại số khi chưa có số; history ghi đúng câu đã gửi; mỗi tin nhắn đồng bộ customers.json lên
GitHub đúng một lần. process_message gọi thẳng bằng asyncio.run (repo không có pytest-asyncio).
"""

import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest

import app.main as main
from app import customer_memory
from app.ai_engine import AIResponse
from app.config import settings

# conftest thay hàm này bằng stub cấm gọi; giữ bản thật để đếm request GitHub qua transport giả.
REAL_SYNC = customer_memory.sync_to_github

CUSTOMER_ID = "9000000000000101"
FB_NAME = "Lan Thử"
MODEL_TEXT = "Dạ bé 3 tuổi học lớp Mầm ạ. Ba/Mẹ muốn tham quan buổi sáng hay buổi chiều ạ?"


class FakeBot:
    """Ghi lại tin gửi phụ huynh."""

    def __init__(self):
        self.sent = []
        self.response = None
        self.extracted = {}

    def say(self, text, reply=MODEL_TEXT, escalate=False, extracted=None):
        """Phụ huynh gửi `text`; model trả `reply` và trích xuất ra `extracted`."""
        self.response = AIResponse(text=reply, should_escalate=escalate, model_used="fake-model")
        self.extracted = extracted or {}
        asyncio.run(main.process_message(CUSTOMER_ID, text))


@pytest.fixture
def bot(monkeypatch):
    bot = FakeBot()

    async def fake_send_message(recipient_id, text):
        assert recipient_id == CUSTOMER_ID
        bot.sent.append(text)

    async def fake_send_typing_indicator(recipient_id, action="typing_on"):
        pass

    async def fake_get_user_profile(user_id):
        first_name, last_name = FB_NAME.split()
        return {"first_name": first_name, "last_name": last_name}

    async def fake_get_response(user_message, conversation_history=None, customer_context="", gap_hours=0.0):
        return bot.response

    async def fake_extract_customer_info(user_message, existing_profile=None):
        return dict(bot.extracted)

    async def fake_sync_to_github():
        return True

    monkeypatch.setattr(main, "send_message", fake_send_message)
    monkeypatch.setattr(main, "send_typing_indicator", fake_send_typing_indicator)
    monkeypatch.setattr(main, "get_user_profile", fake_get_user_profile)
    monkeypatch.setattr(main.ai_engine, "get_response", fake_get_response)
    monkeypatch.setattr(main.ai_engine, "extract_customer_info", fake_extract_customer_info)
    monkeypatch.setattr(customer_memory, "sync_to_github", fake_sync_to_github)
    return bot


@pytest.fixture
def github(monkeypatch):
    """CUSTOMERS_GITHUB_REPO được đặt, sync_to_github thật; trả về các bản customers.json đã PUT lên GitHub."""
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "ghp_fake_token")
    monkeypatch.setattr(settings, "CUSTOMERS_GITHUB_REPO", "casa-owner/casa-private-data")
    monkeypatch.setattr(customer_memory, "sync_to_github", REAL_SYNC)
    pushed = []

    async def fake_github(self, request):
        assert request.url.host == "api.github.com"
        if request.method == "PUT":
            pushed.append(json.loads(base64.b64decode(json.loads(request.content)["content"])))
        return httpx.Response(404 if request.method == "GET" else 201)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_github)
    return pushed


# --- Đồng bộ GitHub: một lần mỗi tin nhắn ---


def test_each_message_pushes_customers_to_github_once(bot, github):
    bot.say("Bé nhà mình 3 tuổi ạ", extracted={"kid_age": "3 tuổi"})

    assert len(github) == 1
    snapshot = github[0][CUSTOMER_ID]
    assert snapshot["kid_age"] == "3 tuổi"
    assert [m["content"] for m in snapshot["conversation_history"]] == ["Bé nhà mình 3 tuổi ạ", MODEL_TEXT]

    bot.say("Cô chủ nhiệm lớp Mầm tên gì ạ?", reply="", escalate=True)
    bot.say("Dạ vâng ạ")

    assert len(github) == 3


def test_profile_and_history_writes_stay_local(github):
    asyncio.run(customer_memory.update_profile(CUSTOMER_ID, {"kid_age": "3 tuổi"}))
    asyncio.run(customer_memory.append_to_history(CUSTOMER_ID, "user", "Bé nhà mình 3 tuổi ạ"))

    assert github == []
    saved = json.loads(Path(customer_memory.CUSTOMERS_PATH).read_text(encoding="utf-8"))
    assert saved[CUSTOMER_ID]["kid_age"] == "3 tuổi"
    assert saved[CUSTOMER_ID]["conversation_history"][0]["content"] == "Bé nhà mình 3 tuổi ạ"


def test_github_down_does_not_break_reply(monkeypatch, bot, github):
    async def github_down(self, request):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", github_down)

    assert asyncio.run(customer_memory.sync_to_github()) is False

    bot.say("Bé nhà mình 3 tuổi ạ", extracted={"kid_age": "3 tuổi"})

    assert bot.sent == [MODEL_TEXT]
    assert customer_memory.get_profile(CUSTOMER_ID)["kid_age"] == "3 tuổi"

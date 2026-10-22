"""POST /customers/{customer_id}/reset: người vận hành thử lại như phụ huynh mới với cùng tài khoản Facebook.

Reset quên hết hồ sơ của đúng một phụ huynh (hồ sơ, lịch sử, tóm tắt, thẻ lead, follow-up) cùng các escalation
đang chờ của họ, lưu đĩa và đẩy lên CUSTOMERS_GITHUB_REPO; tin tiếp theo của họ là tin đầu tiên.
"""

import asyncio
import base64
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import customer_memory, escalation
from app.ai_engine import AIProvider
from app.config import settings

client = TestClient(main.app)
REAL_SYNC = customer_memory.sync_to_github

SECRET = "s3cret-reset"
OPERATOR = "9000000000000501"
OTHER = "9000000000000502"
PHONE = "0900000501"
REPLY = "Dạ Casa chào Ba/Mẹ ạ, bé nhà mình năm nay mấy tuổi ạ?"


class Recorder(AIProvider):
    """Model giả: ghi lại mỗi lời gọi trả lời (không phải trích xuất hồ sơ)."""

    def __init__(self):
        self.chats = []

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024):
        if system_prompt.startswith("Bạn là hệ thống trích xuất"):
            return "{}"
        self.chats.append({"user_message": user_message, "history": list(conversation_history or [])})
        return REPLY


@pytest.fixture
def model(monkeypatch):
    async def nothing(*args, **kwargs):
        return {}

    recorder = Recorder()
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", SECRET)
    monkeypatch.setattr(main, "send_message", nothing)
    monkeypatch.setattr(main, "send_typing_indicator", nothing)
    monkeypatch.setattr(main, "get_user_profile", nothing)
    monkeypatch.setattr(customer_memory, "sync_to_github", nothing)
    monkeypatch.setattr(settings, "AI_MODEL_ORDER", ["openai"])
    monkeypatch.setattr(main.ai_engine, "_providers", {"openai": recorder})
    return recorder


@pytest.fixture
def synced(monkeypatch):
    calls = []

    async def fake_sync():
        calls.append(dict(customer_memory.get_all_profiles()))
        return True

    monkeypatch.setattr(customer_memory, "sync_to_github", fake_sync)
    return calls


def seed_old_test_account(customer_id: str) -> dict:
    """Hồ sơ như tài khoản thử của người vận hành: khách cũ 6 tháng, có lịch sử, tóm tắt, thẻ lead, follow-up."""
    six_months_ago = (datetime.now() - timedelta(days=180)).isoformat()
    return customer_memory.set_fields(
        customer_id,
        {
            "kid_age": "3 tuổi",
            "phone": PHONE,
            "first_seen": six_months_ago,
            "last_seen": six_months_ago,
            "message_count": 12,
            "conversation_history": [
                {"role": "user", "content": "Học phí bao nhiêu ạ?", "timestamp": six_months_ago},
                {"role": "assistant", "content": "Dạ em chuyển tư vấn viên ạ", "timestamp": six_months_ago},
            ],
            "session_summaries": [{"date": "2026-04-20", "summary": "Hỏi học phí, được chuyển tư vấn viên"}],
            escalation.LEAD_CARD_FIELD: 8123,
            "followup_sent_at": six_months_ago,
            "staff_replied_at": six_months_ago,
        },
    )


def reset(customer_id: str, secret: str | None = SECRET):
    params = {} if secret is None else {"secret": secret}
    return client.post(f"/customers/{customer_id}/reset", params=params)


def test_next_message_after_reset_is_a_first_message(model):
    seed_old_test_account(OPERATOR)
    asyncio.run(main.process_message(OPERATOR, "Cho em hỏi về trường ạ"))
    before = model.chats[-1]
    assert len(before["history"]) == 2
    assert "[FIRST_MESSAGE]" not in before["user_message"]
    assert "phụ huynh CŨ quay lại sau khoảng 6 tháng trước" in before["user_message"]

    resp = reset(OPERATOR)

    assert resp.status_code == 200
    assert resp.json() == {"status": "reset", "existed": True}
    assert customer_memory.get_profile(OPERATOR) == {}
    assert customer_memory.get_conversation_history(OPERATOR) == []
    assert customer_memory.get_session_summaries(OPERATOR) == []
    assert OPERATOR not in json.loads(Path(customer_memory.CUSTOMERS_PATH).read_text(encoding="utf-8"))

    asyncio.run(main.process_message(OPERATOR, "Cho em hỏi về trường ạ"))
    after = model.chats[-1]
    assert after["history"] == []
    # Không còn khối hồ sơ/tóm tắt nào đứng trước câu của phụ huynh.
    assert after["user_message"].startswith("[Phụ huynh hỏi]: [FIRST_MESSAGE] Cho em hỏi về trường ạ\n")
    assert "TIN NHẮN ĐẦU TIÊN của phụ huynh (khách mới)" in after["user_message"]
    assert PHONE not in after["user_message"]
    profile = customer_memory.get_profile(OPERATOR)
    assert profile["message_count"] == 1
    assert escalation.LEAD_CARD_FIELD not in profile
    assert "followup_sent_at" not in profile
    assert [m["content"] for m in profile["conversation_history"]] == ["Cho em hỏi về trường ạ", REPLY]


def test_reset_leaves_other_customers_untouched(model, synced):
    seed_old_test_account(OPERATOR)
    other = seed_old_test_account(OTHER)

    assert reset(OPERATOR).json() == {"status": "reset", "existed": True}

    assert customer_memory.get_profile(OTHER) == other
    assert json.loads(Path(customer_memory.CUSTOMERS_PATH).read_text(encoding="utf-8")) == {OTHER: other}
    assert synced == [{OTHER: other}]


def test_reset_drops_only_that_customers_pending_escalations(model):
    seed_old_test_account(OPERATOR)
    escalation._pending.update(
        {
            7001: {"customer_id": OPERATOR, "customer_name": "Thử", "question": "Học phí?", "timestamp": "x"},
            7002: {"customer_id": OTHER, "customer_name": "Khác", "question": "Xe đưa đón?", "timestamp": "x"},
            7003: {"customer_id": OPERATOR, "customer_name": "Thử", "question": "Giáo viên?", "timestamp": "x"},
        }
    )

    reset(OPERATOR)

    assert escalation.get_pending_escalation(7001) is None
    assert escalation.get_pending_escalation(7003) is None
    assert escalation.get_pending_escalation(7002)["customer_id"] == OTHER
    on_disk = json.loads(Path(escalation.PENDING_ESCALATIONS_PATH).read_text(encoding="utf-8"))
    assert list(on_disk) == ["7002"]


def test_reset_of_unknown_customer_is_not_an_error(model, synced):
    other = seed_old_test_account(OTHER)

    resp = reset("9000000000000599")

    assert resp.status_code == 200
    assert resp.json() == {"status": "reset", "existed": False}
    assert customer_memory.get_all_profiles() == {OTHER: other}
    assert synced == []  # không có gì đổi thì không đẩy lên GitHub


@pytest.mark.parametrize("secret", [None, "", "sai", SECRET + " "], ids=["thiếu", "rỗng", "sai", "thừa dấu cách"])
def test_reset_without_valid_secret_keeps_profile(model, secret):
    profile = seed_old_test_account(OPERATOR)

    resp = reset(OPERATOR, secret)

    assert resp.status_code == 403
    assert customer_memory.get_profile(OPERATOR) == profile
    assert json.loads(Path(customer_memory.CUSTOMERS_PATH).read_text(encoding="utf-8")) == {OPERATOR: profile}


def test_reset_logs_id_and_result_but_no_profile_content(model, caplog):
    seed_old_test_account(OPERATOR)

    with caplog.at_level(logging.INFO):
        reset(OPERATOR)

    assert f"Reset customer {OPERATOR}: existed=True" in caplog.text
    for private in (PHONE, "3 tuổi", "Học phí", "chuyển tư vấn viên"):
        assert private not in caplog.text


def test_reset_pushes_profiles_without_that_customer_to_github(model, monkeypatch):
    seed_old_test_account(OPERATOR)
    other = seed_old_test_account(OTHER)
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

    reset(OPERATOR)

    assert pushed == [{OTHER: other}]

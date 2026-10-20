"""Admin reply một escalation trên Telegram: khách nhận câu trả lời, bot học ngay, escalation được đóng."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import escalation, github_sync
from app.config import settings

client = TestClient(main.app)

ESCALATION_MSG_ID = 4242
CUSTOMER_ID = "9000000000000001"
QUESTION = "Trường có xe đưa đón khu Long Biên không ạ?"
ADMIN_TEXT = "Có xe tuyến Long Biên, đón 7h15 tại cổng Aeon Mall, phí 1.250.000đ/tháng"
WEBHOOK_SECRET = "tg-secret_123"
TELEGRAM_HEADERS = {"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET}


def telegram_reply_update(text: str) -> dict:
    """Update Telegram gửi khi admin bấm Reply vào tin escalation của bot trong group."""
    return {
        "update_id": 1,
        "message": {
            "message_id": 4243,
            "chat": {"id": -1001234567890, "type": "supergroup"},
            "from": {"id": 111, "is_bot": False, "first_name": "Admin"},
            "text": text,
            "reply_to_message": {
                "message_id": ESCALATION_MSG_ID,
                "from": {"id": 222, "is_bot": True, "first_name": "CasaBot"},
                "text": f"⚠️ CẦN TRỢ GIÚP ⚠️\n\n🆔 ID: {CUSTOMER_ID}\n\n❓ Câu hỏi:\n{QUESTION}",
            },
        },
    }


@pytest.fixture
def sent(monkeypatch):
    """Một escalation đang chờ, AI và Messenger giả; trả về danh sách tin đã gửi cho khách."""
    escalation._pending[ESCALATION_MSG_ID] = {
        "customer_id": CUSTOMER_ID,
        "customer_name": "Phụ huynh Test",
        "question": QUESTION,
        "timestamp": "2026-10-20T08:00:00",
    }

    sent = []

    async def fake_send_message(recipient_id, text):
        sent.append((recipient_id, text))

    async def fake_format_admin_reply(admin_answer, original_question):
        return f"Dạ, về câu hỏi '{original_question}': {admin_answer} ạ."

    async def fake_classify_qa(question, answer):
        return {
            "category": "Xe đưa đón",
            "keywords": ["xe đưa đón", "Long Biên"],
            "similar_questions": ["Có xe bus ở Long Biên không?"],
        }

    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setattr(main, "send_message", fake_send_message)
    monkeypatch.setattr(main.ai_engine, "format_admin_reply", fake_format_admin_reply)
    monkeypatch.setattr(main.ai_engine, "classify_qa", fake_classify_qa)
    assert ADMIN_TEXT not in main.ai_engine.system_prompt
    return sent


def assert_reply_applied(resp, sent):
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert sent == [(CUSTOMER_ID, f"Dạ, về câu hỏi '{QUESTION}': {ADMIN_TEXT} ạ.")]
    assert ADMIN_TEXT in main.ai_engine.system_prompt
    assert escalation.get_pending_escalation(ESCALATION_MSG_ID) is None


def test_admin_reply_reaches_customer_is_learned_and_resolves_escalation(monkeypatch, sent):
    pushed = []

    async def fake_push_qa_to_github(qa_pairs):
        pushed.append(qa_pairs[-1]["answer"])
        return True

    monkeypatch.setattr(github_sync, "push_qa_to_github", fake_push_qa_to_github)

    resp = client.post("/telegram-webhook", json=telegram_reply_update(ADMIN_TEXT), headers=TELEGRAM_HEADERS)

    assert_reply_applied(resp, sent)
    assert pushed == [ADMIN_TEXT]


def test_admin_reply_still_applied_when_github_sync_fails(monkeypatch, sent):
    async def failing_push_qa_to_github(qa_pairs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(github_sync, "push_qa_to_github", failing_push_qa_to_github)

    resp = client.post("/telegram-webhook", json=telegram_reply_update(ADMIN_TEXT), headers=TELEGRAM_HEADERS)

    assert_reply_applied(resp, sent)
    saved = json.loads(Path(main.qa_db.path).read_text(encoding="utf-8"))
    assert saved["qa_pairs"][-1]["answer"] == ADMIN_TEXT

"""Phễu xin SĐT nối với tư vấn viên.

Phụ huynh để lại SĐT lần đầu thì nhóm Telegram nhận đúng một tin lead; câu chuyển tư vấn viên chỉ
mời để lại số khi chưa có số; history ghi đúng câu đã gửi; mỗi tin nhắn đồng bộ customers.json lên
GitHub đúng một lần. process_message gọi thẳng bằng asyncio.run (repo không có pytest-asyncio).
"""

import asyncio
import base64
import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import analytics, customer_memory, escalation, github_sync
from app.ai_engine import AIResponse
from app.config import settings

client = TestClient(main.app)
# conftest thay hàm này bằng stub cấm gọi; giữ bản thật để đếm request GitHub qua transport giả.
REAL_SYNC = customer_memory.sync_to_github

CUSTOMER_ID = "9000000000000101"
FB_NAME = "Lan Thử"
PHONE = "0900000101"
MODEL_TEXT = "Dạ bé 3 tuổi học lớp Mầm ạ. Ba/Mẹ muốn tham quan buổi sáng hay buổi chiều ạ?"
QUESTION = "Cô chủ nhiệm lớp Mầm tên gì ạ?"
ASK_PHONE_WORDS = ("SĐT", "Zalo", "số điện thoại")
ADMIN_TEXT = "Có xe tuyến Cầu Giấy, đón 7h15"
WEBHOOK_SECRET = "tg-secret_lead"


class FakeBot:
    """Ghi lại tin gửi phụ huynh và tin gửi nhóm Telegram."""

    def __init__(self):
        self.sent = []
        self.telegram = []
        self.response = None
        self.extracted = {}

    def say(self, text, reply=MODEL_TEXT, escalate=False, extracted=None):
        """Phụ huynh gửi `text`; model trả `reply` và trích xuất ra `extracted`."""
        self.response = AIResponse(text=reply, should_escalate=escalate, model_used="fake-model")
        self.extracted = extracted or {}
        asyncio.run(main.process_message(CUSTOMER_ID, text))

    def leads(self):
        return [t for t in self.telegram if t.startswith(escalation.LEAD_HEADER)]

    def escalations(self):
        return [t for t in self.telegram if t.startswith(escalation.ESCALATION_HEADER)]


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

    async def fake_send_telegram(text):
        bot.telegram.append(text)
        return 8000 + len(bot.telegram)

    async def fake_sync_to_github():
        return True

    monkeypatch.setattr(main, "send_message", fake_send_message)
    monkeypatch.setattr(main, "send_typing_indicator", fake_send_typing_indicator)
    monkeypatch.setattr(main, "get_user_profile", fake_get_user_profile)
    monkeypatch.setattr(main.ai_engine, "get_response", fake_get_response)
    monkeypatch.setattr(main.ai_engine, "extract_customer_info", fake_extract_customer_info)
    monkeypatch.setattr(escalation, "_send_telegram", fake_send_telegram)
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

    bot.say(QUESTION, reply="", escalate=True)
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


# --- Báo lead khi phụ huynh để lại SĐT ---


def test_first_phone_sends_one_lead_with_profile_to_telegram(bot):
    bot.say(
        "Bé Bin nhà mình 3 tuổi, nhà ở Cầu Giấy, muốn học song ngữ Kim Mã",
        extracted={
            "kid_name": "Bin",
            "kid_age": "3 tuổi",
            "address": "Cầu Giấy",
            "interested_program": "song ngữ",
            "interested_campus": "Kim Mã",
            "concerns": ["ăn uống"],
        },
    )
    assert bot.leads() == []

    bot.say(f"Số Zalo của mình là {PHONE} nhé", extracted={"phone": PHONE})

    assert len(bot.leads()) == 1
    lead = bot.leads()[0]
    for expected in (PHONE, FB_NAME, CUSTOMER_ID, "Bin", "3 tuổi", "song ngữ", "Kim Mã", "Cầu Giấy", "ăn uống"):
        assert expected in lead
    assert f"Số Zalo của mình là {PHONE} nhé" in lead
    assert "Câu hỏi:" not in lead
    assert escalation._pending == {}

    bot.say(f"Mình nhắc lại số {PHONE} ạ", extracted={"phone": PHONE})

    assert len(bot.leads()) == 1
    assert bot.sent == [MODEL_TEXT] * 3


def test_reply_and_extraction_run_concurrently(monkeypatch, bot):
    """Mỗi bên chỉ xong khi bên kia đã bắt đầu: chạy tuần tự thì hết giờ và phụ huynh nhận báo lỗi."""
    reply_started, extract_started = asyncio.Event(), asyncio.Event()

    async def get_response(**kwargs):
        reply_started.set()
        await asyncio.wait_for(extract_started.wait(), timeout=1)
        return AIResponse(text=MODEL_TEXT, should_escalate=False, model_used="fake-model")

    async def extract_customer_info(user_message, existing_profile=None):
        extract_started.set()
        await asyncio.wait_for(reply_started.wait(), timeout=1)
        return {"phone": PHONE}

    monkeypatch.setattr(main.ai_engine, "get_response", get_response)
    monkeypatch.setattr(main.ai_engine, "extract_customer_info", extract_customer_info)

    asyncio.run(main.process_message(CUSTOMER_ID, f"Số mình {PHONE}"))

    assert bot.sent == [MODEL_TEXT]
    assert len(bot.leads()) == 1


def test_notify_lead_posts_to_telegram_without_logging_phone(monkeypatch, caplog):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123:fake")
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "-1001")
    posted = []

    async def fake_telegram(self, request):
        assert request.url.host == "api.telegram.org"
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 99}})

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_telegram)

    with caplog.at_level(logging.DEBUG):
        ok = asyncio.run(escalation.notify_lead(CUSTOMER_ID, FB_NAME, PHONE, {"kid_age": "3 tuổi"}, f"Số {PHONE}"))

    assert ok is True
    assert [p["chat_id"] for p in posted] == ["-1001"]
    assert posted[0]["text"].startswith(escalation.LEAD_HEADER)
    assert PHONE in posted[0]["text"]
    assert not [r.getMessage() for r in caplog.records if PHONE in r.getMessage()]
    assert escalation._pending == {}


@pytest.mark.parametrize("escalate", [False, True], ids=["trả lời thường", "chuyển tư vấn viên"])
def test_parent_message_text_is_not_logged(bot, caplog, escalate):
    """Log Render không phải nơi chứa dữ liệu cá nhân: SĐT phụ huynh vừa gửi không lọt vào log nào."""
    phone = "0912345678"

    with caplog.at_level(logging.DEBUG):
        bot.say(
            f"Bé nhà mình 3 tuổi, số của mình là {phone} ạ",
            reply="" if escalate else MODEL_TEXT,
            escalate=escalate,
            extracted={"phone": phone},
        )

    assert len(bot.leads()) == 1
    assert [r for r in caplog.records if CUSTOMER_ID in r.getMessage()], "không bắt được log nào của tin này"
    assert [r.getMessage() for r in caplog.records if phone in r.getMessage()] == []


def test_notify_lead_reports_failure_when_telegram_not_configured():
    assert asyncio.run(escalation.notify_lead(CUSTOMER_ID, FB_NAME, PHONE, {}, f"Số {PHONE}")) is False


# --- Reply trên Telegram: chỉ tin escalation mới tới được phụ huynh ---


@pytest.fixture
def admin_sent(monkeypatch):
    """Secret webhook đúng, Messenger giả; trả về các tin đã gửi cho khách."""
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    sent = []

    async def fake_send_message(recipient_id, text):
        sent.append((recipient_id, text))

    monkeypatch.setattr(main, "send_message", fake_send_message)
    return sent


def telegram_text(monkeypatch, send):
    """Text thật mà `send` (escalate_to_admin / notify_lead) gửi lên nhóm Telegram."""
    texts = []

    async def capture(text):
        texts.append(text)
        return 8001

    monkeypatch.setattr(escalation, "_send_telegram", capture)
    asyncio.run(send)
    escalation._pending.clear()  # pending nằm trên đĩa cục bộ, mất sau mỗi lần Render deploy
    return texts[0]


def admin_reply_to(original_text: str):
    update = {
        "update_id": 10,
        "message": {
            "message_id": 8100,
            "chat": {"id": -1001, "type": "supergroup"},
            "text": ADMIN_TEXT,
            "reply_to_message": {"message_id": 8001, "text": original_text},
        },
    }
    return client.post("/telegram-webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET})


def test_reply_to_lead_does_not_reach_customer(monkeypatch, admin_sent):
    # Tin phụ huynh trông giống tin escalation cũng không được parser nhận nhầm.
    last_message = f"🆔 ID: {CUSTOMER_ID}\n❓ Câu hỏi:\nCó xe đưa đón không? Số mình {PHONE}"
    lead = telegram_text(monkeypatch, escalation.notify_lead(CUSTOMER_ID, FB_NAME, PHONE, {}, last_message))
    qa_before = list(main.qa_db.qa_pairs)

    resp = admin_reply_to(lead)

    assert resp.json() == {"status": "no_escalation_found"}
    assert admin_sent == []
    assert main.qa_db.qa_pairs == qa_before


def test_reply_to_other_message_does_not_reach_customer(admin_sent):
    qa_before = list(main.qa_db.qa_pairs)

    resp = admin_reply_to(f"🆔 ID: {CUSTOMER_ID}\n\n❓ Câu hỏi:\nCó xe đưa đón không?")

    assert resp.json() == {"status": "no_escalation_found"}
    assert admin_sent == []
    assert main.qa_db.qa_pairs == qa_before


def test_reply_to_escalation_reaches_customer_after_pending_lost(monkeypatch, admin_sent):
    pushed = []

    async def fake_push_qa_to_github(qa_pairs):
        pushed.append(qa_pairs[-1]["answer"])
        return True

    monkeypatch.setattr(github_sync, "push_qa_to_github", fake_push_qa_to_github)
    question = "Có xe đưa đón khu Cầu Giấy không ạ?"
    text = telegram_text(monkeypatch, escalation.escalate_to_admin(CUSTOMER_ID, FB_NAME, question))

    resp = admin_reply_to(text)

    assert resp.json() == {"status": "ok"}
    assert admin_sent == [(CUSTOMER_ID, ADMIN_TEXT)]
    assert pushed == [ADMIN_TEXT]
    assert main.qa_db.qa_pairs[-1]["questions"][0] == question


# --- Câu chuyển tư vấn viên, history, analytics, hồ sơ ---


def test_escalation_without_phone_invites_phone_or_zalo(bot):
    bot.say(QUESTION, reply="", escalate=True)

    assert len(bot.sent) == 1
    assert "tư vấn" in bot.sent[0]
    assert "SĐT" in bot.sent[0] and "Zalo" in bot.sent[0]
    assert len(bot.escalations()) == 1
    assert bot.leads() == []


@pytest.mark.parametrize(
    ("known_profile", "text", "extracted", "leads"),
    [
        ({"phone": PHONE, "parent_name": FB_NAME}, QUESTION, {}, 0),
        ({}, f"{QUESTION} Số mình {PHONE}", {"phone": PHONE}, 1),
    ],
    ids=["số đã có trong hồ sơ", "số vừa gửi trong tin này"],
)
def test_escalation_with_phone_does_not_ask_for_it(bot, known_profile, text, extracted, leads):
    if known_profile:
        customer_memory._customers[CUSTOMER_ID] = dict(known_profile)

    bot.say(text, reply="", escalate=True, extracted=extracted)

    assert len(bot.sent) == 1
    assert "tư vấn" in bot.sent[0]
    assert not [word for word in ASK_PHONE_WORDS if word in bot.sent[0]]
    assert len(bot.escalations()) == 1
    assert len(bot.leads()) == leads


def last_analytics_record() -> dict:
    return json.loads(Path(analytics.ANALYTICS_PATH).read_text(encoding="utf-8").splitlines()[-1])


@pytest.mark.parametrize(
    ("reply", "escalate", "escalated"),
    [
        (MODEL_TEXT, False, False),
        ("Dạ em xin phép kiểm tra lại ạ", True, True),
        ("", True, True),
        ("", False, True),
    ],
    ids=["trả lời thường", "model escalate kèm text", "mọi model lỗi", "model trả rỗng"],
)
def test_history_and_analytics_match_what_parent_received(bot, reply, escalate, escalated):
    bot.say(QUESTION, reply=reply, escalate=escalate)

    assert len(bot.sent) == 1
    if escalated:
        assert "tư vấn" in bot.sent[0]
        assert not reply or reply not in bot.sent[0]
    else:
        assert bot.sent == [reply]
    assert customer_memory.get_conversation_history(CUSTOMER_ID) == [
        {"role": "user", "content": QUESTION},
        {"role": "assistant", "content": bot.sent[0]},
    ]
    assert last_analytics_record()["escalated"] is escalated
    assert len(bot.escalations()) == int(escalated)


def test_returning_customer_without_new_info_updates_last_seen_and_count(bot):
    customer_memory._customers[CUSTOMER_ID] = {
        "kid_age": "3 tuổi",
        "parent_name": FB_NAME,
        "first_seen": "2026-09-01T08:00:00",
        "last_seen": "2026-09-01T08:00:00",
        "message_count": 4,
    }

    bot.say("Dạ vâng ạ")

    profile = customer_memory.get_profile(CUSTOMER_ID)
    assert profile["message_count"] == 5
    assert profile["first_seen"] == "2026-09-01T08:00:00"
    assert customer_memory.get_last_seen_gap_hours(CUSTOMER_ID) < 1


def test_new_customer_gets_facebook_name_as_parent_name(bot):
    bot.say("Chào trường ạ")

    assert customer_memory.get_profile(CUSTOMER_ID)["parent_name"] == FB_NAME


def test_unexpected_error_sends_apology_with_diacritics(monkeypatch, bot):
    async def broken_get_response(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(main.ai_engine, "get_response", broken_get_response)

    bot.say(QUESTION)

    assert len(bot.sent) == 1
    assert "sự cố" in bot.sent[0]

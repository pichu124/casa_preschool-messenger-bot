"""Trải nghiệm Messenger: sự kiện vào /webhook (tin thường, nút trả lời nhanh, nút gửi SĐT, postback Get Started
và câu hỏi gợi ý, referral từ quảng cáo), nút trả lời nhanh và ảnh tĩnh khi bot trả lời, cài messenger profile.

process_message gọi bằng asyncio.run hoặc qua TestClient (BackgroundTasks chạy xong trước khi post() trả về).
Messenger, model, Telegram và GitHub giả; tên được import trong app.main thì patch trên app.main.
"""

import asyncio
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import ai_engine, customer_memory, escalation, messenger
from app.ai_engine import SYSTEM_PROMPT, AIEngine, AIProvider, AIResponse
from app.config import settings
from app.main import InboundEvent, StaffReply, parse_messaging_event
from app.messenger import QUICK_REPLIES, build_quick_replies, set_messenger_profile

client = TestClient(main.app)

SENDER = "9000000000000501"
PAGE_ID = "9000000000000500"
FB_NAME = "Lan Thử"
PHONE = "0911222501"
PHONE_FROM_FB = "+84911222501"
PAGE_TOKEN = "EAAB-page-token-test"
WEBHOOK_SECRET = "tg-secret_webhook"
BASE_URL = "https://casa.example/"
AD_ID = "6045246247433"
AD_TITLE = "Học thử 1 tuần miễn phí"
TIMESTAMP = 1760000000123
MODEL_TEXT = "Dạ Casa có chương trình cho các con từ 15 tháng đến 6 tuổi ạ. Bé nhà mình được mấy tuổi ạ?"
ASK_PHONE = "Dạ Ba/Mẹ cho em xin SĐT hoặc Zalo để tư vấn viên gửi chi tiết nhé ạ? [QUICK:phone]"
# Nguyên văn 4 câu gợi ý của trường (phản hồi đợt 3).
ICE_BREAKERS = {
    "IB_1": "Học phí của trường là bao nhiêu?",
    "IB_2": "Trường nhận bé từ bao nhiêu tháng?",
    "IB_3": "Hiện tại Nhà trường có ưu đãi gì?",
    "IB_4": "Có chương trình học thử miễn phí cho học sinh mới không?",
}
AD_REFERRAL = {
    "ref": "hoc-thu",
    "ad_id": AD_ID,
    "source": "ADS",
    "type": "OPEN_THREAD",
    "ads_context_data": {"ad_title": AD_TITLE, "photo_url": "https://example.com/ad.jpg", "post_id": "1_2"},
}
AD_ATTRIBUTION = {"lead_source": "ads", "ad_id": AD_ID, "ad_title": AD_TITLE, "ref": "hoc-thu"}


def message_event(**message) -> dict:
    return {
        "sender": {"id": SENDER},
        "recipient": {"id": PAGE_ID},
        "timestamp": TIMESTAMP,
        "message": {"mid": "m_text", **message},
    }


def postback_event(payload, title="Bắt đầu", **postback) -> dict:
    return {
        "sender": {"id": SENDER},
        "recipient": {"id": PAGE_ID},
        "timestamp": TIMESTAMP,
        "postback": {"title": title, "payload": payload, **postback},
    }


def referral_event(referral) -> dict:
    return {"sender": {"id": SENDER}, "recipient": {"id": PAGE_ID}, "timestamp": TIMESTAMP, "referral": referral}


def echo_event(metadata=None, mid="m_echo", **event) -> dict:
    """Tin Page gửi phụ huynh, Facebook gửi lại (message_echoes): sender là Page, recipient là phụ huynh."""
    message = {"is_echo": True, "app_id": 263902037430900, "mid": mid, "text": "Dạ chị gọi lại cho mình ngay ạ"}
    if metadata is not None:
        message["metadata"] = metadata
    return {"sender": {"id": PAGE_ID}, "recipient": {"id": SENDER}, "timestamp": TIMESTAMP, "message": message, **event}


def inbound(text, dedup_key="m_text", attribution=None, phone_from_qr=None) -> InboundEvent:
    return InboundEvent(
        sender_id=SENDER,
        text=text,
        dedup_key=dedup_key,
        attribution=attribution or {},
        phone_from_qr=phone_from_qr,
    )


# --- parse_messaging_event: hàm thuần ---


def test_plain_text_message():
    assert parse_messaging_event(message_event(text="Học phí bao nhiêu ạ?")) == inbound("Học phí bao nhiêu ạ?")


@pytest.mark.parametrize(
    "event",
    [
        echo_event(metadata="casa-bot"),
        echo_event(recipient={}),
        message_event(attachments=[{"type": "image", "payload": {"url": "https://example.com/a.jpg"}}]),
        {"sender": {"id": SENDER}, "recipient": {"id": PAGE_ID}, "delivery": {"mids": ["m_1"]}},
        {"sender": {"id": SENDER}, "recipient": {"id": PAGE_ID}, "read": {"watermark": TIMESTAMP}},
        {"recipient": {"id": PAGE_ID}, "message": {"mid": "m_text", "text": "Không có người gửi"}},
        postback_event("PAYLOAD_LA", title=""),
        referral_event({"source": "DISCOVER_TAB", "type": "OPEN_THREAD"}),
    ],
    ids=[
        "echo của bot",
        "echo không có người nhận",
        "chỉ có ảnh",
        "delivery",
        "read",
        "không có sender",
        "postback lạ không title",
        "referral không nguồn",
    ],
)
def test_events_without_anything_to_answer_or_record_are_ignored(event):
    assert parse_messaging_event(event) is None


# TIMESTAMP (1760000000123 ms) theo UTC
STAFF_REPLIED_AT = "2025-10-09T08:53:20.123000+00:00"


@pytest.mark.parametrize("metadata", [None, "", "cong-cu-khac"], ids=["không metadata", "metadata rỗng", "metadata lạ"])
def test_echo_not_sent_by_the_bot_is_a_staff_reply_to_the_recipient(metadata):
    assert parse_messaging_event(echo_event(metadata)) == StaffReply(SENDER, "m_echo", STAFF_REPLIED_AT)


def test_staff_echo_without_timestamp_is_dated_now_in_utc():
    event = echo_event()
    del event["timestamp"]

    replied_at = datetime.fromisoformat(parse_messaging_event(event).replied_at)

    assert replied_at.utcoffset() == timedelta(0)
    assert abs(datetime.now(timezone.utc) - replied_at) < timedelta(minutes=1)


@pytest.mark.parametrize(
    ("key", "index"),
    [(key, i) for key, buttons in QUICK_REPLIES.items() for i in range(len(buttons))],
)
def test_text_quick_reply_becomes_its_meaning(key, index):
    title, meaning = QUICK_REPLIES[key][index]
    button = build_quick_replies(key)[index]
    assert button["title"] == title

    event = message_event(text=title, quick_reply={"payload": button["payload"]})

    assert parse_messaging_event(event) == inbound(meaning)


# Nút tin đầu và nút tuổi theo phản hồi đợt 3 của trường: (key, nhãn nút, câu bot nhận khi phụ huynh bấm).
SCHOOL_BUTTONS = [
    ("topics", "Cơ sở quan tâm", "Trường có những cơ sở nào ạ?"),
    ("topics", "Chương trình học", "Trường dạy chương trình gì ạ?"),
    ("topics", "Đặt lịch tham quan", "Em muốn đặt lịch tham quan trường ạ"),
    ("topics", "Ưu đãi", "Hiện tại Nhà trường có ưu đãi gì ạ?"),
    ("age", "Dưới 2 tuổi", "Bé nhà em dưới 2 tuổi ạ"),
    ("age", "2-3 tuổi", "Bé nhà em 2-3 tuổi ạ"),
    ("age", "3-5 tuổi", "Bé nhà em 3-5 tuổi ạ"),
    ("age", "5-6 tuổi", "Bé nhà em 5-6 tuổi ạ"),
]


@pytest.mark.parametrize("key", ["topics", "age"])
def test_first_message_and_age_buttons_are_the_school_labels(key):
    titles = [button["title"] for button in build_quick_replies(key)]

    assert titles == [title for k, title, _ in SCHOOL_BUTTONS if k == key]


@pytest.mark.parametrize(("key", "title", "meaning"), SCHOOL_BUTTONS)
def test_school_button_tap_reaches_the_bot_as_a_clear_question(key, title, meaning):
    button = next(b for b in build_quick_replies(key) if b["title"] == title)

    event = message_event(text=title, quick_reply={"payload": button["payload"]})

    assert parse_messaging_event(event) == inbound(meaning)


# Người vận hành 2026-10-22: lời mời học thử/tham quan hiện nút đồng ý / tìm hiểu thêm; chỉ khi phụ huynh đồng ý
# bot mới hỏi tuần (trial_week) hay buổi (visit_time).
INVITE_BUTTONS = [
    ("trial_invite", "Đăng ký học thử", "Em muốn đăng ký cho bé học thử 1 tuần ạ"),
    ("trial_invite", "Tìm hiểu thêm", "Em muốn tìm hiểu thêm trước ạ"),
    ("visit_invite", "Đặt lịch tham quan", "Em muốn đặt lịch tham quan trường ạ"),
    ("visit_invite", "Tìm hiểu thêm", "Em muốn tìm hiểu thêm trước ạ"),
]


@pytest.mark.parametrize("key", ["trial_invite", "visit_invite"])
def test_invite_buttons_are_the_operator_labels(key):
    assert QUICK_REPLIES[key] == [(title, meaning) for k, title, meaning in INVITE_BUTTONS if k == key]


@pytest.mark.parametrize(
    ("payload", "meaning"),
    [
        ("QR:trial_invite:0", "Em muốn đăng ký cho bé học thử 1 tuần ạ"),
        ("QR:trial_invite:1", "Em muốn tìm hiểu thêm trước ạ"),
        ("QR:visit_invite:0", "Em muốn đặt lịch tham quan trường ạ"),
        ("QR:visit_invite:1", "Em muốn tìm hiểu thêm trước ạ"),
    ],
)
def test_invite_button_tap_reaches_the_bot_as_its_meaning(payload, meaning):
    assert parse_messaging_event(message_event(text="Bấm nút", quick_reply={"payload": payload})) == inbound(meaning)


def test_visit_time_button_says_it_is_about_a_visit():
    event = message_event(text="Buổi sáng", quick_reply={"payload": build_quick_replies("visit_time")[0]["payload"]})

    assert parse_messaging_event(event).text == "Em muốn hẹn tham quan buổi sáng ạ"


@pytest.mark.parametrize("payload", ["QR:visit_time:9", "QR:khong-co:0", "QR:age:x", "QR:age:²", "QR:phone:0", "KHAC"])
def test_unknown_quick_reply_payload_keeps_the_button_title(payload):
    event = message_event(text="Buổi sáng", quick_reply={"payload": payload})

    assert parse_messaging_event(event) == inbound("Buổi sáng")


@pytest.mark.parametrize("phone", [PHONE_FROM_FB, "912345678", "+1 650 555 1234"])
def test_phone_quick_reply_gives_phone_and_keeps_text(phone):
    event = message_event(text=phone, quick_reply={"payload": phone})

    assert parse_messaging_event(event) == inbound(phone, phone_from_qr=phone)


def test_get_started_postback_becomes_a_greeting():
    event = postback_event("GET_STARTED", title="Get Started", mid="m_pb")

    assert parse_messaging_event(event) == inbound("Xin chào Casa ạ", dedup_key="m_pb")


@pytest.mark.parametrize(("payload", "question"), ICE_BREAKERS.items())
def test_ice_breaker_postback_becomes_its_question(payload, question):
    assert parse_messaging_event(postback_event(payload, title=question)) == inbound(
        question, dedup_key=f"pb:{SENDER}:{TIMESTAMP}"
    )


def test_unknown_postback_payload_uses_its_title():
    event = postback_event("MENU_HOC_PHI", title="Học phí")

    assert parse_messaging_event(event) == inbound("Học phí", dedup_key=f"pb:{SENDER}:{TIMESTAMP}")


@pytest.mark.parametrize(
    ("event", "expected"),
    [
        (referral_event(AD_REFERRAL), inbound(None, dedup_key="", attribution=AD_ATTRIBUTION)),
        (
            message_event(text="Cho em hỏi học phí", referral=AD_REFERRAL),
            inbound("Cho em hỏi học phí", attribution=AD_ATTRIBUTION),
        ),
        (
            postback_event("GET_STARTED", mid="m_pb", referral={"ref": "bio", "source": "SHORTLINK", "type": "OPEN_THREAD"}),
            inbound("Xin chào Casa ạ", dedup_key="m_pb", attribution={"lead_source": "link", "ref": "bio"}),
        ),
        (
            referral_event({"source": "ADS", "type": "OPEN_THREAD", "ad_id": AD_ID, "ref": "", "ads_context_data": {}}),
            inbound(None, dedup_key="", attribution={"lead_source": "ads", "ad_id": AD_ID}),
        ),
        (
            referral_event({"source": "CUSTOMER_CHAT_PLUGIN", "type": "OPEN_THREAD", "ref": "web"}),
            inbound(None, dedup_key="", attribution={"ref": "web"}),
        ),
    ],
    ids=["event.referral", "message.referral", "postback.referral", "bỏ giá trị rỗng", "nguồn khác: không ghi organic"],
)
def test_referral_attribution(event, expected):
    assert parse_messaging_event(event) == expected


# --- /webhook ---


class Bot:
    """Messenger, model, Telegram và GitHub giả; ghi lại mọi thứ bot gửi đi."""

    def __init__(self):
        self.sent = []  # (loại, nội dung, quick_replies)
        self.telegram = []
        self.response = AIResponse(text=MODEL_TEXT, should_escalate=False, model_used="fake-model")
        self.extracted = {}
        self.contexts = []
        self.last_bot_messages = []
        self.synced = 0

    def say(self, text, reply=MODEL_TEXT, escalate=False, extracted=None):
        self.response = AIResponse(text=reply, should_escalate=escalate, model_used="fake-model")
        self.extracted = extracted or {}
        asyncio.run(main.process_message(SENDER, text))

    def leads(self):
        return [t for t in self.telegram if t.startswith(escalation.LEAD_HEADER)]


@pytest.fixture
def bot(monkeypatch):
    bot = Bot()

    async def send_message(recipient_id, text, quick_replies=None):
        assert recipient_id == SENDER
        bot.sent.append(("text", text, quick_replies))

    async def send_image(recipient_id, image_url, quick_replies=None):
        assert recipient_id == SENDER
        bot.sent.append(("image", image_url, quick_replies))

    async def send_typing_indicator(recipient_id, action="typing_on"):
        pass

    async def get_user_profile(user_id):
        first_name, last_name = FB_NAME.split()
        return {"first_name": first_name, "last_name": last_name}

    async def get_response(user_message, conversation_history=None, customer_context="", gap_hours=0.0):
        bot.contexts.append(customer_context)
        return bot.response

    async def extract_customer_info(user_message, existing_profile=None, last_bot_message=""):
        bot.last_bot_messages.append(last_bot_message)
        return dict(bot.extracted)

    async def send_telegram(text):
        bot.telegram.append(text)
        return 8000 + len(bot.telegram)

    async def sync_to_github():
        bot.synced += 1
        return True

    monkeypatch.setattr(settings, "FB_APP_SECRET", "")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", BASE_URL)
    monkeypatch.setattr(main, "send_message", send_message)
    monkeypatch.setattr(main, "send_image", send_image)
    monkeypatch.setattr(main, "send_typing_indicator", send_typing_indicator)
    monkeypatch.setattr(main, "get_user_profile", get_user_profile)
    monkeypatch.setattr(main.ai_engine, "get_response", get_response)
    monkeypatch.setattr(main.ai_engine, "extract_customer_info", extract_customer_info)
    monkeypatch.setattr(escalation, "_send_telegram", send_telegram)
    monkeypatch.setattr(customer_memory, "sync_to_github", sync_to_github)
    return bot


def post_webhook(*events):
    resp = client.post("/webhook", json={"object": "page", "entry": [{"id": PAGE_ID, "messaging": list(events)}]})
    assert resp.status_code == 200
    return resp


def test_referral_only_event_records_source_without_reply_or_message_count(bot):
    customer_memory._customers[SENDER] = {"kid_age": "3 tuổi", "message_count": 3, "last_seen": "2026-10-01T08:00:00"}

    post_webhook(referral_event(AD_REFERRAL))

    assert bot.sent == []
    profile = customer_memory.get_profile(SENDER)
    assert {k: profile.get(k) for k in AD_ATTRIBUTION} == AD_ATTRIBUTION
    assert (profile["kid_age"], profile["message_count"], profile["last_seen"]) == ("3 tuổi", 3, "2026-10-01T08:00:00")
    assert "conversation_history" not in profile
    assert bot.synced == 1


def test_message_from_ad_reaches_prompt_as_ad_source(bot):
    post_webhook(message_event(text="Cho em hỏi học phí", referral=AD_REFERRAL))

    assert bot.contexts and f'Nguồn: quảng cáo "{AD_TITLE}"' in bot.contexts[0]
    profile = customer_memory.get_profile(SENDER)
    assert (profile["lead_source"], profile["ad_title"], profile["message_count"]) == ("ads", AD_TITLE, 1)
    assert [m["content"] for m in customer_memory.get_conversation_history(SENDER)] == ["Cho em hỏi học phí", MODEL_TEXT]


def test_quick_reply_button_reaches_model_as_its_meaning(bot):
    payload = build_quick_replies("visit_time")[1]["payload"]

    post_webhook(message_event(text="Buổi chiều", quick_reply={"payload": payload}))

    assert customer_memory.get_conversation_history(SENDER)[0]["content"] == "Em muốn hẹn tham quan buổi chiều ạ"


def test_get_started_is_answered_once_with_a_greeting(bot):
    post_webhook(postback_event("GET_STARTED"), postback_event("GET_STARTED"))

    assert bot.sent == [("text", MODEL_TEXT, None)]
    assert customer_memory.get_conversation_history(SENDER)[0]["content"] == "Xin chào Casa ạ"


def test_staff_echo_records_staff_reply_without_answering(bot):
    history = [{"role": "user", "content": "Học phí bao nhiêu ạ?", "timestamp": "2025-10-09T08:00:00"}]
    customer_memory._customers[SENDER] = {"kid_age": "3 tuổi", "message_count": 1, "conversation_history": history}

    post_webhook(echo_event(), echo_event())

    assert bot.sent == []
    assert customer_memory.get_profile(SENDER) == {
        "kid_age": "3 tuổi",
        "message_count": 1,
        "conversation_history": history,
        "staff_replied_at": STAFF_REPLIED_AT,
    }
    assert bot.synced == 1


def test_echo_of_the_bot_own_message_changes_nothing(bot):
    customer_memory._customers[SENDER] = {"kid_age": "3 tuổi", "message_count": 1}

    post_webhook(echo_event(metadata="casa-bot"))

    assert bot.sent == []
    assert customer_memory.get_profile(SENDER) == {"kid_age": "3 tuổi", "message_count": 1}
    assert bot.synced == 0


def test_phone_quick_reply_saves_phone_and_sends_lead_without_logging_it(bot, caplog):
    with caplog.at_level(logging.DEBUG):
        post_webhook(message_event(text=PHONE_FROM_FB, quick_reply={"payload": PHONE_FROM_FB}))

    assert customer_memory.get_profile(SENDER)["phone"] == PHONE_FROM_FB
    assert len(bot.leads()) == 1 and PHONE_FROM_FB in bot.leads()[0]
    assert [r for r in caplog.records if SENDER in r.getMessage()], "không bắt được log nào của tin này"
    assert [r.getMessage() for r in caplog.records if PHONE[1:] in r.getMessage()] == []


def test_phone_quick_reply_wins_over_the_extracted_phone(bot):
    bot.extracted = {"phone": "0987654321"}

    post_webhook(message_event(text=PHONE_FROM_FB, quick_reply={"payload": PHONE_FROM_FB}))

    assert customer_memory.get_profile(SENDER)["phone"] == PHONE_FROM_FB


# --- Nút trả lời nhanh và ảnh tĩnh trong câu trả lời ---


def test_reply_tokens_become_absolute_image_and_quick_replies_on_last_message(bot):
    reply = f"{MODEL_TEXT} [IMAGES:static/thuc-don.jpg,https://cdn.example/b.jpg][QUICK:age]"

    bot.say("Cho em xem thực đơn", reply=reply)

    assert bot.sent == [
        ("text", MODEL_TEXT, None),
        ("image", "https://casa.example/static/thuc-don.jpg", None),
        ("image", "https://cdn.example/b.jpg", build_quick_replies("age")),
    ]
    assert customer_memory.get_conversation_history(SENDER)[-1]["content"] == reply


def test_quick_replies_go_on_the_text_when_there_is_no_image(bot):
    bot.say("Trường có dạy tiếng Anh không", reply=f"{MODEL_TEXT} [QUICK:visit_time]")

    assert bot.sent == [("text", MODEL_TEXT, build_quick_replies("visit_time"))]


def test_trial_invite_token_reaches_messenger_as_register_and_learn_more_buttons(bot, graph, monkeypatch):
    monkeypatch.setattr(main, "send_message", messenger.send_message)
    invite = "Casa tặng bé 1 tuần học thử miễn phí, Ba/Mẹ có muốn cho con thử không ạ?"

    bot.say("Con em nhút nhát lắm", reply=f"{invite} [QUICK:trial_invite]")

    assert [body["message"] for path, _, body in graph if path.endswith("/me/messages")] == [
        {
            "text": invite,
            "metadata": "casa-bot",
            "quick_replies": [
                {"content_type": "text", "title": "Đăng ký học thử", "payload": "QR:trial_invite:0"},
                {"content_type": "text", "title": "Tìm hiểu thêm", "payload": "QR:trial_invite:1"},
            ],
        }
    ]


def test_unknown_quick_key_is_dropped_without_buttons(bot):
    bot.say("Trường có dạy tiếng Anh không", reply=f"{MODEL_TEXT} [QUICK:ngay_sinh]")

    assert bot.sent == [("text", MODEL_TEXT, None)]


def test_escalation_reply_has_no_quick_replies(bot):
    bot.say("Cô chủ nhiệm tên gì ạ?", reply="Dạ em kiểm tra lại ạ [QUICK:age]", escalate=True)

    assert len(bot.sent) == 1
    kind, text, quick_replies = bot.sent[0]
    assert (kind, quick_replies) == ("text", None)
    assert "tư vấn" in text and "[QUICK" not in text


# --- Trích xuất: ép kiểu và ngữ cảnh ---


@pytest.mark.parametrize("declined", ["false", "true", 1, False])
def test_phone_declined_is_kept_only_when_json_true(bot, declined):
    bot.say("Cô chủ nhiệm tên gì ạ?", reply="", escalate=True, extracted={"phone_declined": declined})

    assert "phone_declined" not in customer_memory.get_profile(SENDER)
    assert "SĐT" in bot.sent[0][1]


def test_phone_declined_true_is_kept(bot):
    bot.say("Mình chưa muốn để số", extracted={"phone_declined": True})

    assert customer_memory.get_profile(SENDER)["phone_declined"] is True


@pytest.mark.parametrize(
    "phone",
    [
        "không có",
        "chưa có",
        "123",
        "091234",
        "+84 911 222 501 999",
        "0912345678 123",
        "0912 345 67",
        "212345678",
        "12345678",
        "+1 234 567",
        "+1 2345 6789 0123 4567",
        "1 912 345 678",
    ],
)
def test_phone_without_9_to_11_digits_is_not_saved(bot, phone):
    bot.say("Cô chủ nhiệm tên gì ạ?", reply="", escalate=True, extracted={"phone": phone, "kid_age": "3 tuổi"})

    profile = customer_memory.get_profile(SENDER)
    assert "phone" not in profile and profile["kid_age"] == "3 tuổi"
    assert bot.leads() == []
    assert "SĐT" in bot.sent[0][1]


@pytest.mark.parametrize("phone", [PHONE, "0911 222 501", "+84 911 222 501", "024 3333 4444"])
def test_phone_with_9_to_11_digits_is_saved(bot, phone):
    bot.say(f"Số mình {phone}", extracted={"phone": phone})

    assert customer_memory.get_profile(SENDER)["phone"] == phone
    assert len(bot.leads()) == 1


@pytest.mark.parametrize(
    ("phone", "saved"),
    [
        ("0912345678, 0987654321", "0912345678"),
        ("0912345678 0987654321", "0912345678"),
        ("0912345678 hoặc 0987654321", "0912345678"),
        ("+84 0912345678", "+84 0912345678"),
        ("+84 24 3123 4567", "+84 24 3123 4567"),
        ("(024) 3123 4567", "024 3123 4567"),
        ("(+84) 912 345 678", "+84 912 345 678"),
        ("Zalo 0912.345.678 ạ", "0912.345.678"),
        ("912 345 678", "0912345678"),
        ("912345678", "0912345678"),
        ("Zalo 912.345.678 ạ", "0912345678"),
        ("0912 - 345 - 678", "0912 - 345 - 678"),
        ("0912  345  678", "0912  345  678"),
        ("(0912) 345 678", "0912 345 678"),
        ("+1 650 555 1234", "+1 650 555 1234"),
        ("+44 20 7946 0958, 0912345678", "+44 20 7946 0958"),
        ("+86 138 0013 8000", "+86 138 0013 8000"),
        ("+33 6 12 34 56 78", "+33 6 12 34 56 78"),
        ("+33 1 23 45 67 89", "+33 1 23 45 67 89"),
        ("+41 79 123 45 67", "+41 79 123 45 67"),
        ("+45 12 34 56 78", "+45 12 34 56 78"),
        ("+32 470 12 34 56", "+32 470 12 34 56"),
        ("+886 0912 345 678", "+886 0912 345 678"),
        ("+66 081 234 5678", "+66 081 234 5678"),
        ("+39 0331 123456", "+39 0331 123456"),
        ("+44 020 7946 0958", "+44 020 7946 0958"),
        ("0912345678 2 bé", "0912345678"),
        ("0912345678 3 tuổi", "0912345678"),
        ("098 765 4321 9", "098 765 4321"),
        # A foreign number keeps its whole run: a stray number after one in the extracted phone is very rare
        ("+65 9123 4567 2 bé", "+65 9123 4567 2"),
        ("+65 9123 4567 0912345678", "+65 9123 4567"),
        ("+1 234 0912345678", "0912345678"),
        ("1. 0912345678", "0912345678"),
        ("bé 3 0912345678", "0912345678"),
        ("Tầng 12 - 0912345678", "0912345678"),
        ("0912345678 123 0987654321", "0987654321"),
    ],
)
def test_first_phone_number_in_the_extracted_phone_is_saved_and_sent_as_lead(bot, caplog, phone, saved):
    with caplog.at_level(logging.DEBUG):
        bot.say(f"Số mình {phone}", extracted={"phone": phone})

    assert customer_memory.get_profile(SENDER)["phone"] == saved
    assert len(bot.leads()) == 1 and f"SĐT: {saved}\n" in bot.leads()[0]
    logs = [r.getMessage() for r in caplog.records]
    assert [m for m in logs if SENDER in m], "không bắt được log nào của tin này"
    last_9_digits = re.sub(r"\D", "", saved)[-9:]
    assert [m for m in logs if saved in m or last_9_digits in m] == []


@pytest.mark.parametrize(
    "extracted",
    [{}, {"phone": "không có"}, {"phone_declined": True}, {"phone": "chưa có", "phone_declined": True}],
    ids=["không trích được gì", "phone không có số", "phone_declined", "phone không có số và phone_declined"],
)
def test_phone_typed_in_message_is_saved_when_extraction_has_no_valid_phone(bot, extracted):
    bot.say(f"số điện thoại tôi là {PHONE}", reply="", escalate=True, extracted=extracted)

    profile = customer_memory.get_profile(SENDER)
    assert profile["phone"] == PHONE and "phone_declined" not in profile
    assert len(bot.leads()) == 1 and f"SĐT: {PHONE}\n" in bot.leads()[0]
    assert bot.sent[0][1] == escalation.ESCALATION_MESSAGE_HAS_PHONE


def test_valid_phone_from_the_model_wins_over_another_number_in_the_message(bot):
    bot.say(f"Số cũ {PHONE} không dùng nữa, Zalo mình là 0987 654 321", extracted={"phone": "0987 654 321"})

    assert customer_memory.get_profile(SENDER)["phone"] == "0987 654 321"


@pytest.mark.parametrize(
    "text",
    [
        "Bé nhà mình 3 tuổi ạ",
        "Nhà mình ở 185 Huỳnh Thúc Kháng, có gần cơ sở nào không ạ?",
        "Bé sinh ngày 15/03/2022, học phí 5.500.000 một tháng đúng không ạ?",
        "Cho mình hỏi lớp 18 - 24 tháng còn chỗ không, mình ở tầng 12 tòa 3",
    ],
)
def test_numbers_that_are_not_a_phone_are_not_saved_as_one(bot, text):
    bot.say(text, reply="", escalate=True)

    assert "phone" not in customer_memory.get_profile(SENDER)
    assert bot.leads() == []
    assert bot.sent[0][1] == escalation.ESCALATION_MESSAGE_ASK_PHONE


def test_test_chat_saves_phone_typed_in_message_like_messenger(monkeypatch, bot):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    bot.response = AIResponse(text="", should_escalate=True, model_used="none")

    resp = client.post(
        "/test-chat", params={"secret": WEBHOOK_SECRET}, json={"message": f"số điện thoại tôi là {PHONE}"}
    )

    assert resp.status_code == 200
    assert resp.json()["profile"]["phone"] == PHONE


def test_extraction_gets_the_bot_message_just_sent(bot):
    customer_memory._customers[SENDER] = {
        "conversation_history": [
            {"role": "user", "content": "Trường có ưu đãi gì không ạ?"},
            {"role": "assistant", "content": ASK_PHONE},
        ]
    }

    bot.say("không ạ")
    bot.say("Bé nhà mình 3 tuổi")

    assert bot.last_bot_messages == [ASK_PHONE, MODEL_TEXT]


def test_extraction_gets_no_bot_message_on_first_message(bot):
    bot.say("Chào trường ạ")

    assert bot.last_bot_messages == [""]


# --- Nhóm thông tin bot đã tư vấn (app/coverage.py), cho mẫu nhắc lại thứ 3 ---

PROGRAM_REPLY = (
    "Dạ các con 3–6 tuổi học Cambridge Early Years ạ. Ba/Mẹ muốn đưa bé đến tham quan vào buổi sáng hay buổi "
    "chiều ạ? [QUICK:visit_time]"
)
MENU_REPLY = "Dạ thực đơn của Casa đủ nhóm chất, kết hợp giáo cụ Montessori trong giờ ăn ạ."


def test_topics_the_bot_replied_with_are_saved_and_tokens_are_not_sent(bot):
    bot.say("Trường dạy chương trình gì ạ?", reply=PROGRAM_REPLY)

    assert customer_memory.get_profile(SENDER)["topics_covered"] == ["program", "visit_invite"]
    assert [text for kind, text, _ in bot.sent if kind == "text" and "[" in text] == []


def test_topics_of_later_replies_are_merged_without_duplicates(bot):
    bot.say("Trường dạy chương trình gì ạ?", reply=PROGRAM_REPLY)
    bot.say("Các con ăn gì ạ?", reply=MENU_REPLY)

    assert customer_memory.get_profile(SENDER)["topics_covered"] == ["program", "visit_invite", "menu"]


def test_escalated_reply_saves_no_topics(bot):
    bot.say("Cô chủ nhiệm tên gì ạ?", reply=PROGRAM_REPLY, escalate=True)

    assert "topics_covered" not in customer_memory.get_profile(SENDER)


def test_topics_from_the_extraction_model_are_ignored(bot):
    bot.say("Bé nhà em 3 tuổi", extracted={"kid_age": "3 tuổi", "topics_covered": ["school", "menu"]})
    profile = customer_memory.get_profile(SENDER)
    assert profile["kid_age"] == "3 tuổi" and "topics_covered" not in profile

    bot.say("Trường dạy chương trình gì ạ?", reply=PROGRAM_REPLY, extracted={"topics_covered": ["school"]})

    assert customer_memory.get_profile(SENDER)["topics_covered"] == ["program", "visit_invite"]


@pytest.mark.parametrize(
    ("escalate", "topics"),
    [(False, ["program", "visit_invite"]), (True, None)],
    ids=["trả lời", "chuyển tư vấn viên"],
)
def test_test_chat_saves_topics_like_messenger(monkeypatch, bot, escalate, topics):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    bot.response = AIResponse(text=PROGRAM_REPLY, should_escalate=escalate, model_used="fake-model")
    bot.extracted = {"topics_covered": ["school"]}

    resp = client.post("/test-chat", params={"secret": WEBHOOK_SECRET}, json={"message": "Trường dạy gì ạ?"})

    assert resp.status_code == 200
    assert resp.json()["profile"].get("topics_covered") == topics


class RecordingProvider(AIProvider):
    def __init__(self, reply):
        self.reply = reply
        self.user_messages = []

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024):
        self.user_messages.append(user_message)
        return self.reply


@pytest.fixture
def recorder(monkeypatch):
    recorder = RecordingProvider('{"phone_declined": true}')
    monkeypatch.setattr(settings, "AI_MODEL_ORDER", ["fake"])
    monkeypatch.setattr(ai_engine, "ai_engine_instance", ai_engine.ai_engine_instance)
    engine = AIEngine(qa_context="Q&A giả")
    engine._providers = {"fake": recorder}
    recorder.engine = engine
    return recorder


def test_extract_prompt_carries_the_bot_message_just_sent(recorder):
    info = asyncio.run(recorder.engine.extract_customer_info("không ạ", {}, last_bot_message=ASK_PHONE))

    assert info == {"phone_declined": True}
    assert f"Câu bot vừa hỏi: {ASK_PHONE}" in recorder.user_messages[0]
    assert "không ạ" in recorder.user_messages[0]


def test_extract_prompt_without_bot_message_keeps_old_callers_working(recorder):
    asyncio.run(recorder.engine.extract_customer_info("không ạ", {"kid_age": "3 tuổi"}))

    assert "Câu bot vừa hỏi" not in recorder.user_messages[0]
    assert "3 tuổi" in recorder.user_messages[0]


# --- QUICK_REPLIES khớp prompt và giới hạn của Messenger ---


def test_quick_reply_keys_match_the_prompt_tokens():
    assert set(re.findall(r"\[QUICK:([^\]]*)\]", SYSTEM_PROMPT)) == set(QUICK_REPLIES)


@pytest.mark.parametrize("key", sorted(QUICK_REPLIES))
def test_quick_reply_buttons_fit_messenger_limits(key):
    buttons = build_quick_replies(key)

    assert 1 <= len(buttons) <= 13
    for button in buttons:
        if button["content_type"] == "text":
            assert 0 < len(unicodedata.normalize("NFC", button["title"])) <= 20
            assert len(button["payload"]) <= 1000


def test_phone_key_is_the_messenger_phone_button():
    assert build_quick_replies("phone") == [{"content_type": "user_phone_number"}]


@pytest.mark.parametrize("key", ["", "khong-co", "PHONE"])
def test_unknown_key_builds_no_quick_replies(key):
    assert build_quick_replies(key) is None


# --- Graph API: tin nhắn, ảnh, messenger profile ---


@pytest.fixture
def graph(monkeypatch):
    """graph.facebook.com giả; ghi lại (path, params, body JSON) của mọi request."""
    monkeypatch.setattr(settings, "FB_PAGE_ACCESS_TOKEN", PAGE_TOKEN)
    calls = []

    async def handle(self, request):
        assert request.url.host == "graph.facebook.com"
        calls.append((request.url.path, dict(request.url.params), json.loads(request.content)))
        return httpx.Response(200, json={"result": "success"})

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle)
    return calls


def test_send_message_puts_quick_replies_on_last_chunk_only(graph):
    quick_replies = build_quick_replies("age")

    asyncio.run(messenger.send_message(SENDER, "a" * 2000 + "b" * 5, quick_replies=quick_replies))

    assert [body["message"] for _, _, body in graph] == [
        {"text": "a" * 2000, "metadata": "casa-bot"},
        {"text": "b" * 5, "metadata": "casa-bot", "quick_replies": quick_replies},
    ]


def test_send_message_without_quick_replies_sends_plain_text(graph):
    asyncio.run(messenger.send_message(SENDER, "Dạ vâng ạ"))

    assert [body["message"] for _, _, body in graph] == [{"text": "Dạ vâng ạ", "metadata": "casa-bot"}]


def test_send_image_carries_quick_replies(graph):
    quick_replies = build_quick_replies("campus")

    asyncio.run(messenger.send_image(SENDER, "https://casa.example/static/a.jpg", quick_replies=quick_replies))

    assert [body["message"] for _, _, body in graph] == [
        {
            "attachment": {"type": "image", "payload": {"url": "https://casa.example/static/a.jpg", "is_reusable": True}},
            "metadata": "casa-bot",
            "quick_replies": quick_replies,
        }
    ]


def test_echo_of_every_message_the_bot_sends_is_not_a_staff_reply(graph):
    asyncio.run(messenger.send_message(SENDER, "a" * 2005, quick_replies=build_quick_replies("age")))
    asyncio.run(messenger.send_image(SENDER, "https://casa.example/static/a.jpg"))

    assert len(graph) == 3
    for _, _, body in graph:
        echo = {
            "sender": {"id": PAGE_ID},
            "recipient": body["recipient"],
            "timestamp": TIMESTAMP,
            "message": {"is_echo": True, "app_id": 1234, "mid": "m_echo", **body["message"]},
        }
        assert parse_messaging_event(echo) is None


EXPECTED_PROFILE = {
    "get_started": {"payload": "GET_STARTED"},
    "ice_breakers": [
        {
            "locale": "default",
            "call_to_actions": [{"question": question, "payload": payload} for payload, question in ICE_BREAKERS.items()],
        }
    ],
}


def test_set_messenger_profile_posts_get_started_and_ice_breakers(graph):
    assert asyncio.run(set_messenger_profile()) == {"result": "success"}

    assert graph == [("/v21.0/me/messenger_profile", {"access_token": PAGE_TOKEN}, EXPECTED_PROFILE)]


def test_every_ice_breaker_posted_maps_back_to_its_question(graph):
    asyncio.run(set_messenger_profile())

    for action in graph[0][2]["ice_breakers"][0]["call_to_actions"]:
        assert parse_messaging_event(postback_event(action["payload"], title="")).text == action["question"]


def test_setup_messenger_profile_endpoint_returns_graph_result_without_token(monkeypatch, graph):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)

    resp = client.post("/setup-messenger-profile", params={"secret": WEBHOOK_SECRET})

    assert resp.status_code == 200
    assert resp.json() == {"result": "success"}
    assert PAGE_TOKEN not in resp.text
    assert [body for _, _, body in graph] == [EXPECTED_PROFILE]


@pytest.mark.parametrize("secret", [None, "", "sai"])
def test_setup_messenger_profile_endpoint_needs_secret(monkeypatch, graph, secret):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)
    params = {} if secret is None else {"secret": secret}

    assert client.post("/setup-messenger-profile", params=params).status_code == 403
    assert graph == []


# --- /static ---


def test_static_files_are_served():
    assert client.get("/static/.gitkeep").status_code == 200
    assert client.get("/static/khong-co.jpg").status_code == 404

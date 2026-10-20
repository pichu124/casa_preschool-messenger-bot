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

import app.main as main
from app import customer_memory, escalation
from app.ai_engine import AIResponse
from app.config import settings
from app.escalation import lead_events
from app.leads_sheet import post_lead_row

CUSTOMER_ID = "9000000000000401"
FB_NAME = "Lan Thử"
PHONE = "0900000401"
NEW_PHONE = "0911000402"
AD_TITLE = "Học thử 1 tuần miễn phí"
VISIT = "tham quan sáng thứ 7"
SHEET_DEPLOYMENT = "AKfycb-test-deployment"
SHEET_URL = f"https://script.google.com/macros/s/{SHEET_DEPLOYMENT}/exec"
SHEET_ECHO_URL = "https://script.googleusercontent.com/macros/echo?user_content_key=test-key&lib=test-lib"
SHEET_TOKEN = "sheet-token-test"
TELEGRAM_TOKEN = "123456:telegram-token-test"
MODEL_TEXT = "Dạ em ghi nhận ạ. Ba/Mẹ muốn tham quan buổi sáng hay buổi chiều ạ?"
QUESTION = "Bảng học phí chi tiết thế nào ạ?"
ASK_PHONE_WORDS = ("SĐT", "Zalo", "số điện thoại")
VN = timezone(timedelta(hours=7))


# --- lead_events: hàm thuần ---


@pytest.mark.parametrize(
    ("before", "extracted", "events"),
    [
        ({}, {}, []),
        ({}, {"kid_age": "3 tuổi"}, []),
        ({}, {"phone": PHONE}, ["new_phone"]),
        ({"kid_age": "3 tuổi"}, {"phone": "0900 000 401"}, ["new_phone"]),
        ({"phone": PHONE}, {}, []),
        ({"phone": PHONE}, {"phone": PHONE}, []),
        ({"phone": PHONE}, {"phone": "0900 000 401"}, []),
        ({"phone": "0900.000.401"}, {"phone": PHONE}, []),
        ({"phone": PHONE}, {"phone": NEW_PHONE}, ["phone_changed"]),
        ({}, {"phone": "không có"}, []),
        ({}, {"visit_request": VISIT}, ["visit_request"]),
        ({"visit_request": VISIT}, {"visit_request": VISIT}, []),
        ({"visit_request": VISIT}, {"visit_request": "học thử tuần sau"}, ["visit_request"]),
        ({"visit_request": VISIT}, {}, []),
        ({}, {"visit_request": "  "}, []),
        ({}, {"phone": PHONE, "visit_request": VISIT}, ["new_phone", "visit_request"]),
    ],
    ids=[
        "không có gì",
        "không có SĐT",
        "SĐT mới",
        "SĐT mới có dấu cách",
        "không gửi lại SĐT",
        "cùng SĐT",
        "cùng SĐT, có dấu cách",
        "cùng SĐT, hồ sơ có dấu chấm",
        "đổi SĐT",
        "SĐT không có chữ số",
        "hẹn mới",
        "hẹn giống lần trước",
        "hẹn khác lần trước",
        "không nhắc lại hẹn",
        "hẹn rỗng",
        "SĐT mới và hẹn",
    ],
)
def test_lead_events(before, extracted, events):
    assert lead_events(before, extracted) == events


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

    def leads(self, header=escalation.LEAD_HEADER):
        return [t for t in self.telegram if t.startswith(header)]


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


class Chat:
    """Phụ huynh nhắn qua process_message; Messenger và model giả."""

    def __init__(self):
        self.sent = []
        self.response = None
        self.extracted = {}

    def say(self, text, extracted=None, reply=MODEL_TEXT, escalate=False):
        self.response = AIResponse(text=reply, should_escalate=escalate, model_used="fake-model")
        self.extracted = extracted or {}
        asyncio.run(main.process_message(CUSTOMER_ID, text))


@pytest.fixture
def chat(monkeypatch):
    chat = Chat()

    async def send_message(recipient_id, text):
        assert recipient_id == CUSTOMER_ID
        chat.sent.append(text)

    async def send_typing_indicator(recipient_id, action="typing_on"):
        pass

    async def get_user_profile(user_id):
        first_name, last_name = FB_NAME.split()
        return {"first_name": first_name, "last_name": last_name}

    async def get_response(user_message, conversation_history=None, customer_context="", gap_hours=0.0):
        return chat.response

    async def extract_customer_info(user_message, existing_profile=None):
        return dict(chat.extracted)

    async def sync_to_github():
        return True

    monkeypatch.setattr(main, "send_message", send_message)
    monkeypatch.setattr(main, "send_typing_indicator", send_typing_indicator)
    monkeypatch.setattr(main, "get_user_profile", get_user_profile)
    monkeypatch.setattr(main.ai_engine, "get_response", get_response)
    monkeypatch.setattr(main.ai_engine, "extract_customer_info", extract_customer_info)
    monkeypatch.setattr(customer_memory, "sync_to_github", sync_to_github)
    return chat


def known_customer(**profile):
    customer_memory._customers[CUSTOMER_ID] = {"parent_name": FB_NAME, **profile}


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


# --- process_message phát sự kiện ---


def test_new_phone_sends_one_telegram_lead_and_one_sheet_row(chat, net):
    known_customer(
        kid_name="Bin",
        kid_age="3 tuổi",
        interested_campus="Kim Mã",
        area="Cầu Giấy",
        lead_source="ads",
        ad_title=AD_TITLE,
    )
    text = f"Số Zalo của mình là {PHONE}, bé dự kiến vào học tháng 9 ạ"

    chat.say(text, extracted={"phone": PHONE, "expected_start": "tháng 9"})

    assert chat.sent == [MODEL_TEXT]
    assert len(net.telegram) == 1
    lead = net.telegram[0]
    assert lead.startswith(escalation.LEAD_HEADER)
    for expected in (PHONE, FB_NAME, CUSTOMER_ID, "Bin", "3 tuổi", "Kim Mã", "Cầu Giấy", "tháng 9", AD_TITLE, text):
        assert expected in lead
    assert "Đã có SĐT" in lead
    assert "Câu hỏi:" not in lead

    assert len(net.sheet) == 1
    row = dict(net.sheet[0])
    assert_vietnam_now(row.pop("time"))
    assert row == {
        "token": SHEET_TOKEN,
        "event": "new_phone",
        "fb_name": FB_NAME,
        "customer_id": CUSTOMER_ID,
        "phone": PHONE,
        "kid_name": "Bin",
        "kid_age": "3 tuổi",
        "campus": "Kim Mã",
        "area": "Cầu Giấy",
        "expected_start": "tháng 9",
        "visit_request": "",
        "ad_title": AD_TITLE,
        "stage": "Đã có SĐT",
        "last_message": text,
    }
    assert escalation._pending == {}

    chat.say(f"Mình nhắc lại số {PHONE} ạ", extracted={"phone": PHONE})

    assert (len(net.telegram), len(net.sheet)) == (1, 1)


def test_sheet_row_joins_program_with_campus_and_address_with_area(chat, net):
    known_customer(interested_program="song ngữ", interested_campus="Kim Mã", address="ngõ 12 Trần Thái Tông")

    chat.say(f"Số mình {PHONE}", extracted={"phone": PHONE, "area": "Cầu Giấy"})

    assert [(row["campus"], row["area"]) for row in net.sheet] == [
        ("Kim Mã, song ngữ", "Cầu Giấy, ngõ 12 Trần Thái Tông")
    ]


def test_changed_phone_publishes_phone_changed(chat, net):
    known_customer(phone=PHONE)

    chat.say(f"Mình đổi sang số {NEW_PHONE} nhé", extracted={"phone": NEW_PHONE})

    assert net.leads() == []
    assert len(net.telegram) == len(net.leads("📞 KHÁCH ĐỔI SĐT")) == 1
    assert NEW_PHONE in net.telegram[0]
    assert [(row["event"], row["phone"]) for row in net.sheet] == [("phone_changed", NEW_PHONE)]
    assert customer_memory.get_profile(CUSTOMER_ID)["phone"] == NEW_PHONE


def test_same_phone_in_other_format_publishes_nothing(chat, net):
    known_customer(phone=PHONE)

    chat.say("Số mình 0900 000 401 ạ", extracted={"phone": "0900 000 401"})

    assert chat.sent == [MODEL_TEXT]
    assert (net.telegram, net.sheet) == ([], [])


def test_visit_request_publishes_once_per_new_request(chat, net):
    known_customer(kid_age="4 tuổi", interested_campus="Mỹ Đình")

    chat.say("Cho mình đặt lịch tham quan sáng thứ 7 nhé", extracted={"visit_request": VISIT})

    visits = net.leads("📅 KHÁCH HẸN THAM QUAN/HỌC THỬ")
    assert len(net.telegram) == len(visits) == 1
    assert VISIT in visits[0]
    assert [(row["event"], row["visit_request"], row["stage"]) for row in net.sheet] == [
        ("visit_request", VISIT, "Đã hẹn tham quan/học thử")
    ]

    chat.say("Vâng sáng thứ 7 ạ", extracted={"visit_request": VISIT})
    assert len(net.sheet) == 1

    chat.say("À cho bé học thử tuần sau luôn", extracted={"visit_request": "học thử tuần sau"})
    assert [row["visit_request"] for row in net.sheet] == [VISIT, "học thử tuần sau"]
    assert len(net.telegram) == 2


def test_no_sheet_url_sends_no_sheet_request(monkeypatch, chat, net):
    monkeypatch.setattr(settings, "LEADS_SHEET_WEBHOOK_URL", "")

    chat.say(f"Số mình {PHONE}", extracted={"phone": PHONE})

    assert chat.sent == [MODEL_TEXT]
    assert len(net.leads()) == 1
    assert net.sheet == []


def test_telegram_not_configured_still_writes_sheet_row(monkeypatch, chat, net):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")

    chat.say(f"Số mình {PHONE}", extracted={"phone": PHONE})

    assert chat.sent == [MODEL_TEXT]
    assert net.telegram == []
    assert [(row["event"], row["phone"]) for row in net.sheet] == [("new_phone", PHONE)]


@pytest.mark.parametrize("sheet_response", SHEET_FAILURES, ids=SHEET_FAILURE_IDS)
def test_sheet_failure_does_not_break_reply_or_telegram(chat, net, caplog, sheet_response):
    net.sheet_response = sheet_response

    with caplog.at_level(logging.DEBUG):
        chat.say(f"Số mình {PHONE}", extracted={"phone": PHONE})

    assert chat.sent == [MODEL_TEXT]
    assert len(net.leads()) == 1
    assert len(net.sheet) == 1
    assert customer_memory.get_profile(CUSTOMER_ID)["phone"] == PHONE
    assert customer_memory.get_conversation_history(CUSTOMER_ID)[-1] == {"role": "assistant", "content": MODEL_TEXT}
    assert [r for r in caplog.records if r.name == "app.leads_sheet" and r.levelno == logging.WARNING]
    assert leaked(caplog) == []


@pytest.mark.parametrize("escalate", [False, True], ids=["trả lời thường", "chuyển tư vấn viên"])
def test_lead_logs_contain_no_phone_or_sheet_url(chat, net, caplog, escalate):
    with caplog.at_level(logging.DEBUG):
        chat.say(
            f"Số mình {PHONE}, cho mình hẹn {VISIT}",
            extracted={"phone": PHONE, "visit_request": VISIT},
            reply="" if escalate else MODEL_TEXT,
            escalate=escalate,
        )

    assert [row["event"] for row in net.sheet] == ["new_phone", "visit_request"]
    assert len(net.telegram) == 2 + int(escalate)
    assert [r for r in caplog.records if CUSTOMER_ID in r.getMessage()], "không bắt được log nào của tin này"
    assert leaked(caplog) == []


# --- Câu chuyển tư vấn viên khi phụ huynh đã từ chối để lại SĐT ---


@pytest.mark.parametrize("declined_in", ["tin này", "hồ sơ"])
def test_escalation_after_phone_declined_does_not_ask_for_phone(chat, net, declined_in):
    extracted = {}
    if declined_in == "hồ sơ":
        known_customer(kid_age="3 tuổi", phone_declined=True)
    else:
        extracted = {"phone_declined": True}

    chat.say(f"Mình không để số đâu, {QUESTION}", extracted=extracted, reply="", escalate=True)

    assert len(chat.sent) == 1
    assert "tư vấn" in chat.sent[0] and "trực tiếp" in chat.sent[0]
    assert [word for word in ASK_PHONE_WORDS if word in chat.sent[0]] == []
    assert len(net.leads(escalation.ESCALATION_HEADER)) == len(net.telegram) == 1
    assert net.sheet == []
    assert customer_memory.get_profile(CUSTOMER_ID)["phone_declined"] is True
    assert customer_memory.get_conversation_history(CUSTOMER_ID)[-1] == {"role": "assistant", "content": chat.sent[0]}


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

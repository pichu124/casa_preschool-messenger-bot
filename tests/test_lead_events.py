"""Sự kiện lead (SĐT mới, đổi SĐT, hẹn tham quan/học thử, lead cập nhật thông tin) sang nhóm Telegram và Google Sheet.

Telegram và Google Sheet chạy thật tới tầng httpx; transport giả trả lời như api.telegram.org và như web app
Apps Script (POST /exec → 302 → JSON ở script.googleusercontent.com). process_message gọi bằng asyncio.run.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

import app.main as main
from app import customer_memory, escalation, leads_sheet
from app.ai_engine import AIProvider, AIResponse
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
        ({"phone": "+84 900 000 401"}, {"phone": PHONE}, []),
        ({"phone": PHONE}, {"phone": "84900000401"}, []),
        ({"phone": "+84900000401"}, {"phone": NEW_PHONE}, ["phone_changed"]),
        ({}, {"phone": "+84 900 000 401"}, ["new_phone"]),
        ({"phone": PHONE}, {"phone": "+84 0900 000 401"}, []),
        ({"phone": "840900000401"}, {"phone": PHONE}, []),
        ({"phone": "+84 0900 000 401"}, {"phone": NEW_PHONE}, ["phone_changed"]),
        ({}, {"phone": "+84 24 3123 4567"}, ["new_phone"]),
        ({"phone": "024 3123 4567"}, {"phone": "+84 24 3123 4567"}, []),
        ({"phone": "+84 024 3123 4567"}, {"phone": "02431234567"}, []),
        ({"phone": "024 3123 4567"}, {"phone": "+84 24 3123 4568"}, ["phone_changed"]),
        ({}, {"phone": "không có"}, []),
        ({"phone": PHONE}, {"phone": "900000401"}, []),
        ({"phone": "900 000 401"}, {"phone": PHONE}, []),
        ({"phone": "900000401"}, {"phone": NEW_PHONE}, ["phone_changed"]),
        ({}, {"phone": "+1 650 555 1234"}, ["new_phone"]),
        ({"phone": "+1 650 555 1234"}, {"phone": "+16505551234"}, []),
        ({"phone": PHONE}, {"phone": "+1 650 555 1234"}, ["phone_changed"]),
        ({"phone": "+1 650 555 1234"}, {"phone": "16505551234"}, ["phone_changed"]),
        ({"phone": PHONE}, {"phone": "+886 0900 000 401"}, ["phone_changed"]),
        ({"phone": "+66 090 000 0401"}, {"phone": PHONE}, ["phone_changed"]),
        ({}, {"visit_request": VISIT}, ["visit_request"]),
        ({"visit_request": VISIT}, {"visit_request": VISIT}, []),
        ({"visit_request": "tham quan buổi sáng"}, {"visit_request": "Tham quan  buổi sáng"}, []),
        ({"visit_request": "Tham Quan\tbuổi  sáng "}, {"visit_request": " THAM QUAN BUỔI SÁNG"}, []),
        ({"visit_request": VISIT}, {"visit_request": "học thử tuần sau"}, ["visit_request"]),
        ({"visit_request": VISIT}, {}, []),
        ({}, {"visit_request": "  "}, []),
        ({}, {"phone": PHONE, "visit_request": VISIT}, ["new_phone", "visit_request"]),
        ({"phone": PHONE}, {"expected_start": "tháng 12"}, ["info_update"]),
        ({"visit_request": VISIT, "kid_age": "dưới 2 tuổi"}, {"kid_age": "2 tuổi"}, ["info_update"]),
        ({"phone": PHONE}, {"interested_program": "song ngữ"}, ["info_update"]),
        ({"phone": PHONE}, {"address": "ngõ 12 Trần Thái Tông"}, ["info_update"]),
        ({"phone": PHONE, "kid_name": "Bin"}, {"kid_name": "Bơ"}, ["info_update"]),
        ({"phone": PHONE, "concerns": ["học phí"]}, {"concerns": ["học phí", "giờ đón"]}, ["info_update"]),
        ({"phone": PHONE, "kid_age": "2 tuổi"}, {"kid_age": " 2  Tuổi"}, []),
        ({"phone": PHONE, "interested_campus": "Kim Mã"}, {"interested_campus": "kim mã"}, []),
        ({"phone": PHONE, "concerns": ["học phí", "giờ đón"]}, {"concerns": ["Học phí"]}, []),
        ({"phone": PHONE, "area": "Cầu Giấy"}, {"address": "Cầu Giấy"}, []),
        ({"phone": PHONE, "area": "Cầu Giấy"}, {"area": "Cầu Giấy", "address": "cầu giấy"}, []),
        ({"phone": PHONE, "interested_campus": "Kim Mã"}, {"interested_program": "kim mã"}, []),
        ({"phone": PHONE, "kid_age": "2 tuổi"}, {"kid_age": "", "expected_start": "  ", "area": None}, []),
        ({"phone": PHONE}, {"parent_name": FB_NAME, "topics_covered": ["menu"], "lead_source": "ads"}, []),
        ({"kid_age": "2 tuổi"}, {"kid_age": "3 tuổi", "area": "Cầu Giấy"}, []),
        ({"phone": PHONE}, {"visit_request": VISIT, "kid_age": "2 tuổi"}, ["visit_request"]),
        ({"phone": PHONE}, {"phone": NEW_PHONE, "expected_start": "tháng 12"}, ["phone_changed"]),
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
        "cùng SĐT, hồ sơ có +84",
        "cùng SĐT, tin có 84",
        "đổi SĐT, hồ sơ có +84",
        "SĐT mới có +84",
        "cùng SĐT, tin có +84 0",
        "cùng SĐT, hồ sơ có 840",
        "đổi SĐT, hồ sơ có +84 0",
        "máy bàn mới có +84",
        "cùng máy bàn, tin có +84",
        "cùng máy bàn, hồ sơ có +84 0",
        "đổi máy bàn",
        "SĐT không có chữ số",
        "cùng SĐT, tin thiếu số 0",
        "cùng SĐT, hồ sơ thiếu số 0",
        "đổi SĐT, hồ sơ thiếu số 0",
        "SĐT nước ngoài mới",
        "cùng SĐT nước ngoài, khác cách viết",
        "đổi sang SĐT nước ngoài",
        "SĐT nước ngoài khác dãy số không có +",
        "đổi sang SĐT nước ngoài có 0 sau mã nước",
        "đổi từ SĐT nước ngoài có 0 sau mã nước",
        "hẹn mới",
        "hẹn giống lần trước",
        "hẹn giống, khác hoa thường và khoảng trắng",
        "hẹn giống, viết hoa hết và tab",
        "hẹn khác lần trước",
        "không nhắc lại hẹn",
        "hẹn rỗng",
        "SĐT mới và hẹn",
        "lead nói dự kiến nhập học",
        "lead đổi tuổi bé",
        "lead nói hệ",
        "lead nói địa chỉ",
        "lead đổi tên bé",
        "lead thêm mối quan tâm",
        "lead nói lại tuổi, khác hoa thường và khoảng trắng",
        "lead nói lại cơ sở, khác hoa thường",
        "lead nhắc lại mối quan tâm đã có",
        "lead nói lại khu vực vào ô địa chỉ",
        "lead nói lại khu vực vào cả hai ô",
        "lead nói lại cơ sở vào ô hệ",
        "lead, trích xuất trả trường rỗng",
        "lead, chỉ có trường không hiện trên thẻ",
        "chưa là lead mà nói tuổi và khu vực",
        "lead hẹn và nói tuổi: một sự kiện hẹn",
        "lead đổi SĐT và nói dự kiến nhập học: một sự kiện đổi SĐT",
    ],
)
def test_lead_events(before, extracted, events):
    assert lead_events(before, extracted) == events


# --- Telegram + Google Sheet giả ---


class Network:
    """api.telegram.org và web app Apps Script giả; ghi lại tin Telegram và body POST tới Google Sheet."""

    def __init__(self):
        self.telegram = []
        self.telegram_sent = []  # (message_id, body) of each message Telegram accepted
        self.deleted = set()  # message ids an admin deleted from the group
        self.telegram_delay = 0.0  # seconds api.telegram.org takes to answer
        self.sheet = []
        self.sheet_response = lambda: httpx.Response(200, json={"ok": True})
        self.unexpected = []

    async def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url == f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage":
            await asyncio.sleep(self.telegram_delay)
            body = json.loads(request.content)
            if body.get("reply_parameters", {}).get("message_id") in self.deleted:
                return httpx.Response(
                    400,
                    json={"ok": False, "error_code": 400, "description": "Bad Request: message to be replied not found"},
                )
            self.telegram.append(body["text"])
            message_id = 7000 + len(self.telegram)
            self.telegram_sent.append((message_id, body))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": message_id}})
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

    async def send_message(recipient_id, text, **kwargs):
        assert recipient_id == CUSTOMER_ID
        chat.sent.append(text)

    async def send_typing_indicator(recipient_id, action="typing_on"):
        pass

    async def get_user_profile(user_id):
        first_name, last_name = FB_NAME.split()
        return {"first_name": first_name, "last_name": last_name}

    async def get_response(user_message, conversation_history=None, customer_context="", gap_hours=0.0, media_note=""):
        return chat.response

    async def extract_customer_info(user_message, existing_profile=None, **kwargs):
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


def test_two_numbers_in_one_message_publish_the_first_as_new_phone(chat, net, caplog):
    two_numbers = f"{PHONE}, {NEW_PHONE}"

    with caplog.at_level(logging.DEBUG):
        chat.say(f"Số mình {two_numbers} ạ", extracted={"phone": two_numbers})

    assert customer_memory.get_profile(CUSTOMER_ID)["phone"] == PHONE
    assert len(net.telegram) == len(net.leads()) == 1
    assert [(row["event"], row["phone"]) for row in net.sheet] == [("new_phone", PHONE)]
    assert leaked(caplog) == []
    assert [r.getMessage() for r in caplog.records if NEW_PHONE in r.getMessage()] == []


def test_same_phone_without_leading_zero_publishes_nothing(chat, net):
    known_customer(phone=PHONE)

    chat.say("Số mình 900 000 401 ạ", extracted={"phone": "900 000 401"})

    assert chat.sent == [MODEL_TEXT]
    assert (net.telegram, net.sheet) == ([], [])


def test_phone_without_leading_zero_is_published_with_it(chat, net, caplog):
    with caplog.at_level(logging.DEBUG):
        chat.say("Số mình 900 000 401 ạ", extracted={"phone": "900 000 401"})

    assert customer_memory.get_profile(CUSTOMER_ID)["phone"] == PHONE
    assert [(row["event"], row["phone"]) for row in net.sheet] == [("new_phone", PHONE)]
    assert leaked(caplog) == []


def test_same_visit_request_in_other_case_and_spacing_publishes_nothing(chat, net):
    known_customer(visit_request="Tham quan buổi sáng thứ 7")

    chat.say("Vâng tham quan buổi sáng thứ 7 ạ", extracted={"visit_request": "tham quan  buổi sáng thứ 7"})

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


def tap(payload: str) -> str:
    """What process_message receives when the parent taps the quick reply button `payload`."""
    event = {"sender": {"id": CUSTOMER_ID}, "message": {"mid": payload, "text": "nút", "quick_reply": {"payload": payload}}}
    return main.parse_messaging_event(event).text


# Người vận hành 2026-10-22: bot mời tham quan (nút Đặt lịch tham quan), phụ huynh đồng ý rồi mới chọn buổi. Quyết định:
# hai tin Telegram cho cùng một lịch là chấp nhận được (tin đầu: phụ huynh đồng ý, tư vấn viên gọi được ngay; tin sau
# thêm buổi để chốt giờ, từ khi có thẻ lead là tin ngắn trả lời vào thẻ); bấm lại cùng buổi thì không gửi nữa.
def test_agreeing_to_visit_then_choosing_the_time_publishes_each_new_detail_once(chat, net):
    known_customer(kid_age="3 tuổi", interested_campus="Mỹ Đình")
    agree, morning = tap("QR:visit_invite:0"), tap("QR:visit_time:0")
    assert (agree, morning) == ("Em muốn đặt lịch tham quan trường ạ", "Em muốn hẹn tham quan buổi sáng ạ")

    chat.say(agree, extracted={"visit_request": "tham quan trường"})
    chat.say(morning, extracted={"visit_request": "tham quan buổi sáng"})
    chat.say(morning, extracted={"visit_request": "tham quan buổi sáng"})

    card_id, card, updates = card_and_updates(net)
    assert card.startswith("📅 KHÁCH HẸN THAM QUAN/HỌC THỬ") and "tham quan trường" in card and agree in card
    assert update_lines(updates) == [(card_id, f"🔄 {FB_NAME}: Hẹn: tham quan trường → tham quan buổi sáng")]
    assert [(row["event"], row["visit_request"], row["last_message"]) for row in net.sheet] == [
        ("visit_request", "tham quan trường", agree),
        ("visit_request", "tham quan buổi sáng", morning),
    ]


# --- Mỗi phụ huynh một thẻ Telegram; thay đổi sau là tin ngắn trả lời vào thẻ (người vận hành, 2026-10-22) ---

UPDATE_TIME = r"\n🕐 \d{2}/\d{2}/\d{4} \d{2}:\d{2}"


def replied_to(body):
    return body.get("reply_parameters", {}).get("message_id")


def card_and_updates(net):
    """(id of the one full card, [(replied-to id, text) of each later message]) of what Telegram accepted."""
    (card_id, card), *updates = net.telegram_sent
    assert "reply_parameters" not in card
    return card_id, card["text"], [(replied_to(body), body["text"]) for _, body in updates]


def update_lines(updates):
    """First line of each update; each must carry the Vietnam time on its second (and last) line."""
    for _, text in updates:
        assert re.fullmatch(r"🔄 [^\n]+" + UPDATE_TIME, text), text
    return [(reply_to, text.split("\n")[0]) for reply_to, text in updates]


def saved_card_id():
    on_disk = json.loads(Path(customer_memory.CUSTOMERS_PATH).read_text(encoding="utf-8"))[CUSTOMER_ID]
    assert on_disk.get("lead_card_msg_id") == customer_memory.get_profile(CUSTOMER_ID).get("lead_card_msg_id")
    return on_disk.get("lead_card_msg_id")


def test_phone_then_visit_then_changed_visit_is_one_card_and_two_replies(chat, net):
    """Sự cố 2026-10-22: SĐT 09:02, hẹn buổi sáng 09:03, đổi sáng mai 09:04 ra 3 thẻ đầy đủ như 3 khách."""
    chat.say(f"Số mình {PHONE}", extracted={"phone": PHONE})
    chat.say("Cho mình tham quan buổi sáng", extracted={"visit_request": "tham quan buổi sáng"})
    chat.say("À sáng mai nhé", extracted={"visit_request": "tham quan sáng mai"})

    card_id, card, updates = card_and_updates(net)
    assert card.startswith(escalation.LEAD_HEADER) and f"SĐT: {PHONE}\n" in card
    assert update_lines(updates) == [
        (card_id, f"🔄 {FB_NAME}: Hẹn: tham quan buổi sáng"),
        (card_id, f"🔄 {FB_NAME}: Hẹn: tham quan buổi sáng → tham quan sáng mai"),
    ]
    assert saved_card_id() == card_id
    assert [(row["event"], row["customer_id"], row["visit_request"]) for row in net.sheet] == [
        ("new_phone", CUSTOMER_ID, ""),
        ("visit_request", CUSTOMER_ID, "tham quan buổi sáng"),
        ("visit_request", CUSTOMER_ID, "tham quan sáng mai"),
    ]


def test_phone_after_visit_card_replies_that_the_parent_left_it(chat, net):
    chat.say(f"Cho mình hẹn {VISIT}", extracted={"visit_request": VISIT})
    chat.say(f"Số mình {PHONE}", extracted={"phone": PHONE})

    card_id, card, updates = card_and_updates(net)
    assert card.startswith("📅 KHÁCH HẸN THAM QUAN/HỌC THỬ") and "SĐT: chưa rõ" in card
    assert update_lines(updates) == [(card_id, f"🔄 {FB_NAME}: để lại SĐT {PHONE}")]


def test_changed_phone_after_card_replies_old_and_new_number(chat, net):
    chat.say(f"Số mình {PHONE}", extracted={"phone": PHONE})
    chat.say(f"Mình đổi sang số {NEW_PHONE} nhé", extracted={"phone": NEW_PHONE})

    card_id, _, updates = card_and_updates(net)
    assert update_lines(updates) == [(card_id, f"🔄 {FB_NAME}: SĐT: {PHONE} → {NEW_PHONE}")]
    assert [(row["event"], row["phone"]) for row in net.sheet] == [("new_phone", PHONE), ("phone_changed", NEW_PHONE)]


def test_phone_and_visit_in_the_first_message_are_one_card(chat, net):
    chat.say(f"Số mình {PHONE}, cho mình hẹn {VISIT}", extracted={"phone": PHONE, "visit_request": VISIT})

    card_id, card, updates = card_and_updates(net)
    assert updates == []
    assert card.startswith(escalation.LEAD_HEADER) and f"SĐT: {PHONE}\n" in card and VISIT in card
    assert saved_card_id() == card_id
    assert [row["event"] for row in net.sheet] == ["new_phone", "visit_request"]


def test_two_changes_in_one_message_are_one_reply(chat, net):
    chat.say(f"Cho mình hẹn {VISIT}", extracted={"visit_request": VISIT})
    chat.say(
        f"Số mình {PHONE}, cho bé học thử tuần sau luôn",
        extracted={"phone": PHONE, "visit_request": "học thử tuần sau"},
    )

    card_id, _, updates = card_and_updates(net)
    assert update_lines(updates) == [
        (card_id, f"🔄 {FB_NAME}: để lại SĐT {PHONE}; Hẹn: {VISIT} → học thử tuần sau")
    ]


def test_deleted_card_gets_a_new_full_card_that_later_changes_reply_to(chat, net):
    chat.say(f"Số mình {PHONE}", extracted={"phone": PHONE})
    old_card = saved_card_id()
    net.deleted.add(old_card)

    chat.say("Cho mình tham quan buổi sáng", extracted={"visit_request": "tham quan buổi sáng"})
    chat.say("À sáng mai nhé", extracted={"visit_request": "tham quan sáng mai"})

    (_, first), (new_card, second), (_, third) = net.telegram_sent
    assert "reply_parameters" not in first and "reply_parameters" not in second
    assert second["text"].startswith("📅 KHÁCH HẸN THAM QUAN/HỌC THỬ")
    assert f"SĐT: {PHONE}\n" in second["text"] and "tham quan buổi sáng" in second["text"]
    assert replied_to(third) == new_card != old_card
    assert third["text"].startswith(f"🔄 {FB_NAME}: Hẹn: tham quan buổi sáng → tham quan sáng mai\n")
    assert saved_card_id() == new_card


def test_two_close_messages_handled_concurrently_are_one_card_and_one_reply(monkeypatch, net):
    """Tin thứ hai tới khi thẻ của tin đầu còn đang gửi (Telegram chậm): vẫn trả lời vào thẻ đó, không ra thẻ thứ hai."""
    # Khoá đã phải chờ thì gắn với event loop của asyncio.run này: không để lại cho test sau.
    monkeypatch.setattr(escalation, "_lead_locks", {})
    net.telegram_delay = 0.05
    with_phone = {"parent_name": FB_NAME, "phone": PHONE}
    with_visit = {**with_phone, "visit_request": VISIT}

    async def two_messages():
        await asyncio.gather(
            escalation.publish_lead_events(["new_phone"], CUSTOMER_ID, FB_NAME, {}, with_phone, f"Số mình {PHONE}"),
            escalation.publish_lead_events(
                ["visit_request"], CUSTOMER_ID, FB_NAME, with_phone, with_visit, f"Cho mình hẹn {VISIT}"
            ),
        )

    asyncio.run(two_messages())

    card_id, card, updates = card_and_updates(net)
    assert card.startswith(escalation.LEAD_HEADER) and f"SĐT: {PHONE}\n" in card
    assert update_lines(updates) == [(card_id, f"🔄 {FB_NAME}: Hẹn: {VISIT}")]
    assert saved_card_id() == card_id


def test_card_not_sent_is_not_saved_and_the_next_lead_sends_the_card(monkeypatch, chat, net):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    chat.say(f"Số mình {PHONE}", extracted={"phone": PHONE})
    assert "lead_card_msg_id" not in customer_memory.get_profile(CUSTOMER_ID)

    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", TELEGRAM_TOKEN)
    chat.say(f"Cho mình hẹn {VISIT}", extracted={"visit_request": VISIT})

    card_id, card, updates = card_and_updates(net)
    assert updates == []
    assert card.startswith("📅 KHÁCH HẸN THAM QUAN/HỌC THỬ") and f"SĐT: {PHONE}\n" in card
    assert saved_card_id() == card_id


# --- Lead nói thêm thông tin: Sheet và thẻ Telegram cập nhật ngay (người vận hành, 2026-10-23) ---

INFO_UPDATE_EVENT = "Cập nhật thông tin"  # "Sự kiện" trên Sheet: Apps Script cũ hiện nguyên chữ


def test_lead_telling_expected_start_replies_to_the_card_and_updates_the_sheet_row(chat, net, caplog):
    """Sự cố 2026-10-23: đặt lịch, để số, rồi "Tầm tháng 12": hàng Sheet vẫn trống "Dự kiến nhập học"."""
    chat.say(f"Cho mình đặt lịch {VISIT}", extracted={"visit_request": VISIT})
    chat.say(f"Số mình {PHONE}", extracted={"phone": PHONE})
    with caplog.at_level(logging.DEBUG):
        chat.say("Tầm tháng 12", extracted={"expected_start": "tháng 12"})

    card_id, card, updates = card_and_updates(net)
    assert card.startswith("📅 KHÁCH HẸN THAM QUAN/HỌC THỬ")
    assert update_lines(updates) == [
        (card_id, f"🔄 {FB_NAME}: để lại SĐT {PHONE}"),
        (card_id, f"🔄 {FB_NAME}: Dự kiến nhập học: tháng 12"),
    ]
    assert [row["event"] for row in net.sheet] == ["visit_request", "new_phone", INFO_UPDATE_EVENT]
    row = dict(net.sheet[-1])
    assert_vietnam_now(row.pop("time"))
    assert row == {
        "token": SHEET_TOKEN,
        "event": INFO_UPDATE_EVENT,
        "fb_name": FB_NAME,
        "customer_id": CUSTOMER_ID,
        "phone": PHONE,
        "kid_name": "",
        "kid_age": "",
        "campus": "",
        "area": "",
        "expected_start": "tháng 12",
        "visit_request": VISIT,
        "ad_title": "",
        "stage": "Đã hẹn tham quan/học thử",
        "last_message": "Tầm tháng 12",
    }
    assert [r.getMessage() for r in caplog.records if r.getMessage().startswith("Lead ")][-1] == (
        f"Lead info_update for customer {CUSTOMER_ID}: Telegram msg_id={net.telegram_sent[-1][0]}, Sheet written=True"
    )
    assert leaked(caplog) == []


def test_lead_changing_kid_age_and_telling_area_and_concern_is_one_reply_old_to_new(chat, net):
    known_customer(kid_age="dưới 2 tuổi", concerns=["học phí"])
    chat.say(f"Số mình {PHONE}", extracted={"phone": PHONE})
    chat.say(
        "Bé 2 tuổi rồi, nhà mình ở Cầu Giấy, giờ đón thế nào ạ",
        extracted={"kid_age": "2 tuổi", "area": "Cầu Giấy", "concerns": ["giờ đón"]},
    )

    card_id, _, updates = card_and_updates(net)
    assert update_lines(updates) == [
        (
            card_id,
            f"🔄 {FB_NAME}: Tuổi bé: dưới 2 tuổi → 2 tuổi; Khu vực: Cầu Giấy; "
            "Mối quan tâm: học phí → học phí, giờ đón",
        )
    ]
    assert [(row["event"], row["kid_age"], row["area"]) for row in net.sheet] == [
        ("new_phone", "dưới 2 tuổi", ""),
        (INFO_UPDATE_EVENT, "2 tuổi", "Cầu Giấy"),
    ]


def test_parent_not_yet_a_lead_telling_kid_age_publishes_nothing(chat, net):
    chat.say("Bé nhà mình 2 tuổi", extracted={"kid_age": "2 tuổi"})
    chat.say("Nhà mình ở Cầu Giấy, tầm tháng 12 cho bé đi học", extracted={"area": "Cầu Giấy", "expected_start": "tháng 12"})

    assert chat.sent == [MODEL_TEXT, MODEL_TEXT]
    assert (net.telegram, net.sheet) == ([], [])
    assert customer_memory.get_profile(CUSTOMER_ID)["expected_start"] == "tháng 12"


def test_lead_repeating_known_info_publishes_nothing(chat, net):
    known_customer(
        phone=PHONE, kid_age="2 tuổi", interested_campus="Kim Mã", expected_start="tháng 12", concerns=["học phí"]
    )

    chat.say(
        "Bé 2 tuổi, học Kim Mã, tầm tháng 12, học phí sao ạ",
        extracted={"kid_age": "2 Tuổi", "interested_campus": "kim  mã", "expected_start": " Tháng 12", "concerns": ["Học phí"]},
    )

    assert chat.sent == [MODEL_TEXT]
    assert (net.telegram, net.sheet) == ([], [])


def test_lead_repeating_area_as_address_publishes_nothing(chat, net):
    """Thẻ gộp khu vực với địa chỉ: cùng giá trị sang ô kia không phải thay đổi, không có tin 🔄 rỗng."""
    known_customer(phone=PHONE, area="Cầu Giấy", lead_card_msg_id=7001)

    chat.say("Nhà mình ở Cầu Giấy", extracted={"address": "Cầu Giấy"})

    assert chat.sent == [MODEL_TEXT]
    assert (net.telegram, net.sheet) == ([], [])


def test_changed_visit_and_kid_age_in_one_message_are_one_reply_and_one_sheet_row(chat, net):
    chat.say(f"Cho mình hẹn {VISIT}", extracted={"visit_request": VISIT})
    chat.say(
        "Bé 3 tuổi, cho bé học thử tuần sau nhé", extracted={"visit_request": "học thử tuần sau", "kid_age": "3 tuổi"}
    )

    card_id, _, updates = card_and_updates(net)
    assert update_lines(updates) == [(card_id, f"🔄 {FB_NAME}: Hẹn: {VISIT} → học thử tuần sau; Tuổi bé: 3 tuổi")]
    assert [(row["event"], row["visit_request"], row["kid_age"]) for row in net.sheet] == [
        ("visit_request", VISIT, ""),
        ("visit_request", "học thử tuần sau", "3 tuổi"),
    ]


def test_lead_message_whose_extraction_returns_empty_fields_publishes_nothing(chat, net):
    known_customer(phone=PHONE, kid_age="2 tuổi", area="Cầu Giấy", lead_card_msg_id=7001)

    chat.say("Dạ vâng ạ", extracted={"kid_age": "", "area": "  ", "expected_start": None, "concerns": []})

    assert chat.sent == [MODEL_TEXT]
    assert (net.telegram, net.sheet) == ([], [])
    assert customer_memory.get_profile(CUSTOMER_ID)["kid_age"] == "2 tuổi"


def test_topics_of_a_lead_message_are_not_saved_and_publish_nothing(chat, net):
    """Chủ đề là thống kê của từng tin, không phải hồ sơ: không lưu, không sinh sự kiện lead."""
    known_customer(phone=PHONE, kid_age="3 tuổi", lead_card_msg_id=7001)

    chat.say(QUESTION, extracted={"topics": ["Học phí", "Ưu đãi"], "kid_age": "3 tuổi"})

    assert chat.sent == [MODEL_TEXT]
    assert "topics" not in customer_memory.get_profile(CUSTOMER_ID)
    assert (net.telegram, net.sheet) == ([], [])


def test_info_update_without_a_card_sends_the_full_card(chat, net):
    """Lead từ trước khi có thẻ, hoặc thẻ chưa gửi được (Telegram chưa cấu hình): thẻ đầy đủ, các thay đổi sau trả lời vào nó."""
    known_customer(phone=PHONE, kid_age="2 tuổi")

    chat.say("Tầm tháng 12", extracted={"expected_start": "tháng 12"})
    chat.say("À bé tên Bơ", extracted={"kid_name": "Bơ"})

    card_id, card, updates = card_and_updates(net)
    assert card.startswith("📝 KHÁCH CẬP NHẬT THÔNG TIN\n")
    assert f"SĐT: {PHONE}\n" in card and "Dự kiến nhập học: tháng 12\n" in card and "Tầm tháng 12" in card
    assert update_lines(updates) == [(card_id, f"🔄 {FB_NAME}: Tên bé: Bơ")]
    assert saved_card_id() == card_id
    assert [row["event"] for row in net.sheet] == [INFO_UPDATE_EVENT, INFO_UPDATE_EVENT]


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
    assert len(net.telegram) == 1 + int(escalate)
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


# --- Mọi model lỗi (vd tên model sai): SĐT phụ huynh gõ trong tin vẫn được nhận ---


class ModelDown(AIProvider):
    """Model lỗi ở mọi lời gọi, như khi tên model trong AI_MODEL_ORDER sai."""

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024):
        raise RuntimeError("The model `gpt-ten-sai` does not exist")


@pytest.fixture
def models_down(monkeypatch, chat):
    """get_response và extract_customer_info thật chạy hết chuỗi dự phòng, model nào cũng lỗi."""
    monkeypatch.delattr(main.ai_engine, "get_response")
    monkeypatch.delattr(main.ai_engine, "extract_customer_info")
    monkeypatch.setattr(settings, "AI_MODEL_ORDER", ["openai", "groq"])
    monkeypatch.setattr(main.ai_engine, "_providers", {"openai": ModelDown(), "groq": ModelDown()})
    return chat


def test_phone_typed_while_every_model_fails_is_saved_and_published(models_down, net):
    asyncio.run(main.process_message(CUSTOMER_ID, f"số điện thoại tôi là {PHONE}"))

    assert models_down.sent == [escalation.ESCALATION_MESSAGE_HAS_PHONE]
    assert len(net.leads(escalation.ESCALATION_HEADER)) == 1
    assert len(net.leads()) == 1 and f"SĐT: {PHONE}\n" in net.leads()[0]
    assert [(row["event"], row["phone"]) for row in net.sheet] == [("new_phone", PHONE)]
    assert customer_memory.get_profile(CUSTOMER_ID)["phone"] == PHONE


@pytest.mark.parametrize("text", [QUESTION, "Bé nhà mình 3 tuổi, nhà ở 185 Huỳnh Thúc Kháng ạ"])
def test_message_without_phone_while_every_model_fails_asks_for_it(models_down, net, text):
    asyncio.run(main.process_message(CUSTOMER_ID, text))

    assert models_down.sent == [escalation.ESCALATION_MESSAGE_ASK_PHONE]
    assert len(net.telegram) == len(net.leads(escalation.ESCALATION_HEADER)) == 1
    assert net.sheet == []
    assert "phone" not in customer_memory.get_profile(CUSTOMER_ID)


# --- Giờ trong tin cho admin là giờ Việt Nam, bất kể TZ của server ---


class RenderClock(datetime):
    """Đồng hồ server Render, giờ máy là UTC: 01:30 UTC ngày 22/10/2026, tức 08:30 giờ Việt Nam."""

    @classmethod
    def now(cls, tz=None):
        utc_now = datetime(2026, 10, 22, 1, 30, tzinfo=timezone.utc)
        return utc_now.astimezone(tz) if tz else utc_now.replace(tzinfo=None)


def test_escalation_and_lead_show_vietnam_time_on_a_utc_server(monkeypatch, chat, net):
    monkeypatch.setattr(escalation, "datetime", RenderClock)
    monkeypatch.setattr(leads_sheet, "datetime", RenderClock)

    chat.say(f"{QUESTION} Số mình {PHONE}", extracted={"phone": PHONE}, reply="", escalate=True)
    chat.say(f"Cho mình hẹn {VISIT}", extracted={"visit_request": VISIT})

    assert len(net.leads(escalation.ESCALATION_HEADER)) == len(net.leads()) == len(net.leads("🔄")) == 1
    assert [message for message in net.telegram if "🕐 22/10/2026 08:30" not in message.split("\n")] == []
    assert [row["time"] for row in net.sheet] == ["2026-10-22 08:30:00"] * 2


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


# --- Apps Script trong docs: mỗi phụ huynh một hàng, cột khớp khóa bot gửi ---

DOCS = Path(__file__).resolve().parent.parent / "docs" / "google-sheet-leads.md"
# Cột của Sheet đã chạy trước khi có upsert: hàng cũ ghi theo đúng thứ tự này.
FIRST_COLUMNS = [
    "time", "event", "fb_name", "customer_id", "phone", "kid_name", "kid_age",
    "campus", "area", "expected_start", "visit_request", "ad_title", "stage", "last_message",
]


def docs_columns(name="COLUMNS") -> list[tuple[str, str]]:
    (script,) = re.findall(r"```javascript\n(.*?)```", DOCS.read_text(encoding="utf-8"), re.S)
    (block,) = re.findall(rf"const {name} = \[\n(.*?)\n\];", script, re.S)
    return re.findall(r"\['(\w+)', '([^']*)'\]", block)


def test_docs_script_columns_are_the_keys_the_bot_sends_then_first_contact_and_updated_at(chat, net):
    chat.say(f"Số mình {PHONE}", extracted={"phone": PHONE})
    (body,) = net.sheet

    columns = docs_columns()

    assert [key for key, _ in columns[: len(FIRST_COLUMNS)]] == FIRST_COLUMNS
    assert columns[len(FIRST_COLUMNS):] == [("first_contact", "Lần đầu liên hệ"), ("updated_at", "Cập nhật lúc")]
    assert set(body) - {"token"} == set(FIRST_COLUMNS)


def test_docs_column_table_lists_every_script_column_in_order():
    text = DOCS.read_text(encoding="utf-8")
    table = text.split("| Khóa | Cột | Nội dung |", 1)[1].split("\n\n", 1)[0]

    rows = re.findall(r"^\| `(\w+)` \| ([^|]+) \|", table, re.M)

    assert [(key, title.strip()) for key, title in rows] == docs_columns()


MERGE_CASES = [
    ({}, {"area": "Cầu Giấy"}),
    ({"area": "Cầu Giấy"}, {"area": None, "address": "  ", "kid_age": 0, "kid_name": ""}),
    ({"concerns": ["học phí"]}, {"concerns": ["học phí", "giờ đón"]}),
    ({"concerns": "học phí"}, {"concerns": ["giờ đón"]}),
    ({"concerns": ["học phí"]}, {"concerns": "giờ đón"}),
    ({}, {"concerns": [""]}),
    ({"kid_age": "2 tuổi"}, {"kid_age": 3}),
]


@pytest.mark.parametrize("before,extracted", MERGE_CASES)
def test_merged_matches_update_profile(before, extracted):
    # lead_events đoán hồ sơ sau tin bằng escalation._merged: lệch với update_profile là tin 🔄 rỗng hoặc thiếu.
    customer_memory._customers["9000000000000999"] = dict(before)
    saved = asyncio.run(customer_memory.update_profile("9000000000000999", extracted))
    for key in ("first_seen", "last_seen", "message_count"):
        saved.pop(key, None)
    assert saved == escalation._merged(before, extracted)


# --- Tab "Chủ đề": mỗi tin có chủ đề một dòng, chỉ khi TOPICS_SHEET_ENABLED ---

TOPIC_TITLES = [
    "Thời gian", "Customer ID", "Quảng cáo", "Cơ sở/hệ", "Tuổi bé", "Chủ đề", "Chuyển tư vấn viên", "Câu hỏi",
]
TOPIC_TEXT = "Học phí và xe đưa đón thế nào ạ?"


@pytest.fixture
def topics_on(monkeypatch):
    monkeypatch.setattr(settings, "TOPICS_SHEET_ENABLED", True)


def test_topics_sheet_off_posts_no_topic_row(chat, net):
    chat.say(TOPIC_TEXT, extracted={"topics": ["Học phí"]})

    assert chat.sent == [MODEL_TEXT]
    assert net.sheet == []


def test_message_with_topics_posts_one_topic_row_after_the_reply(chat, net, topics_on):
    known_customer(
        kid_age="3 tuổi", interested_campus="Kim Mã", interested_program="song ngữ", lead_source="ads", ad_title=AD_TITLE
    )
    sent_before_post = []

    def answer():
        sent_before_post.append(list(chat.sent))
        return httpx.Response(200, json={"ok": True})

    net.sheet_response = answer

    chat.say(TOPIC_TEXT, extracted={"topics": ["học phí", "Xe đưa đón", "Giá vé máy bay"]})

    assert chat.sent == [MODEL_TEXT]
    assert sent_before_post == [[MODEL_TEXT]]
    (row,) = net.sheet
    assert_vietnam_now(row.pop("time"))
    assert row == {
        "type": "topic",
        "token": SHEET_TOKEN,
        "customer_id": CUSTOMER_ID,
        "ad_title": AD_TITLE,
        "campus": "Kim Mã, song ngữ",
        "kid_age": "3 tuổi",
        "topics": "Học phí, Xe đưa đón",
        "escalated": "Không",
        "question": TOPIC_TEXT,
    }
    assert FB_NAME not in json.dumps(row, ensure_ascii=False)


def test_escalated_message_posts_other_with_this_message_info_and_without_phone(chat, net, topics_on):
    text = f"Cô chủ nhiệm lớp Mầm tên gì ạ? Bé 4 tuổi, zalo {PHONE}"

    chat.say(text, extracted={"phone": PHONE, "kid_age": "4 tuổi"}, reply="", escalate=True)

    assert chat.sent == [escalation.ESCALATION_MESSAGE_HAS_PHONE]
    lead, topic = net.sheet
    assert (lead["event"], topic["type"]) == ("new_phone", "topic")
    assert (topic["topics"], topic["escalated"], topic["kid_age"], topic["ad_title"], topic["campus"]) == (
        "Khác", "Có", "4 tuổi", "", ""
    )
    assert topic["question"] == "Cô chủ nhiệm lớp Mầm tên gì ạ? Bé 4 tuổi, zalo [SĐT]"
    assert PHONE not in json.dumps(topic)


def test_topic_row_question_is_cut_to_300_characters(chat, net, topics_on):
    chat.say(f"Zalo {PHONE}, học phí " + "rất " * 100 + "cao không ạ", extracted={"topics": ["Học phí"]})

    (row,) = [row for row in net.sheet if row.get("type") == "topic"]
    assert row["question"] == ("Zalo [SĐT], học phí " + "rất " * 100)[:300]


@pytest.mark.parametrize(
    "extracted",
    [{"kid_age": "3 tuổi", "topics": []}, {"kid_age": "3 tuổi"}, {"topics": ["Giá vé máy bay"]}],
    ids=["topics rỗng", "không có topics", "chỉ khoá lạ"],
)
def test_message_without_topics_posts_no_topic_row(chat, net, topics_on, extracted):
    chat.say("Bé nhà mình 3 tuổi ạ", extracted=extracted)

    assert chat.sent == [MODEL_TEXT]
    assert net.sheet == []


@pytest.mark.parametrize("sheet_response", SHEET_FAILURES, ids=SHEET_FAILURE_IDS)
def test_topic_sheet_failure_does_not_break_the_reply(chat, net, caplog, topics_on, sheet_response):
    net.sheet_response = sheet_response

    with caplog.at_level(logging.DEBUG):
        chat.say(TOPIC_TEXT, extracted={"topics": ["Học phí"]})

    assert chat.sent == [MODEL_TEXT]
    assert len(net.sheet) == 1
    assert customer_memory.get_conversation_history(CUSTOMER_ID)[-1] == {"role": "assistant", "content": MODEL_TEXT}
    assert [r for r in caplog.records if r.name == "app.leads_sheet" and r.levelno == logging.WARNING]
    assert leaked(caplog) == []
    assert [r.getMessage() for r in caplog.records if TOPIC_TEXT in r.getMessage()] == []


def test_docs_topic_columns_are_the_keys_the_bot_sends(chat, net, topics_on):
    chat.say(TOPIC_TEXT, extracted={"topics": ["Học phí"]})
    (body,) = net.sheet

    columns = docs_columns("TOPIC_COLUMNS")

    assert [title for _, title in columns] == TOPIC_TITLES
    assert set(body) - {"type", "token"} == {key for key, _ in columns}


def test_docs_topic_column_table_lists_every_topic_column_in_order():
    text = DOCS.read_text(encoding="utf-8")
    table = text.split("| Khóa | Cột tab Chủ đề | Nội dung |", 1)[1].split("\n\n", 1)[0]

    rows = re.findall(r"^\| `(\w+)` \| ([^|]+) \|", table, re.M)

    assert [(key, title.strip()) for key, title in rows] == docs_columns("TOPIC_COLUMNS")

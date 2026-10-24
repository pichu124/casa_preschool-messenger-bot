"""Bot gửi ảnh Drive (app/media.py) cho phụ huynh đúng lúc: học phí, thời khoá biểu, cơ sở vật chất, thực đơn.

Danh mục ảnh là bản giả theo cây thư mục thật của trường; model trả lời và model trích xuất là fake, nên test đọc được
cả dòng [HỆ THỐNG] mà code đưa vào khối nhắc nhở. process_message gọi thẳng bằng asyncio.run.
"""

import asyncio
import json
import logging
import time
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.main as main
from app import customer_memory, escalation, media, messenger
from app.ai_engine import AIResponse
from app.config import settings

CUSTOMER_ID = "9000000000000701"
BASE_URL = "https://bot.example.test"
OCT_23 = date(2026, 10, 23)
REPLY = "Dạ vâng ạ. Không biết Ba/Mẹ có muốn ghé tham quan lớp một buổi không ạ? [QUICK:visit_invite]"
SHOWN = "Dạ vâng ạ. Không biết Ba/Mẹ có muốn ghé tham quan lớp một buổi không ạ?"
VISIT_BUTTONS = main.build_quick_replies("visit_invite")
QT, SN = "HỆ QUỐC TẾ", "HỆ SONG NGỮ"
TKB, CSVC = "THỜI KHÓA BIỂU", "ẢNH CƠ SỞ VẬT CHẤT"


def item(file_id, name, *path):
    return {"id": file_id, "name": name, "path": list(path), "modified": "2026-10-01T02:00:00.000Z",
            **media.classify(list(path), name)}


CATALOG = [
    item("qt-fee-10", "7.png", QT, "HỌC PHÍ THÁNG 10"),
    item("qt-menu", "Thực đơn mẫu.jpg", QT, "THỰC ĐƠN"),
    item("cl-tkb-15-36", "TKB 15 tháng - 3 tuổi.jpg", QT, "CƠ SỞ CHÙA LÁNG", TKB),
    item("cl-tkb-36-60", "TKB 3-5 tuổi.jpg", QT, "CƠ SỞ CHÙA LÁNG", TKB),
    item("md-tkb-15-36", "TKB 15 tháng - 3 tuổi.png", QT, "CƠ SỞ MỸ ĐÌNH", TKB),
    item("md-tkb-36-60", "TKB 3-5 tuổi.png", QT, "CƠ SỞ MỸ ĐÌNH", TKB),
    *[item(f"md-csvc-{i}", f"IMG_{i:02}.jpg", QT, "CƠ SỞ MỸ ĐÌNH", CSVC) for i in range(1, 7)],
    item("sn-fee-10", "Học phí Kim Mã - Tháng 10.png", SN, "HỌC PHÍ THÁNG 10"),
    item("sn-menu", "Thực đơn Kim Mã.png", SN, "THỰC ĐƠN"),
    item("km-tkb-15-36", "TKB 15 tháng  -3 tuổi.png", SN, "CƠ SỞ KIM MÃ", TKB),
    item("km-tkb-36-72", "TKB 3-6 tuổi.png", SN, "CƠ SỞ KIM MÃ", TKB),
    *[item(f"km-csvc-{i}", f"IMG_{i:02}.jpg", SN, "CƠ SỞ KIM MÃ", CSVC) for i in range(1, 6)],
]


GRAPH_FETCH_ERROR = "(#100) Failed to fetch the file from the url (code 100)"


def url(file_id: str) -> str:
    return f"{BASE_URL}/static/media/{file_id}.jpg"


class Parent:
    """Một phụ huynh nhắn bot: ghi lại tin và ảnh bot gửi, dòng nhắc model nhận, tin Telegram."""

    def __init__(self):
        self.sent: list[tuple] = []
        self.notes: list[str] = []
        self.telegram: list[str] = []
        self.failing: set[str] = set()
        self.response = None
        self.extracted = {}

    def say(self, text, reply=REPLY, extracted=None, escalate=False, customer_id=CUSTOMER_ID):
        """Phụ huynh gửi `text`; model trả `reply`, model trích xuất ra `extracted`. Trả về những gì bot gửi lượt này."""
        before = len(self.sent)
        self.response = AIResponse(text=reply, should_escalate=escalate, model_used="fake-model")
        self.extracted = extracted or {}
        asyncio.run(main.process_message(customer_id, text))
        return self.sent[before:]

    def images(self, sent=None) -> list[str]:
        return [s[1] for s in (self.sent if sent is None else sent) if s[0] == "image"]

    def history(self) -> list[str]:
        return [m["content"] for m in customer_memory.get_conversation_history(CUSTOMER_ID)]


@pytest.fixture
def today(monkeypatch):
    days = [OCT_23]
    monkeypatch.setattr(main, "_today_vn", lambda: days[0])
    return days


@pytest.fixture
def parent(monkeypatch, today):
    p = Parent()

    async def send_message(recipient_id, text, quick_replies=None):
        p.sent.append(("text", text, quick_replies))

    async def send_image(recipient_id, image_url, quick_replies=None):
        if image_url in p.failing:
            raise messenger.GraphError("image", 400, GRAPH_FETCH_ERROR)
        p.sent.append(("image", image_url, quick_replies))

    async def nothing(*args, **kwargs):
        return {}

    async def get_response(user_message, conversation_history=None, customer_context="", gap_hours=0.0, media_note=""):
        p.notes.append(media_note)
        return p.response

    async def extract_customer_info(user_message, existing_profile=None, **kwargs):
        return dict(p.extracted)

    async def send_telegram(text, reply_to=None):
        p.telegram.append(text)
        return 8000 + len(p.telegram)

    async def synced():
        return True

    monkeypatch.setattr(main, "send_message", send_message)
    monkeypatch.setattr(main, "send_image", send_image)
    monkeypatch.setattr(main, "send_typing_indicator", nothing)
    monkeypatch.setattr(main, "get_user_profile", nothing)
    monkeypatch.setattr(main.ai_engine, "get_response", get_response)
    monkeypatch.setattr(main.ai_engine, "extract_customer_info", extract_customer_info)
    monkeypatch.setattr(main, "_send_telegram", send_telegram)
    monkeypatch.setattr(escalation, "_send_telegram", send_telegram)
    monkeypatch.setattr(customer_memory, "sync_to_github", synced)
    monkeypatch.setattr(main, "_stale_fee_reminded", {})
    monkeypatch.setattr(main, "_image_failure_alerted_at", None)
    return p


@pytest.fixture
def catalog(monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", BASE_URL)
    monkeypatch.setattr(media, "_catalog", {**media._empty(), "items": {i["id"]: dict(i) for i in CATALOG}})
    monkeypatch.setattr(media, "_first_sync", None)  # no first sync pending from a TestClient lifespan of another test


def known(customer_id=CUSTOMER_ID, **fields):
    customer_memory.set_fields(customer_id, fields)


# --- tuổi bé theo tháng ---


@pytest.mark.parametrize(
    ("kid_age", "months"),
    [
        ("20 tháng", 20),
        ("15 tháng", 15),
        ("3 tuổi", 36),
        ("2-3 tuổi", 24),
        ("2 - 3 tuổi", 24),
        ("dưới 2 tuổi", 18),
        ("Dưới 2 tuổi", 18),
        ("Bé nhà em 3-5 tuổi ạ", 36),
        ("18 tháng tuổi", 18),
        ("2 tuổi 3 tháng", 27),
        ("2,5 tuổi", 30),
        ("3", 36),
        ("sinh năm", None),
        ("bé nhà em", None),
        ("", None),
    ],
)
def test_kid_age_is_read_as_months(kid_age, months):
    assert media.age_months(kid_age) == months


# Review vòng thời khoá biểu v2: tuổi ghi theo năm sinh không đọc được, timetable_asked kẹt và bot mỗi lượt dặn hỏi
# tuổi bé dù phụ huynh đã nói. Chỉ có năm: tính như sinh giữa năm (tháng 7).
@pytest.mark.parametrize(
    ("kid_age", "months"),
    [
        ("sinh năm 2022", 51),
        ("Bé sinh năm 2024 ạ", 27),
        ("bé sinh tháng 3/2022", 55),
        ("sinh tháng 3 năm 2022", 55),
        ("sinh 12/2023", 34),
        ("sinh ngày 5/3/2022", 55),
        ("sinh 2022", 51),
        ("sinh tháng 13/2022", None),
        ("sinh năm 2027", None),
        ("3 tuổi, sinh năm 2022", 36),
        ("2022", 51),  # năm sinh trơn, không phải 2022 tuổi
        ("4", 48),
        ("30", None),
        # Review vòng thời khoá biểu v3: năm tuyển sinh, học sinh của năm nào không phải năm sinh của bé
        ("Trường còn tuyển sinh 2025 không", None),
        ("lớp có bao nhiêu học sinh năm 2024 ạ", None),
    ],
)
def test_kid_age_written_as_the_birth_date_is_read_as_months(kid_age, months):
    assert media.age_months(kid_age, OCT_23) == months


@pytest.mark.parametrize(
    ("text", "campus"),
    [("Em quan tâm cơ sở Kim Mã ạ", "Kim Mã"), ("co so my dinh a", "Mỹ Đình"), ("cơ sở chùa láng", "Chùa Láng"),
     ("Kim Mã hay Mỹ Đình gần hơn ạ", None), ("trường ở đâu ạ", None), ("", None)],
)
def test_campus_named_in_a_message(text, campus):
    assert media.campus_in(text) == campus


@pytest.mark.parametrize(
    ("text", "campuses"),
    [("Chùa Láng và Kim Mã", ["Chùa Láng", "Kim Mã"]), ("Kim Mã hay Mỹ Đình gần hơn ạ", ["Kim Mã", "Mỹ Đình"]),
     ("Chùa Láng, Kim Mã", ["Chùa Láng", "Kim Mã"]), ("co so kim ma a, Kim Mã", ["Kim Mã"]), ("trường ở đâu ạ", []),
     ("", []), (None, [])],
)
def test_every_campus_named_in_a_message_in_its_order(text, campuses):
    assert media.campuses_in(text) == campuses


# --- học phí ---


def test_fee_image_waits_for_age_and_campus_then_goes_once_a_month(parent, catalog, today):
    sent = parent.say("cho em hỏi học phí ạ", extracted={"topics": ["Học phí"]})
    assert parent.images(sent) == []
    assert "học phí" not in parent.notes[-1]

    sent = parent.say("bé nhà em 3 tuổi, em quan tâm cơ sở Kim Mã",
                      extracted={"kid_age": "3 tuổi", "interested_campus": "Kim Mã"})
    assert sent == [("text", SHOWN, None), ("image", url("sn-fee-10"), VISIT_BUTTONS)]
    assert "[HỆ THỐNG] Sau câu trả lời này hệ thống gửi ảnh học phí hệ Song ngữ" in parent.notes[-1]
    assert "[đã gửi ảnh học phí hệ Song ngữ" in parent.history()[-1]
    assert parent.history()[-1].startswith(REPLY)

    sent = parent.say("học phí như vậy là theo quý ạ?", extracted={"topics": ["Học phí"]})
    assert parent.images(sent) == []
    assert "học phí" not in parent.notes[-1]

    today[0] = date(2026, 11, 2)
    sent = parent.say("cho em hỏi lại học phí tháng này", extracted={"topics": ["Học phí"]})
    assert parent.images(sent) == [url("sn-fee-10")]


def test_kim_ma_parent_gets_the_bilingual_fee_even_without_a_kim_ma_folder_on_drive(parent, catalog, monkeypatch):
    items = {i["id"]: dict(i) for i in CATALOG if not i["id"].startswith("km-")}
    monkeypatch.setattr(media, "_catalog", {**media._empty(), "items": items})
    known(kid_age="3 tuổi", interested_campus="Kim Mã")

    sent = parent.say("học phí bao nhiêu ạ", extracted={"topics": ["Học phí"]})

    assert parent.images(sent) == [url("sn-fee-10")]
    assert not customer_memory.get_profile(CUSTOMER_ID).get("fee_asked")


def test_fee_question_with_age_and_campus_known_is_announced_to_the_model(parent, catalog):
    known(kid_age="20 tháng", interested_campus="Mỹ Đình")

    sent = parent.say("học phí bao nhiêu ạ", extracted={"topics": ["Học phí"]})

    assert parent.images(sent) == [url("qt-fee-10")]
    note = parent.notes[-1]
    assert "Nếu phụ huynh hỏi học phí/ưu đãi" in note and "hệ Quốc tế" in note
    assert "không nêu con số" in note
    assert customer_memory.get_profile(CUSTOMER_ID)["media_sent"].keys() == {"fee:quoc_te:2026-10"}


def test_parent_refusing_the_phone_but_asking_the_fee_gets_the_image_without_a_consultant(parent, catalog):
    known(interested_campus="Mỹ Đình", phone_declined=True)

    sent = parent.say("cứ báo học phí luôn đi em", extracted={"topics": ["Học phí"]})

    assert parent.images(sent) == [url("qt-fee-10")]
    assert "Nếu phụ huynh hỏi học phí/ưu đãi" in parent.notes[-1]
    assert not [t for t in parent.telegram if t.startswith(escalation.ESCALATION_HEADER)]


def test_parent_not_leaving_the_phone_when_asked_gets_the_image(parent, catalog):
    known(interested_campus="Kim Mã")
    parent.say("bé nhà em học Kim Mã", reply="Dạ nếu tiện Ba/Mẹ để lại SĐT/Zalo nhé? [QUICK:phone]")

    sent = parent.say("em cứ báo con số luôn đi", extracted={"topics": ["Học phí"]})

    assert parent.images(sent) == [url("sn-fee-10")]


ASKED_PHONE = "Dạ nếu tiện Ba/Mẹ để lại SĐT/Zalo nhé? [QUICK:phone]"


# Review vòng thời khoá biểu v2: model xin SĐT "để em gửi bảng học phí chi tiết" (tư vấn viên gửi qua Zalo) được đọc
# là báo gửi ảnh học phí; tin bot trước có "Zalo" nên luật "không để số mà đòi giá" bỏ qua tuổi bé, và phụ huynh không
# hỏi học phí nhận ảnh học phí.
def test_asking_the_phone_to_send_the_fee_table_sends_no_fee_image(parent, catalog):
    known(interested_campus="Kim Mã")
    parent.say("Em quan tâm Kim Mã", reply=ASKED_PHONE)
    reply = "Dạ hiện Nhà trường chưa có tuyến xe bus ạ. Ba/Mẹ cho em xin SĐT/Zalo để em gửi bảng học phí chi tiết ạ."

    sent = parent.say("trường có xe đưa đón không", reply=reply)

    assert parent.images(sent) == []
    assert not customer_memory.get_profile(CUSTOMER_ID).get("fee_asked")


FEE_SENT = "Dạ em gửi Ba/Mẹ chính sách học phí cơ sở Kim Mã ạ. [SEND:fee]"


def test_fee_without_the_age_goes_only_to_a_parent_asking_the_fee(parent, catalog):
    known(interested_campus="Kim Mã")
    parent.say("Em quan tâm Kim Mã", reply=ASKED_PHONE)

    sent = parent.say("trường có xe đưa đón không", reply=FEE_SENT)

    assert parent.images(sent) == []
    # Phụ huynh không hỏi học phí: không chờ tuổi bé để rồi tự gửi ảnh học phí ở lượt sau
    assert not customer_memory.get_profile(CUSTOMER_ID).get("fee_asked")
    assert parent.images(parent.say("bé nhà em 4 tuổi ạ", extracted={"kid_age": "4 tuổi"})) == []


def test_parent_not_leaving_the_phone_and_naming_the_fee_gets_it_when_the_reply_sends_it(parent, catalog):
    known(interested_campus="Kim Mã")
    parent.say("Em quan tâm Kim Mã", reply=ASKED_PHONE)

    sent = parent.say("em cứ báo học phí luôn đi", reply=FEE_SENT)

    assert parent.images(sent) == [url("sn-fee-10")]


# Review vòng thời khoá biểu v3: phụ huynh hỏi học phí ở tin trước (chưa biết tuổi, cờ fee_asked chờ), bot xin SĐT,
# tin này không để số: vẫn là phụ huynh đòi giá mà không để số, biết cơ sở thì gửi.
def test_parent_who_asked_the_fee_before_and_now_does_not_leave_the_phone_gets_it(parent, catalog):
    known(interested_campus="Kim Mã")
    assert parent.images(parent.say("học phí bao nhiêu ạ", reply=ASKED_PHONE, extracted={"topics": ["Học phí"]})) == []
    assert customer_memory.get_profile(CUSTOMER_ID)["fee_asked"] is True

    sent = parent.say("thôi không để số đâu em")

    assert parent.images(sent) == [url("sn-fee-10")]
    assert not customer_memory.get_profile(CUSTOMER_ID).get("fee_asked")


def test_parent_refusing_the_phone_without_a_campus_gets_no_fee_image(parent, catalog):
    known(kid_age="3 tuổi", phone_declined=True)

    sent = parent.say("cứ báo học phí luôn đi em", extracted={"topics": ["Học phí"]})

    assert parent.images(sent) == []
    assert "học phí" not in parent.notes[-1]
    assert not [t for t in parent.telegram if t.startswith(escalation.ESCALATION_HEADER)]


def test_stale_fee_image_is_sent_and_the_school_is_reminded_once_a_day(parent, catalog, today):
    today[0] = date(2026, 11, 2)
    fee = {"topics": ["Học phí"]}
    for n, day in enumerate((2, 2, 3)):
        customer_id = f"900000000000071{n}"
        known(customer_id, kid_age="3 tuổi", interested_campus="Kim Mã")
        today[0] = date(2026, 11, day)
        assert parent.images(parent.say("học phí bao nhiêu ạ", extracted=fee, customer_id=customer_id)) == [
            url("sn-fee-10")
        ]
        if n == 1:
            reminders = [t for t in parent.telegram if "HỌC PHÍ THÁNG 11" in t]
            assert len(reminders) == 1
            assert "Song ngữ" in reminders[0] and "tháng 10" in reminders[0] and "/capnhatanh" in reminders[0]

    assert len([t for t in parent.telegram if "HỌC PHÍ THÁNG 11" in t]) == 2


def test_last_years_fee_image_of_this_month_is_sent_and_the_school_is_reminded(parent, catalog, today):
    old = {**item("sn-fee-11", "hp.png", SN, "HỌC PHÍ THÁNG 11"), "modified": "2026-11-01T02:00:00.000Z"}
    media._catalog["items"]["sn-fee-11"] = old
    today[0] = date(2027, 11, 3)
    known(kid_age="3 tuổi", interested_campus="Kim Mã")

    assert parent.images(parent.say("học phí bao nhiêu ạ", extracted={"topics": ["Học phí"]})) == [url("sn-fee-11")]

    (reminder,) = [t for t in parent.telegram if "HỌC PHÍ THÁNG 11" in t]
    assert "Song ngữ" in reminder and "ảnh tháng 11 sửa lần cuối 01/11/2026" in reminder, reminder
    assert "đổi tên hay chuyển thư mục không tính là ảnh mới" in reminder, reminder


def test_fee_asked_again_in_the_same_month_does_not_send_next_month_unasked(parent, catalog, today):
    known(kid_age="3 tuổi", interested_campus="Kim Mã")
    assert parent.images(parent.say("học phí bao nhiêu ạ", extracted={"topics": ["Học phí"]})) == [url("sn-fee-10")]

    assert parent.images(parent.say("học phí như vậy là theo quý ạ?", extracted={"topics": ["Học phí"]})) == []
    assert not customer_memory.get_profile(CUSTOMER_ID).get("fee_asked")

    today[0] = date(2026, 11, 2)
    assert parent.images(parent.say("dạ vâng")) == []


def test_fee_asked_while_drive_has_no_fee_image_of_the_system_does_not_wait(parent, catalog):
    known(kid_age="3 tuổi", interested_campus="Kim Mã")
    fee = media._catalog["items"].pop("sn-fee-10")

    assert parent.images(parent.say("học phí bao nhiêu ạ", extracted={"topics": ["Học phí"]})) == []
    assert not customer_memory.get_profile(CUSTOMER_ID).get("fee_asked")

    media._catalog["items"]["sn-fee-10"] = fee
    assert parent.images(parent.say("dạ vâng")) == []


# --- thời khoá biểu ---


# Người vận hành 2026-10-24: hỏi thời khoá biểu khi chưa biết cơ sở, bot nói "em gửi ngay bên dưới" (ảnh mặc định
# Mỹ Đình nhóm 3–5 tuổi) mà ảnh không tới. Thời khoá biểu chỉ gửi khi đã biết cả cơ sở và tuổi bé; thiếu thì hỏi.
def test_timetable_waits_for_the_campus_and_the_age_then_goes_once(parent, catalog):
    sent = parent.say("Cho mình tham khảo thời khoá biểu nhé")
    assert parent.images(sent) == []
    note = parent.notes[-1]
    assert "Chưa biết cơ sở Ba/Mẹ quan tâm và tuổi bé nên chưa gửi ảnh thời khoá biểu" in note, note
    assert "để em gửi đúng thời khoá biểu" in note and "không nói tư vấn viên sẽ gửi" in note, note
    assert "hệ thống gửi ảnh thời khoá biểu" not in note, note
    assert customer_memory.get_profile(CUSTOMER_ID)["timetable_asked"] is True

    sent = parent.say("Em quan tâm cơ sở Kim Mã ạ", extracted={"interested_campus": "Kim Mã"})
    assert parent.images(sent) == []
    assert "Chưa biết tuổi bé nên chưa gửi ảnh thời khoá biểu" in parent.notes[-1], parent.notes[-1]

    sent = parent.say("Bé nhà em 3-5 tuổi ạ", extracted={"kid_age": "3-5 tuổi"})
    assert sent == [("text", SHOWN, None), ("image", url("km-tkb-36-72"), VISIT_BUTTONS)]
    assert "[HỆ THỐNG] Sau câu trả lời này hệ thống gửi ảnh thời khoá biểu cơ sở Kim Mã" in parent.notes[-1]
    assert not customer_memory.get_profile(CUSTOMER_ID).get("timetable_asked")

    assert parent.images(parent.say("dạ vâng")) == []


def test_programme_question_without_campus_or_age_sends_no_timetable_but_asks_for_them(parent, catalog):
    sent = parent.say("Trường dạy chương trình gì ạ?", extracted={"topics": ["Chương trình/phương pháp"]})

    assert parent.images(sent) == []
    assert (
        "[HỆ THỐNG] Nếu phụ huynh hỏi chương trình học/Cambridge/thời khoá biểu: chưa biết cơ sở Ba/Mẹ quan tâm và "
        "tuổi bé nên chưa gửi ảnh thời khoá biểu"
    ) in parent.notes[-1], parent.notes[-1]
    assert customer_memory.get_profile(CUSTOMER_ID)["timetable_asked"] is True

    sent = parent.say("Bé 20 tháng, em quan tâm Mỹ Đình", extracted={"kid_age": "20 tháng", "interested_campus": "Mỹ Đình"})
    assert parent.images(sent) == [url("md-tkb-15-36")]


@pytest.mark.parametrize(
    ("kid_age", "campus", "timetable"),
    [("bé sinh tháng 3/2022", "Kim Mã", "km-tkb-36-72"), ("sinh năm 2024", "Mỹ Đình", "md-tkb-15-36")],
)
def test_timetable_goes_for_a_kid_age_written_as_the_birth_date(parent, catalog, kid_age, campus, timetable):
    known(kid_age=kid_age, interested_campus=campus)

    assert parent.images(parent.say("Cho em xin thời khoá biểu ạ")) == [url(timetable)]
    assert "tuổi bé" not in parent.notes[-1], parent.notes[-1]
    assert not customer_memory.get_profile(CUSTOMER_ID).get("timetable_asked")


def test_birth_year_said_in_the_message_is_the_kids_age(parent, catalog):
    known(interested_campus="Kim Mã")

    assert parent.images(parent.say("Bé nhà em sinh năm 2022, cho em xin thời khoá biểu ạ")) == [url("km-tkb-36-72")]


def test_enrolment_year_in_the_message_is_not_the_kids_age(parent, catalog):
    known(interested_campus="Kim Mã")

    assert parent.images(parent.say("Trường còn tuyển sinh 2025 không, cho em xin thời khoá biểu")) == []
    assert "Chưa biết tuổi bé nên chưa gửi ảnh thời khoá biểu" in parent.notes[-1], parent.notes[-1]


def test_timetable_with_the_age_known_asks_only_the_campus(parent, catalog):
    known(kid_age="4 tuổi")

    assert parent.images(parent.say("Cho em xin thời khoá biểu ạ")) == []
    assert "Chưa biết cơ sở Ba/Mẹ quan tâm nên chưa gửi ảnh thời khoá biểu" in parent.notes[-1], parent.notes[-1]


@pytest.mark.parametrize("program", ["song ngữ", "quốc tế"])
def test_the_programme_the_parent_wants_does_not_pick_the_timetable_campus(parent, catalog, program):
    known(interested_program=program, kid_age="4 tuổi")

    assert parent.images(parent.say("Trường dạy chương trình gì ạ?", extracted={"topics": ["Chương trình/phương pháp"]})) == []


@pytest.mark.parametrize("kid_age", ["4 tuổi", "10 tháng"], ids=["no-timetable-of-the-campus", "no-group-of-the-age"])
def test_timetable_that_drive_does_not_have_does_not_wait(parent, catalog, kid_age):
    for file_id in [i for i in media._catalog["items"] if i.startswith("md-tkb")]:
        media._catalog["items"].pop(file_id)
    known(interested_campus="Mỹ Đình" if kid_age == "4 tuổi" else "Kim Mã", kid_age=kid_age)

    assert parent.images(parent.say("Cho em xin thời khoá biểu ạ")) == []
    assert "thời khoá biểu" not in parent.notes[-1]
    assert not customer_memory.get_profile(CUSTOMER_ID).get("timetable_asked")


CAMPUS_LIST = "Dạ Casa có 3 cơ sở: hệ Quốc tế Chùa Láng, hệ Quốc tế Mỹ Đình và hệ Song ngữ Kim Mã ạ. [QUICK:campus]"


# Hội thoại thật 2026-10-24: phụ huynh quan tâm "Chùa Láng và Kim Mã", chọn "3-5 tuổi", rồi "Gửi thời khoá biểu 2 hệ
# nhé" mà không ảnh nào tới (bot còn bịa "tư vấn viên sẽ gửi" cho Kim Mã). Mỗi cơ sở một ảnh, mỗi ảnh một lần.
def test_timetables_of_every_campus_the_parent_named_go_once_the_age_is_known(parent, catalog):
    assert parent.images(parent.say("Cho mình tham khảo thời khoá biểu nhé")) == []
    assert parent.images(parent.say("Trường có những cơ sở nào", reply=CAMPUS_LIST)) == []
    sent = parent.say("Chùa Láng và Kim Mã", extracted={"interested_campus": "Chùa Láng, Kim Mã"})
    assert parent.images(sent) == []
    assert "Chưa biết tuổi bé nên chưa gửi ảnh thời khoá biểu" in parent.notes[-1], parent.notes[-1]

    sent = parent.say("Bé nhà em 3-5 tuổi ạ", extracted={"kid_age": "3-5 tuổi"})

    assert parent.images(sent) == [url("cl-tkb-36-60"), url("km-tkb-36-72")]
    for campus in ("Chùa Láng", "Kim Mã"):
        assert f"[HỆ THỐNG] Sau câu trả lời này hệ thống gửi ảnh thời khoá biểu cơ sở {campus}." in parent.notes[-1]
    assert not customer_memory.get_profile(CUSTOMER_ID).get("timetable_asked")
    assert parent.images(parent.say("Gửi thời khoá biểu 2 hệ nhé")) == []


def test_both_systems_asked_for_get_the_timetables_of_the_campuses_named_earlier(parent, catalog):
    known(kid_age="4 tuổi")
    parent.say("Chùa Láng và Kim Mã")

    sent = parent.say("Gửi thời khoá biểu 2 hệ nhé")

    assert parent.images(sent) == [url("cl-tkb-36-60"), url("km-tkb-36-72")]


@pytest.mark.parametrize("both", ["cả 2 cơ sở", "hai bên", "2 trường"])
def test_both_campuses_get_the_timetables_of_every_campus_named_and_no_system_not_named(parent, catalog, both):
    known(kid_age="4 tuổi")
    parent.say("Chùa Láng và Kim Mã")

    assert parent.images(parent.say(f"Gửi thời khoá biểu {both} nhé")) == [url("cl-tkb-36-60"), url("km-tkb-36-72")]

    customer_memory.set_fields(CUSTOMER_ID, {"conversation_history": [], "media_sent": {}, "interested_campus": "Kim Mã"})
    sent = parent.say(f"Cho em xin TKB {both} ạ")

    assert parent.images(sent) == [url("km-tkb-36-72")]  # không thêm hệ Quốc tế mà phụ huynh chưa nêu, không hỏi
    assert "Chưa biết cơ sở" not in parent.notes[-1], parent.notes[-1]
    assert not customer_memory.get_profile(CUSTOMER_ID).get("timetable_asked")


@pytest.mark.parametrize("text", ["Gửi thời khoá biểu 2 hệ nhé", "cho em xin TKB cả hai hệ ạ"])
def test_both_systems_without_an_international_campus_ask_which_one(parent, catalog, text):
    known(kid_age="4 tuổi")

    sent = parent.say(text)

    assert parent.images(sent) == [url("km-tkb-36-72")]  # hệ Song ngữ chỉ có Kim Mã
    note = parent.notes[-1]
    assert "Chưa biết cơ sở hệ Quốc tế Ba/Mẹ quan tâm (Chùa Láng hay Mỹ Đình) nên chưa gửi ảnh thời khoá biểu" in note, note
    assert customer_memory.get_profile(CUSTOMER_ID)["timetable_asked"] is True

    sent = parent.say("Em quan tâm cơ sở Mỹ Đình ạ", extracted={"interested_campus": "Mỹ Đình"})
    assert parent.images(sent) == [url("md-tkb-36-60")]
    assert not customer_memory.get_profile(CUSTOMER_ID).get("timetable_asked")


# Review vòng thời khoá biểu v2: "học phí 2 hệ" khi chưa rõ cơ sở Quốc tế chỉ gửi ảnh Song ngữ, xoá fee_asked, và tin
# sau nêu cơ sở Quốc tế không nhận ảnh nào. Ảnh học phí đi theo hệ (Chùa Láng, Mỹ Đình dùng chung ảnh Quốc tế).
def test_fee_of_both_systems_goes_without_knowing_the_international_campus(parent, catalog):
    known(kid_age="3 tuổi")

    sent = parent.say("Cho mình xin học phí 2 hệ nhé", extracted={"topics": ["Học phí"]})

    assert parent.images(sent) == [url("sn-fee-10"), url("qt-fee-10")]
    note = parent.notes[-1]
    assert "gửi ảnh học phí hệ Quốc tế." in note and "gửi ảnh học phí hệ Song ngữ (cơ sở Kim Mã)." in note, note
    assert "[đã gửi ảnh học phí hệ Quốc tế]" in parent.history()[-1]
    profile = customer_memory.get_profile(CUSTOMER_ID)
    assert profile["media_sent"].keys() == {"fee:quoc_te:2026-10", "fee:song_ngu:2026-10"}
    assert not profile.get("fee_asked")

    assert parent.images(parent.say("Mỹ Đình ạ", extracted={"interested_campus": "Mỹ Đình"})) == []
    assert "học phí" not in parent.notes[-1]


def test_fee_of_two_campuses_of_different_systems_is_one_image_each(parent, catalog):
    known(kid_age="3 tuổi", interested_campus="Chùa Láng, Kim Mã")

    sent = parent.say("học phí bao nhiêu ạ", extracted={"topics": ["Học phí"]})

    assert parent.images(sent) == [url("qt-fee-10"), url("sn-fee-10")]
    assert customer_memory.get_profile(CUSTOMER_ID)["media_sent"].keys() == {"fee:quoc_te:2026-10", "fee:song_ngu:2026-10"}


def test_facilities_of_two_campuses_go_one_campus_a_turn(parent, catalog):
    known(interested_campus="Mỹ Đình, Kim Mã")

    first = parent.images(parent.say("trường có sân chơi không ạ", extracted={"topics": ["Cơ sở vật chất"]}))
    second = parent.images(parent.say("cho em xem ảnh trường ạ", extracted={"topics": ["Cơ sở vật chất"]}))

    assert first == [url(f"md-csvc-{i}") for i in range(1, 5)]
    assert second == [url(f"km-csvc-{i}") for i in range(1, 5)]


def test_timetables_already_sent_are_not_promised_again_nor_left_to_a_consultant(parent, catalog):
    known(kid_age="4 tuổi", interested_campus="Chùa Láng, Kim Mã")
    assert parent.images(parent.say("Cho em xin thời khoá biểu ạ")) == [url("cl-tkb-36-60"), url("km-tkb-36-72")]

    assert parent.images(parent.say("Gửi thời khoá biểu 2 hệ nhé")) == []

    note = parent.notes[-1]
    assert "[HỆ THỐNG] Ảnh thời khoá biểu cơ sở Chùa Láng, Kim Mã đã gửi ở tin trước" in note, note
    assert "không gửi lại, không nói tư vấn viên sẽ gửi" in note and "gửi ảnh thời khoá biểu" not in note, note


# Phản hồi 2026-10-24: dòng "Nếu phụ huynh hỏi …" cho model nói "em gửi …", nhưng ảnh chỉ đi khi trích xuất gắn đúng
# chủ đề. Câu trả lời báo em gửi loại ảnh đó thì model gắn [SEND:<loại>] (dòng [HỆ THỐNG] dặn) và ảnh đi theo; chữ
# của câu trả lời không được đọc nữa (review vòng thời khoá biểu v3).
@pytest.mark.parametrize(
    ("reply", "images"),
    [
        ("Dạ thời khoá biểu lớp của bé em gửi ngay bên dưới ạ. [SEND:timetable]", ["km-tkb-36-72"]),
        ("Dạ em xin phép gửi Ba/Mẹ thời khóa biểu để tham khảo ạ. [SEND:timetable] [QUICK:visit_invite]", ["km-tkb-36-72"]),
        ("Dạ em xin phép gửi Ba/Mẹ thời khóa biểu để tham khảo ạ.", []),
        ("Dạ thời khoá biểu tư vấn viên sẽ gửi Ba/Mẹ ạ.", []),
        ("Dạ Ba/Mẹ có muốn em gửi thời khoá biểu lớp của bé không ạ?", []),
        ("Dạ em gửi Ba/Mẹ học phí ạ, Ba/Mẹ có muốn xem thời khoá biểu không ạ? [SEND:fee]", ["sn-fee-10"]),
    ],
)
def test_an_image_the_reply_tags_as_sent_goes_even_if_the_extraction_missed_its_topic(parent, catalog, reply, images):
    known(kid_age="4 tuổi", interested_campus="Kim Mã")

    sent = parent.say("Trường dạy chương trình gì ạ?", reply=reply)

    line = next(l for l in parent.notes[-1].splitlines() if "Nếu phụ huynh hỏi chương trình học" in l)
    assert "sau câu trả lời hệ thống gửi ảnh thời khoá biểu cơ sở Kim Mã" in line, line
    assert "thêm [SEND:timetable]" in line and "hỏi/mời xem ảnh thì không thêm" in line, line
    assert parent.images(sent) == [url(i) for i in images]


# Review vòng thời khoá biểu v2: câu mời "Ba/Mẹ có muốn em gửi ảnh cơ sở vật chất không ạ?" bị đọc là báo gửi, nên
# 4 ảnh đi ngay khi phụ huynh chưa trả lời. Câu hỏi, câu mời không có token nên không gửi.
@pytest.mark.parametrize(
    ("reply", "goes"),
    [
        ("Dạ Kim Mã có sân vườn rộng ạ. Ba/Mẹ có muốn em gửi ảnh cơ sở vật chất không ạ?", False),
        ("Dạ Kim Mã có sân vườn rộng ạ, em gửi Ba/Mẹ ảnh cơ sở vật chất nhé?", False),
        ("Dạ Kim Mã có sân vườn rộng ạ! Em gửi Ba/Mẹ ảnh cơ sở vật chất bên dưới ạ. [SEND:facilities]", True),
        ("Dạ em gửi Ba/Mẹ ảnh cơ sở vật chất ạ, Ba/Mẹ có muốn ghé tham quan không ạ? [SEND:facilities]", True),
    ],
)
def test_an_offer_to_send_images_is_not_saying_they_are_sent(parent, catalog, reply, goes):
    known(interested_campus="Kim Mã")

    sent = parent.say("Kim Mã có rộng không ạ", reply=reply)

    assert parent.images(sent) == ([url(f"km-csvc-{i}") for i in range(1, 5)] if goes else [])
    assert bool(customer_memory.get_profile(CUSTOMER_ID).get("media_sent")) == goes


# Review vòng thời khoá biểu v3: câu ghép báo gửi học phí rồi mời xem ảnh cơ sở vật chất kéo theo 4 ảnh cơ sở vật chất.
def test_a_reply_sending_the_fee_and_offering_the_facilities_sends_only_the_fee(parent, catalog):
    known(kid_age="4 tuổi", interested_campus="Kim Mã")
    shown = "Dạ em gửi Ba/Mẹ bảng học phí bên dưới ạ, Ba/Mẹ có muốn xem thêm ảnh cơ sở vật chất không ạ?"

    sent = parent.say("học phí bao nhiêu ạ", reply=f"{shown} [SEND:fee]", extracted={"topics": ["Học phí"]})

    assert sent == [("text", shown, None), ("image", url("sn-fee-10"), None)]
    assert customer_memory.get_profile(CUSTOMER_ID)["media_sent"].keys() == {"fee:song_ngu:2026-10"}


def test_the_send_token_is_neither_shown_to_the_parent_nor_kept_in_the_history(parent, catalog):
    known(kid_age="4 tuổi", interested_campus="Kim Mã")
    reply = "Dạ em gửi Ba/Mẹ thời khoá biểu lớp của bé ạ. [SEND:timetable] [QUICK:visit_invite]"

    sent = parent.say("Trường dạy chương trình gì ạ?", reply=reply)

    assert sent == [
        ("text", "Dạ em gửi Ba/Mẹ thời khoá biểu lớp của bé ạ.", None),
        ("image", url("km-tkb-36-72"), VISIT_BUTTONS),
    ]
    assert parent.history()[-1] == (
        "Dạ em gửi Ba/Mẹ thời khoá biểu lớp của bé ạ. [QUICK:visit_invite] [đã gửi ảnh thời khoá biểu cơ sở Kim Mã]"
    )


# Token của ảnh chưa đủ điều kiện (thiếu tuổi bé, thiếu cơ sở) không gửi gì và không để cờ chờ: phụ huynh không hỏi.
@pytest.mark.parametrize(
    ("profile", "reply", "flag"),
    [
        ({"interested_campus": "Kim Mã"}, "Dạ em gửi Ba/Mẹ thời khoá biểu ạ. [SEND:timetable]", "timetable_asked"),
        ({"kid_age": "4 tuổi"}, "Dạ em gửi Ba/Mẹ ảnh cơ sở vật chất ạ. [SEND:facilities]", "facilities_asked"),
        ({"interested_campus": "Kim Mã"}, "Dạ em gửi Ba/Mẹ bảng học phí ạ. [SEND:fee]", "fee_asked"),
    ],
    ids=["timetable-no-age", "facilities-no-campus", "fee-no-age"],
)
def test_a_send_token_of_an_image_not_ready_sends_nothing_and_waits_for_nothing(parent, catalog, profile, reply, flag):
    known(**profile)

    sent = parent.say("trường có xe đưa đón không ạ", reply=reply)

    assert sent == [("text", reply.split(" [SEND:")[0], None)]
    assert not customer_memory.get_profile(CUSTOMER_ID).get(flag)


def test_fee_image_the_reply_says_the_bot_sends_goes_without_the_fee_topic(parent, catalog):
    known(kid_age="3 tuổi", interested_campus="Mỹ Đình")

    reply = "Dạ em gửi Ba/Mẹ chính sách học phí cơ sở Mỹ Đình để tham khảo ạ. [SEND:fee]"
    sent = parent.say("vậy chi phí thế nào ạ", reply=reply)

    assert parent.images(sent) == [url("qt-fee-10")]


def test_daily_schedule_question_gets_the_timetable(parent, catalog):
    known(interested_campus="Kim Mã", kid_age="4 tuổi")

    assert parent.images(parent.say("Thời gian biểu trong ngày của bé thế nào ạ?")) == [url("km-tkb-36-72")]


# Review vòng thời khoá biểu v3: "lịch học thử 1 tuần/từ thứ 2/ba ngày" bị tính là thời khoá biểu ("thử" bỏ dấu là
# "thu", như "thứ"). Có dấu thì theo dấu của phụ huynh; không dấu thì chỉ "thu" + thứ trong tuần (2–7, hai, bay).
@pytest.mark.parametrize(
    "text",
    [
        "lịch học thử tuần sau thế nào ạ",
        "lịch học thử 1 tuần thế nào ạ",
        "lịch học thử từ thứ 2 tuần sau",
        "lịch học thử ba ngày",
        "lich hoc thu 1 tuan",
    ],
)
def test_trial_week_schedule_is_not_a_timetable_question(parent, catalog, text):
    known(interested_campus="Kim Mã", kid_age="4 tuổi")

    assert parent.images(parent.say(text)) == []
    assert "Sau câu trả lời này hệ thống gửi ảnh thời khoá biểu" not in parent.notes[-1], parent.notes[-1]
    assert not customer_memory.get_profile(CUSTOMER_ID).get("timetable_asked")


@pytest.mark.parametrize(
    "text",
    [
        "Lịch học thứ 2 đến thứ 6 thế nào ạ?",
        "lịch học thứ 2 đến thứ 6",
        "lịch học thứ hai của bé ra sao ạ",
        "lịch học thứ hai",
        "lich hoc thu 2 den thu 6",
        "Lịch học của bé thế nào ạ",
    ],
)
def test_weekday_schedule_question_gets_the_timetable(parent, catalog, text):
    known(interested_campus="Kim Mã", kid_age="4 tuổi")

    assert parent.images(parent.say(text)) == [url("km-tkb-36-72")]


TRIAL_WEEK_SENT = "Dạ em gửi Ba/Mẹ lịch học thử tuần sau ạ."


# Review vòng thời khoá biểu v2: câu "em gửi … lịch học thử" bị đọc là báo gửi thời khoá biểu.
def test_a_reply_sending_the_trial_week_does_not_send_the_timetable(parent, catalog):
    known(kid_age="4 tuổi", interested_campus="Kim Mã")

    assert parent.images(parent.say("cho em đăng ký học thử ạ", reply=TRIAL_WEEK_SENT)) == []


def test_a_reply_sending_the_trial_week_does_not_wait_for_the_kids_age(parent, catalog):
    known(interested_campus="Kim Mã")

    parent.say("cho em đăng ký học thử ạ", reply=TRIAL_WEEK_SENT)

    assert not customer_memory.get_profile(CUSTOMER_ID).get("timetable_asked")
    parent.say("dạ vâng")
    assert "[HỆ THỐNG] Chưa biết tuổi bé nên chưa gửi ảnh thời khoá biểu" not in parent.notes[-1], parent.notes[-1]


# --- cơ sở vật chất ---


def test_facilities_wait_for_the_campus_then_go_once_with_buttons_on_the_last_image(parent, catalog):
    sent = parent.say("trường có sân chơi không ạ", extracted={"topics": ["Cơ sở vật chất"]})
    assert parent.images(sent) == []
    assert "hỏi Ba/Mẹ quan tâm cơ sở nào" in parent.notes[-1]

    sent = parent.say("Em quan tâm cơ sở Kim Mã ạ")
    assert sent == [("text", SHOWN, None)] + [
        ("image", url(f"km-csvc-{i}"), VISIT_BUTTONS if i == 4 else None) for i in range(1, 5)
    ]
    assert "[HỆ THỐNG] Sau câu trả lời này hệ thống gửi ảnh cơ sở vật chất cơ sở Kim Mã" in parent.notes[-1]

    assert parent.images(parent.say("trường có sân chơi không ạ", extracted={"topics": ["Cơ sở vật chất"]})) == []


# Review 2026-10-23: hỏi lại cơ sở vật chất khi ảnh cơ sở đó đã gửi bật lại cờ facilities_asked và để nó kẹt, nên
# tin sau nhắc tới cơ sở khác (không hỏi ảnh) nhận 4 ảnh cơ sở đó.
def test_facilities_asked_again_after_the_images_went_does_not_wait_for_another_campus(parent, catalog):
    parent.say("trường có sân chơi không ạ", extracted={"topics": ["Cơ sở vật chất"]})
    sent = parent.say("Em quan tâm cơ sở Kim Mã ạ", extracted={"interested_campus": "Kim Mã"})
    assert parent.images(sent) == [url(f"km-csvc-{i}") for i in range(1, 5)]

    assert parent.images(parent.say("phòng học rộng không ạ", extracted={"topics": ["Cơ sở vật chất"]})) == []
    assert not customer_memory.get_profile(CUSTOMER_ID).get("facilities_asked")

    assert parent.images(parent.say("Bên Mỹ Đình có xa không ạ")) == []


def test_facilities_of_a_campus_without_images_do_not_wait(parent, catalog):
    known(interested_campus="Chùa Láng")

    assert parent.images(parent.say("trường có sân chơi không ạ", extracted={"topics": ["Cơ sở vật chất"]})) == []
    assert not customer_memory.get_profile(CUSTOMER_ID).get("facilities_asked")

    assert parent.images(parent.say("Bên Mỹ Đình có xa không ạ")) == []


# --- thực đơn ---


def test_menu_of_kim_ma_is_the_drive_image_not_the_old_sample(parent, catalog):
    known(interested_campus="Kim Mã")
    reply = "Dạ đây là thực đơn mẫu của Casa ạ. [IMAGES:static/thuc-don-mau.jpg][QUICK:age]"

    sent = parent.say("Cho em xem thực đơn của trường", reply=reply, extracted={"topics": ["Ăn uống/thực đơn"]})

    assert parent.images(sent) == [url("sn-menu")]
    assert "thực đơn hệ Song ngữ" in parent.notes[-1]


def test_menu_without_a_known_system_is_the_international_one(parent, catalog):
    sent = parent.say("bé ăn những gì ở trường ạ", extracted={"topics": ["Ăn uống/thực đơn"]})

    assert parent.images(sent) == [url("qt-menu")]


def test_menu_goes_once_to_each_parent(parent, catalog):
    known(interested_campus="Kim Mã")
    asks_menu = {"topics": ["Ăn uống/thực đơn"]}

    assert parent.images(parent.say("cho em xem thực đơn ạ", extracted=asks_menu)) == [url("sn-menu")]
    assert "menu:sn-menu" in customer_memory.get_profile(CUSTOMER_ID)["media_sent"]
    assert parent.images(parent.say("gửi lại thực đơn cho em với", extracted=asks_menu)) == []
    assert "thực đơn" not in parent.notes[-1], parent.notes[-1]


@pytest.mark.parametrize(("program", "menu"), [("song ngữ", "sn-menu"), ("Quốc tế", "qt-menu")])
def test_menu_without_a_campus_is_the_one_of_the_programme_the_parent_wants(parent, catalog, program, menu):
    known(interested_program=program)

    assert parent.images(parent.say("bé ăn những gì ạ", extracted={"topics": ["Ăn uống/thực đơn"]})) == [url(menu)]


# --- không có danh mục, lỗi, chuyển tư vấn viên ---


@pytest.mark.parametrize("off", ["empty catalog", "sync off"])
def test_without_drive_images_the_bot_behaves_as_before(parent, catalog, monkeypatch, off):
    if off == "sync off":
        monkeypatch.setattr(settings, "MEDIA_SYNC_ENABLED", False)
    else:
        monkeypatch.setattr(media, "_catalog", media._empty())
    known(kid_age="3 tuổi", interested_campus="Kim Mã", phone_declined=True)
    reply = "Dạ đây là thực đơn mẫu của Casa ạ. [IMAGES:static/thuc-don-mau.jpg][QUICK:age]"

    parent.say("học phí bao nhiêu ạ", extracted={"topics": ["Học phí", "Chương trình/phương pháp", "Cơ sở vật chất"]})
    sent = parent.say("Cho em xem thực đơn", reply=reply, extracted={"topics": ["Ăn uống/thực đơn"]})

    assert parent.images() == [f"{BASE_URL}/static/thuc-don-mau.jpg"]
    assert sent[0] == ("text", "Dạ đây là thực đơn mẫu của Casa ạ.", None)
    assert all("[HỆ THỐNG]" not in note for note in parent.notes)


@pytest.mark.parametrize(
    ("extracted", "escalate"), [({"topics": ["Học phí"]}, True), ({"topics": ["Học phí"], "upset": True}, False)],
    ids=["escalate", "upset"],
)
def test_no_image_when_the_parent_goes_to_a_consultant(parent, catalog, extracted, escalate):
    known(kid_age="3 tuổi", interested_campus="Kim Mã")

    sent = parent.say("học phí bao nhiêu ạ", reply="" if escalate else REPLY, extracted=extracted, escalate=escalate)

    assert parent.images(sent) == []
    assert "media_sent" not in customer_memory.get_profile(CUSTOMER_ID)


def test_a_failed_image_does_not_break_the_turn_and_goes_when_asked_again(parent, catalog, caplog):
    known(kid_age="3 tuổi", interested_campus="Kim Mã")
    parent.failing = {url("sn-fee-10")}

    with caplog.at_level(logging.WARNING):
        sent = parent.say("học phí bao nhiêu ạ", extracted={"topics": ["Học phí"]})

    # Ảnh của lượt là ảnh model được dặn báo gửi: mọi ảnh Drive lỗi thì xin lỗi, nút sang câu xin lỗi
    assert sent == [("text", SHOWN, None), ("text", main.IMAGES_FAILED_MESSAGE, VISIT_BUTTONS)]
    assert [r.levelname for r in caplog.records if "not sent" in r.getMessage()] == ["WARNING"]
    assert parent.history()[-1] == REPLY + " [ảnh học phí hệ Song ngữ (cơ sở Kim Mã) chưa gửi được]"
    parent.failing = set()
    assert parent.images(parent.say("học phí bao nhiêu ạ", extracted={"topics": ["Học phí"]})) == [url("sn-fee-10")]


TIMETABLE_SENT = "Dạ em gửi Ba/Mẹ thời khoá biểu lớp của bé để tham khảo ạ. [QUICK:visit_invite]"


def image_alerts(parent) -> list[str]:
    return [t for t in parent.telegram if t.startswith("⚠️ Gửi ảnh")]


# Hội thoại thật 2026-10-24: bot báo "em gửi ngay bên dưới" mà ảnh Drive không tới, không ai biết vì sao.
def test_a_failed_image_tells_the_admin_group_once_an_hour_without_the_parents_message(parent, catalog, monkeypatch):
    known(kid_age="4 tuổi", interested_campus="Kim Mã")
    parent.failing = {url("km-tkb-36-72"), url("sn-fee-10")}

    parent.say("Cho em xin thời khoá biểu ạ", reply=TIMETABLE_SENT)

    (alert,) = image_alerts(parent)
    assert "thời khoá biểu cơ sở Kim Mã" in alert and "HTTP 400" in alert and GRAPH_FETCH_ERROR in alert, alert
    assert "PUBLIC_BASE_URL" in alert and url("km-tkb-36-72") in alert, alert
    assert "Cho em xin" not in alert and CUSTOMER_ID not in alert

    parent.say("học phí bao nhiêu ạ", extracted={"topics": ["Học phí"]})
    assert len(image_alerts(parent)) == 1

    main._image_failure_alerted_at = datetime.now(timezone.utc) - timedelta(minutes=61)
    parent.say("cho em xin lại học phí ạ", extracted={"topics": ["Học phí"]})
    assert len(image_alerts(parent)) == 2 and "học phí hệ Song ngữ" in image_alerts(parent)[-1]


def test_parent_told_the_images_failed_when_every_drive_image_promised_failed(parent, catalog):
    known(kid_age="4 tuổi", interested_campus="Kim Mã")
    parent.failing = {url("km-tkb-36-72")}

    sent = parent.say("Cho em xin thời khoá biểu ạ", reply=TIMETABLE_SENT)

    assert sent == [
        ("text", "Dạ em gửi Ba/Mẹ thời khoá biểu lớp của bé để tham khảo ạ.", None),
        ("text", main.IMAGES_FAILED_MESSAGE, VISIT_BUTTONS),
    ]
    assert main.IMAGES_FAILED_MESSAGE == "Dạ ảnh em gửi đang bị lỗi chưa tới được, Ba/Mẹ nhắn lại em sau ít phút để em gửi lại nhé ạ."
    # Tin Telegram không nêu phụ huynh nào, nên câu xin lỗi không hứa tư vấn viên gửi lại; ảnh chưa tính là đã gửi,
    # phụ huynh hỏi lại thì bot gửi lại.
    assert "tư vấn viên" not in main.IMAGES_FAILED_MESSAGE


def failed(labels: str) -> str:
    return f"Dạ ảnh {labels} em gửi đang bị lỗi chưa tới được, Ba/Mẹ nhắn lại em sau ít phút để em gửi lại nhé ạ."


def test_apology_names_the_campus_whose_timetable_failed(parent, catalog):
    known(kid_age="4 tuổi", interested_campus="Chùa Láng, Kim Mã")
    parent.failing = {url("km-tkb-36-72")}

    sent = parent.say("Cho em xin thời khoá biểu ạ", reply=TIMETABLE_SENT)

    assert sent == [
        ("text", "Dạ em gửi Ba/Mẹ thời khoá biểu lớp của bé để tham khảo ạ.", None),
        ("image", url("cl-tkb-36-60"), None),
        ("text", failed("thời khoá biểu cơ sở Kim Mã"), VISIT_BUTTONS),
    ]
    assert len(image_alerts(parent)) == 1


FEE_AND_TIMETABLE = {"topics": ["Học phí", "Chương trình/phương pháp"]}
FEE_NOTE, TIMETABLE_NOTE_SENT = "[đã gửi ảnh học phí hệ Song ngữ (cơ sở Kim Mã)]", "[đã gửi ảnh thời khoá biểu cơ sở Kim Mã]"
TIMETABLE_FAILED_NOTE = "[ảnh thời khoá biểu cơ sở Kim Mã chưa gửi được]"
TIMETABLE_FOLLOWS = "Sau câu trả lời này hệ thống gửi ảnh thời khoá biểu cơ sở Kim Mã"


# Review 2026-10-24 (hồi quy so với 0bc19ee): lượt có ảnh học phí và thời khoá biểu mà chỉ thời khoá biểu lỗi thì bot
# im lặng (câu xin lỗi chỉ đi khi mọi ảnh lỗi) và xoá cờ chờ thời khoá biểu: phụ huynh không bao giờ biết ảnh thiếu.
def test_a_partly_failed_turn_apologises_for_the_image_that_failed_and_does_not_try_it_again_unasked(parent, catalog):
    known(kid_age="4 tuổi", interested_campus="Kim Mã")
    parent.failing = {url("km-tkb-36-72")}

    sent = parent.say("học phí và thời khoá biểu", extracted=FEE_AND_TIMETABLE)

    assert sent == [
        ("text", SHOWN, None),
        ("image", url("sn-fee-10"), None),
        ("text", failed("thời khoá biểu cơ sở Kim Mã"), VISIT_BUTTONS),
    ]
    assert parent.history()[-1] == f"{REPLY} {FEE_NOTE} {TIMETABLE_FAILED_NOTE}"
    assert not customer_memory.get_profile(CUSTOMER_ID).get("timetable_asked")

    parent.failing = set()
    assert parent.say("dạ vâng") == [("text", SHOWN, VISIT_BUTTONS)]
    assert TIMETABLE_FOLLOWS not in parent.notes[-1], parent.notes[-1]


def resend_line(kind: str, label: str) -> str:
    return (
        f"- [HỆ THỐNG] Ảnh {label} tin trước chưa gửi được. Nếu phụ huynh xin gửi lại thì báo em gửi lại và thêm "
        f"[SEND:{kind}]; phụ huynh không cần/nói chuyện khác thì không thêm, không nhắc lại ảnh."
    )


# (loại, tin xin ảnh, trích xuất, ảnh của lượt, nhãn): mỗi loại ảnh Drive, phụ huynh ở Kim Mã, bé 4 tuổi.
FAILED_KINDS = {
    "fee": ("học phí bao nhiêu ạ", {"topics": ["Học phí"]}, ["sn-fee-10"], "học phí hệ Song ngữ (cơ sở Kim Mã)"),
    "timetable": ("Cho em xin thời khoá biểu ạ", {}, ["km-tkb-36-72"], "thời khoá biểu cơ sở Kim Mã"),
    "facilities": ("cho em xem ảnh trường ạ", {"topics": ["Cơ sở vật chất"]}, [f"km-csvc-{i}" for i in range(1, 5)],
                   "cơ sở vật chất cơ sở Kim Mã"),
    "menu": ("cho em xem thực đơn", {"topics": ["Ăn uống/thực đơn"]}, ["sn-menu"], "thực đơn hệ Song ngữ"),
}


def fail_once(parent, kind: str) -> tuple[list[str], str]:
    """Lượt xin ảnh `kind` mà mọi ảnh của nó lỗi (bot xin lỗi); trả về URL các ảnh đó và nhãn trong ghi chú lịch sử."""
    known(kid_age="4 tuổi", interested_campus="Kim Mã")
    text, extracted, ids, label = FAILED_KINDS[kind]
    parent.failing = {url(i) for i in ids}
    assert parent.images(parent.say(text, extracted=extracted)) == []
    assert parent.history()[-1].endswith(f" [ảnh {label} chưa gửi được]")
    parent.failing = set()
    return [url(i) for i in ids], label


# Review 2026-10-24: code đọc chữ "gửi lại" của phụ huynh nên "không cần em gửi lại đâu" vẫn nhận ảnh. Ảnh lỗi ở tin
# trước được nhắc trong dòng [HỆ THỐNG]; ảnh chỉ đi lại khi model gắn [SEND:<loại>] (như mọi ảnh tuỳ chủ đề).
@pytest.mark.parametrize("kind", list(FAILED_KINDS))
def test_a_failed_image_goes_again_when_the_reply_to_the_parent_asking_tags_it(parent, catalog, kind):
    images, label = fail_once(parent, kind)

    sent = parent.say("em gửi lại ảnh đi", reply=f"Dạ em gửi lại Ba/Mẹ ảnh ạ. [SEND:{kind}] [QUICK:visit_invite]")

    assert parent.images(sent) == images
    assert resend_line(kind, label) in parent.notes[-1].splitlines(), parent.notes[-1]
    assert f"Sau câu trả lời này hệ thống gửi ảnh {label}" not in parent.notes[-1], parent.notes[-1]
    assert parent.history()[-1] == f"Dạ em gửi lại Ba/Mẹ ảnh ạ. [QUICK:visit_invite] [đã gửi ảnh {label}]"


@pytest.mark.parametrize("kind", list(FAILED_KINDS))
@pytest.mark.parametrize("text", ["không cần em gửi lại đâu, chị xem web rồi", "dạ vâng", "em gửi lại ảnh đi"])
def test_a_failed_image_does_not_go_again_when_the_reply_does_not_tag_it(parent, catalog, kind, text):
    _, label = fail_once(parent, kind)

    sent = parent.say(text)

    assert sent == [("text", SHOWN, VISIT_BUTTONS)]
    assert resend_line(kind, label) in parent.notes[-1].splitlines(), parent.notes[-1]
    assert f"Sau câu trả lời này hệ thống gửi ảnh {label}" not in parent.notes[-1], parent.notes[-1]
    assert "media_sent" not in customer_memory.get_profile(CUSTOMER_ID)


def test_only_the_image_that_failed_is_offered_again_after_a_partly_failed_turn(parent, catalog):
    known(kid_age="4 tuổi", interested_campus="Kim Mã")
    parent.failing = {url("km-tkb-36-72")}
    parent.say("học phí và thời khoá biểu", extracted=FEE_AND_TIMETABLE)
    parent.failing = set()

    sent = parent.say("em gửi lại ảnh đi", reply="Dạ em gửi lại Ba/Mẹ ảnh ạ. [SEND:timetable] [QUICK:visit_invite]")

    assert parent.images(sent) == [url("km-tkb-36-72")]
    resend = [line for line in parent.notes[-1].splitlines() if "tin trước chưa gửi được" in line]
    assert resend == [resend_line("timetable", "thời khoá biểu cơ sở Kim Mã")], parent.notes[-1]
    assert TIMETABLE_NOTE_SENT in parent.history()[-1]
    assert "timetable:km-tkb-36-72" in customer_memory.get_profile(CUSTOMER_ID)["media_sent"]
    parent.say("em gửi lại ảnh đi")
    assert "tin trước chưa gửi được" not in parent.notes[-1], parent.notes[-1]


# Thử thật trên Render 2026-10-24 (PUBLIC_BASE_URL sai, Graph "(#100) Upload failed"): ảnh cơ sở vật chất Chùa Láng
# lỗi, cờ facilities_asked còn chờ nên lượt sau (phụ huynh chỉ bấm "Dưới 2 tuổi") bot lại gửi, lại lỗi, lại xin lỗi.
# Ảnh lỗi không tự thử lại: chỉ gửi lại khi phụ huynh hỏi lại.
def test_failed_images_are_not_tried_again_until_the_parent_asks_again(parent, catalog, monkeypatch):
    chua_lang = [item(f"cl-csvc-{i}", f"IMG_{i:02}.jpg", QT, "CƠ SỞ CHÙA LÁNG", CSVC) for i in range(1, 7)]
    monkeypatch.setitem(media._catalog, "items", {**media._catalog["items"], **{i["id"]: i for i in chua_lang}})
    photos = [url(f"cl-csvc-{i}") for i in range(1, 5)]
    asks_photos = {"topics": ["Cơ sở vật chất"]}
    facilities_sent = "Sau câu trả lời này hệ thống gửi ảnh cơ sở vật chất cơ sở Chùa Láng"

    assert parent.images(parent.say("Cho em xin ảnh trường ạ", extracted=asks_photos)) == []
    parent.failing = set(photos)
    sent = parent.say("Chùa Láng", reply="Dạ em gửi Ba/Mẹ ảnh cơ sở Chùa Láng ạ.",
                      extracted={"interested_campus": "Chùa Láng"})
    assert facilities_sent in parent.notes[-1], parent.notes[-1]
    assert sent == [("text", "Dạ em gửi Ba/Mẹ ảnh cơ sở Chùa Láng ạ.", None), ("text", main.IMAGES_FAILED_MESSAGE, None)]

    sent = parent.say("Dưới 2 tuổi", extracted={"kid_age": "dưới 2 tuổi"})
    assert sent == [("text", SHOWN, VISIT_BUTTONS)]
    assert facilities_sent not in parent.notes[-1], parent.notes[-1]

    parent.failing = set()
    assert parent.images(parent.say("Cho em xin ảnh trường ạ", extracted=asks_photos)) == photos


def test_some_photos_of_the_facilities_failing_count_as_sent_without_an_apology(parent, catalog):
    known(interested_campus="Kim Mã")
    parent.failing = {url("km-csvc-2")}

    sent = parent.say("cho em xem ảnh trường ạ", reply="Dạ em gửi Ba/Mẹ ảnh cơ sở Kim Mã ạ.",
                      extracted={"topics": ["Cơ sở vật chất"]})

    assert sent == [("text", "Dạ em gửi Ba/Mẹ ảnh cơ sở Kim Mã ạ.", None),
                    *[("image", url(f"km-csvc-{i}"), None) for i in (1, 3, 4)]]
    assert "facilities:Kim Mã" in customer_memory.get_profile(CUSTOMER_ID)["media_sent"]
    assert len(image_alerts(parent)) == 1


def test_a_failed_qa_image_is_skipped_without_an_apology_nor_an_alert(parent, catalog, monkeypatch):
    monkeypatch.setattr(settings, "MEDIA_SYNC_ENABLED", False)
    parent.failing = {f"{BASE_URL}/static/thuc-don-mau.jpg"}

    sent = parent.say("Cho em xem thực đơn", reply="Dạ đây là thực đơn mẫu của Casa ạ. [IMAGES:static/thuc-don-mau.jpg]")

    assert sent == [("text", "Dạ đây là thực đơn mẫu của Casa ạ.", None)]
    assert parent.telegram == []


def test_every_turn_logs_the_drive_images_it_plans_to_send(parent, catalog, caplog):
    known(kid_age="4 tuổi", interested_campus="Kim Mã")

    with caplog.at_level(logging.INFO, logger="app.main"):
        parent.say("Cho em xin thời khoá biểu ạ", reply=TIMETABLE_SENT)
        parent.say("dạ vâng")

    planned = [r.getMessage() for r in caplog.records if "Drive images planned" in r.getMessage()]
    assert planned == [
        f"Drive images planned for {CUSTOMER_ID}: ['timetable:km-tkb-36-72']",
        f"Drive images planned for {CUSTOMER_ID}: []",
    ]


PAGE_TOKEN = "EAAG-page-token-media-replies"


@pytest.mark.parametrize("send", ["image", "message"])
def test_graph_errors_are_logged_and_raised_without_the_access_token(monkeypatch, caplog, send):
    monkeypatch.setattr(settings, "FB_PAGE_ACCESS_TOKEN", PAGE_TOKEN)
    error = {"error": {"message": f"(#100) Failed to fetch the file from the url access_token={PAGE_TOKEN}", "code": 100}}

    async def graph(self, request):
        assert request.url.params["access_token"] == PAGE_TOKEN
        return httpx.Response(400, content=json.dumps(error))

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", graph)
    call = messenger.send_image(CUSTOMER_ID, url("x")) if send == "image" else messenger.send_message(CUSTOMER_ID, "Dạ")

    with caplog.at_level(logging.ERROR), pytest.raises(messenger.GraphError) as raised:
        asyncio.run(call)

    assert raised.value.status == 400
    assert raised.value.message == "(#100) Failed to fetch the file from the url access_token=*** (code 100)"
    assert PAGE_TOKEN not in str(raised.value) and PAGE_TOKEN not in caplog.text
    assert "Failed to fetch the file" in caplog.text


def test_at_most_five_images_in_one_turn(parent, catalog):
    known(kid_age="3 tuổi", interested_campus="Kim Mã")

    sent = parent.say(
        "cho em xin học phí, thời khóa biểu, thực đơn và ảnh trường",
        extracted={"topics": ["Học phí", "Chương trình/phương pháp", "Ăn uống/thực đơn", "Cơ sở vật chất"]},
    )

    images = parent.images(sent)
    assert images[:3] == [url("sn-fee-10"), url("km-tkb-36-72"), url("sn-menu")]
    assert len(images) == 3  # 4 ảnh cơ sở vật chất không vừa: cờ facilities_asked chờ lượt sau
    assert sent[-1][2] == VISIT_BUTTONS


def test_images_that_did_not_fit_go_on_the_next_turn(parent, catalog):
    known(kid_age="3 tuổi", interested_campus="Kim Mã")
    parent.say(
        "cho em xin học phí, thời khóa biểu, thực đơn và ảnh trường",
        extracted={"topics": ["Học phí", "Chương trình/phương pháp", "Ăn uống/thực đơn", "Cơ sở vật chất"]},
    )

    sent = parent.say("dạ vâng")

    assert parent.images(sent) == [url(f"km-csvc-{i}") for i in range(1, 5)]
    assert not customer_memory.get_profile(CUSTOMER_ID).get("facilities_asked")


def test_a_menu_that_did_not_fit_waits_until_the_parent_asks_again(parent, catalog):
    known(kid_age="4 tuổi", interested_campus="Chùa Láng, Mỹ Đình, Kim Mã")
    asks_menu = {"topics": ["Ăn uống/thực đơn"]}

    sent = parent.say("cho em xin học phí, thời khoá biểu và thực đơn",
                      extracted={"topics": ["Học phí", "Chương trình/phương pháp", *asks_menu["topics"]]})

    assert len(parent.images(sent)) == 5 and url("qt-menu") not in parent.images(sent)  # 2 học phí + 3 thời khoá biểu
    assert parent.images(parent.say("dạ vâng")) == []  # thực đơn không có cờ chờ
    assert parent.images(parent.say("cho em xem thực đơn", extracted=asks_menu)) == [url("qt-menu")]


def test_a_reply_of_only_tokens_sends_only_the_images_with_the_buttons(parent, catalog):
    known(interested_campus="Kim Mã")

    sent = parent.say("thực đơn", reply="[IMAGES:static/thuc-don-mau.jpg][QUICK:age]",
                      extracted={"topics": ["Ăn uống/thực đơn"]})

    assert sent == [("image", url("sn-menu"), main.build_quick_replies("age"))]


@pytest.mark.parametrize("note", ["[đã gửi ảnh học phí hệ Song ngữ]", "[ảnh thời khoá biểu cơ sở Kim Mã chưa gửi được]"])
def test_model_copying_the_sent_note_is_not_shown_to_the_parent(parent, catalog, note):
    sent = parent.say("dạ vâng", reply=f"Dạ vâng ạ. {note} Ba/Mẹ cần thêm gì không ạ?")

    assert sent == [("text", "Dạ vâng ạ. Ba/Mẹ cần thêm gì không ạ?", None)]


# --- /test-chat giống tin Messenger thật ---


def test_test_chat_tells_the_model_which_images_follow_like_messenger(parent, catalog, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "tg-secret_media_replies")
    known(kid_age="3 tuổi", interested_campus="Kim Mã")
    parent.response = AIResponse(text=REPLY, should_escalate=False, model_used="fake-model")

    resp = TestClient(main.app).post(
        "/test-chat", params={"secret": "tg-secret_media_replies"},
        json={"message": "học phí bao nhiêu ạ", "user_id": CUSTOMER_ID},
    )

    assert resp.status_code == 200
    assert "[HỆ THỐNG] Nếu phụ huynh hỏi học phí/ưu đãi: sau câu trả lời hệ thống gửi ảnh học phí hệ Song ngữ" in (
        parent.notes[-1]
    )


def test_test_chat_keeps_no_send_token_in_the_history(parent, catalog, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "tg-secret_media_replies")
    reply = "Dạ em gửi Ba/Mẹ bảng học phí ạ. [SEND:fee] [QUICK:visit_invite]"
    parent.response = AIResponse(text=reply, should_escalate=False, model_used="fake-model")

    resp = TestClient(main.app).post(
        "/test-chat", params={"secret": "tg-secret_media_replies"},
        json={"message": "học phí bao nhiêu ạ", "user_id": CUSTOMER_ID},
    )

    assert resp.status_code == 200
    assert parent.history()[-1] == "Dạ em gửi Ba/Mẹ bảng học phí ạ. [QUICK:visit_invite]"


# --- lần đồng bộ đầu sau khởi động ---


SHEET_URL = "https://script.google.com/macros/s/MEDIA-REPLIES-TEST/exec"
TIMETABLE_NOTE = "[HỆ THỐNG] Sau câu trả lời này hệ thống gửi ảnh thời khoá biểu cơ sở Kim Mã"


def _png() -> bytes:
    out = BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(out, "PNG")
    return out.getvalue()


class SlowDrive:
    """Apps Script (type "media") và link tải Drive sau httpx. Apps Script trả lời sau `delay` giây, như sau khi
    Render Free thức dậy: ổ đĩa trống, lần đồng bộ đầu chạy nền."""

    def __init__(self):
        self.delay = 0.3
        files = [{"id": i["id"], "name": i["name"], "mimeType": "image/png", "modified": i["modified"],
                  "path": i["path"]} for i in CATALOG]
        self.answer = {"ok": True, "files": files}
        self.listed = 0

    async def respond(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "script.google.com":
            self.listed += 1
            await asyncio.sleep(self.delay)
            return httpx.Response(200, json=self.answer)
        if request.url.host == "drive.google.com":
            return httpx.Response(200, content=_png(), headers={"Content-Type": "image/png"})
        if request.url.host == httpx.URL(BASE_URL).host:  # the link check after a sync (media.check_link)
            return httpx.Response(200, content=b"\xff\xd8jpeg", headers={"Content-Type": "image/jpeg"})
        raise AssertionError(f"unexpected request {request.url}")


@pytest.fixture
def drive(monkeypatch):
    fake = SlowDrive()

    async def handle_async(self, request):
        return await fake.respond(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle_async)
    monkeypatch.setattr(settings, "MEDIA_SYNC_ENABLED", True)
    monkeypatch.setattr(settings, "LEADS_SHEET_WEBHOOK_URL", SHEET_URL)
    monkeypatch.setattr(settings, "LEADS_SHEET_TOKEN", "sheet-token-media-replies")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", BASE_URL)
    monkeypatch.setattr(settings, "MEDIA_FIRST_SYNC_WAIT", 30)
    monkeypatch.setattr(media, "_first_sync", None)
    monkeypatch.setattr(media, "_link_alerted_at", None)
    return fake


def right_after_start(parent, *texts) -> list[tuple[list, float]]:
    """The bot starts (lifespan: media.start_sync_task) and the parent sends `texts` at once, one after the other;
    (what the bot sent, seconds) per message."""
    parent.response = AIResponse(text=REPLY, should_escalate=False, model_used="fake-model")

    async def run():
        task = media.start_sync_task()
        turns = []
        try:
            for text in texts:
                before, started = len(parent.sent), time.monotonic()
                await main.process_message(CUSTOMER_ID, text)
                turns.append((parent.sent[before:], time.monotonic() - started))
        finally:
            if task:
                task.cancel()
        return turns

    return asyncio.run(run())


def first_sync_warnings(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and "first sync" in r.getMessage()]


# Người vận hành 2026-10-24: sau mỗi lần deploy hay Render Free thức dậy, tin hỏi thời khoá biểu đầu tiên được trả
# lời như chưa có ảnh ([ESCALATE]) vì lần đồng bộ đầu còn chạy nền. Lượt đó chờ đồng bộ xong rồi mới trả lời.
def test_a_message_right_after_start_waits_for_the_first_sync_and_gets_the_timetable(parent, drive, caplog):
    known(interested_campus="Kim Mã", kid_age="3-5 tuổi")

    with caplog.at_level(logging.INFO):
        [(sent, seconds)] = right_after_start(parent, "Cho em xin thời khoá biểu ạ")

    assert sent == [("text", SHOWN, None), ("image", url("km-tkb-36-72"), VISIT_BUTTONS)]
    assert TIMETABLE_NOTE in parent.notes[-1], parent.notes[-1]
    assert seconds >= drive.delay
    first = [r for r in caplog.records if r.name == "app.media" and "first sync" in r.getMessage()]
    assert [r.levelname for r in first] == ["INFO"]
    assert f"{len(CATALOG)} images" in first[0].getMessage(), first[0].getMessage()
    assert first_sync_warnings(caplog) == []


def test_a_first_sync_slower_than_the_wait_still_gets_an_answer_without_images(parent, drive, monkeypatch, caplog):
    known(interested_campus="Kim Mã", kid_age="3-5 tuổi")
    drive.delay = 30
    monkeypatch.setattr(settings, "MEDIA_FIRST_SYNC_WAIT", 0.2)

    with caplog.at_level(logging.WARNING):
        [(sent, seconds)] = right_after_start(parent, "Cho em xin thời khoá biểu ạ")

    assert parent.images(sent) == [] and sent[0][1] == SHOWN
    assert 0.2 <= seconds < 5
    assert len(first_sync_warnings(caplog)) == 1


# Review 2026-10-24: mỗi tin tới trong lúc lần đồng bộ đầu còn chạy đều chờ đủ MEDIA_FIRST_SYNC_WAIT (60 giây), tin
# sau chờ thêm 60 giây nữa. Hạn là một: lúc bắt đầu lần đồng bộ đầu + MEDIA_FIRST_SYNC_WAIT; tin tới sau hạn không chờ.
def test_every_message_waits_for_the_first_sync_until_one_deadline(parent, drive, monkeypatch, caplog):
    known(interested_campus="Kim Mã", kid_age="3-5 tuổi")
    drive.delay = 30
    monkeypatch.setattr(settings, "MEDIA_FIRST_SYNC_WAIT", 0.6)
    parent.response = AIResponse(text=REPLY, should_escalate=False, model_used="fake-model")

    async def run():
        task = media.start_sync_task()
        seconds = []
        try:
            await asyncio.sleep(0.3)
            for text in ("Cho em xin thời khoá biểu ạ", "dạ vâng", "học phí bao nhiêu ạ"):
                started = time.monotonic()
                await main.process_message(CUSTOMER_ID, text)
                seconds.append(time.monotonic() - started)
        finally:
            task.cancel()
        return seconds

    with caplog.at_level(logging.WARNING):
        first, *later = asyncio.run(run())

    assert 0.2 <= first < 0.5  # came 0.3 s after the sync started: waits what is left of the 0.6 s
    assert all(s < 0.3 for s in later), later
    assert parent.images() == []
    assert len(first_sync_warnings(caplog)) == 1


# Messenger tắt "đang soạn" sau ~20 giây, còn lượt chờ lần đồng bộ đầu tới MEDIA_FIRST_SYNC_WAIT (60 giây): phụ huynh
# thấy bot im. Trong lúc chờ, bot bật lại "đang soạn" mỗi TYPING_REFRESH_EVERY giây.
def test_waiting_for_the_first_sync_keeps_the_typing_indicator_on(parent, drive, monkeypatch):
    known(interested_campus="Kim Mã", kid_age="3-5 tuổi")
    typing = []

    async def send_typing_indicator(recipient_id, action="typing_on"):
        typing.append((recipient_id, action))

    monkeypatch.setattr(main, "send_typing_indicator", send_typing_indicator)
    monkeypatch.setattr(main, "TYPING_REFRESH_EVERY", 0.05)
    drive.delay = 0.3

    parent.response = AIResponse(text=REPLY, should_escalate=False, model_used="fake-model")

    async def run():
        task = media.start_sync_task()
        try:
            await main.process_message(CUSTOMER_ID, "Cho em xin thời khoá biểu ạ")
            after = len(typing)
            await asyncio.sleep(0.2)
        finally:
            task.cancel()
        return after

    after = asyncio.run(run())

    assert parent.images() == [url("km-tkb-36-72")]
    assert len(typing) >= 3 and set(typing) == {(CUSTOMER_ID, "typing_on")}, typing
    assert len(typing) == after  # stopped with the wait

    typing.clear()
    parent.say("dạ vâng")  # first sync done: no wait, the one typing_on of every turn
    assert typing == [(CUSTOMER_ID, "typing_on")]


@pytest.mark.parametrize("off", ["MEDIA_SYNC_ENABLED", "LEADS_SHEET_WEBHOOK_URL"])
def test_with_media_sync_off_a_message_does_not_wait(parent, drive, monkeypatch, caplog, off):
    drive.delay = 30
    monkeypatch.setattr(settings, off, False if off == "MEDIA_SYNC_ENABLED" else "")

    with caplog.at_level(logging.WARNING):
        [(sent, seconds)] = right_after_start(parent, "Cho em xin thời khoá biểu ạ")

    assert sent[0][1] == SHOWN and seconds < 5
    assert drive.listed == 0
    assert first_sync_warnings(caplog) == []


def test_a_failed_first_sync_answers_then_and_no_later_message_waits(parent, drive, caplog):
    known(interested_campus="Kim Mã", kid_age="3-5 tuổi")
    drive.answer = {"ok": False, "error": "Drive folder not found"}

    with caplog.at_level(logging.INFO):
        turns = right_after_start(parent, "Cho em xin thời khoá biểu ạ", "dạ vâng")

    assert [parent.images(sent) for sent, _ in turns] == [[], []]
    assert turns[0][1] >= drive.delay
    assert turns[1][1] < 5  # the next sync is MEDIA_SYNC_MINUTES away: waiting for it would take MEDIA_FIRST_SYNC_WAIT
    assert drive.listed == 1
    assert any(r.levelname == "INFO" and "first sync" in r.getMessage() for r in caplog.records)
    assert first_sync_warnings(caplog) == []


def test_images_kept_on_disk_from_before_the_restart_are_used_without_waiting(parent, drive, monkeypatch, caplog):
    known(interested_campus="Kim Mã", kid_age="3-5 tuổi")
    folder = Path(settings.MEDIA_DIR)
    folder.mkdir(parents=True)
    for i in CATALOG:
        (folder / f"{i['id']}.jpg").write_bytes(_png())
    media._write_catalog({**media._empty(), "synced_at": "2026-10-23T08:00:00+07:00", "items": {i["id"]: i for i in CATALOG}})
    monkeypatch.setattr(media, "_catalog", media.load_catalog())  # như lúc import sau khi restart
    drive.delay = 30

    with caplog.at_level(logging.WARNING):
        [(sent, seconds)] = right_after_start(parent, "Cho em xin thời khoá biểu ạ")

    assert parent.images(sent) == [url("km-tkb-36-72")]
    assert seconds < 5
    assert first_sync_warnings(caplog) == []


def test_test_chat_right_after_start_waits_for_the_first_sync(parent, drive, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "tg-secret_media_replies")
    known(interested_campus="Kim Mã", kid_age="3-5 tuổi")
    parent.response = AIResponse(text=REPLY, should_escalate=False, model_used="fake-model")

    with TestClient(main.app) as client:
        resp = client.post(
            "/test-chat", params={"secret": "tg-secret_media_replies"},
            json={"message": "Cho em xin thời khoá biểu ạ", "user_id": CUSTOMER_ID},
        )

    assert resp.status_code == 200
    assert TIMETABLE_NOTE in parent.notes[-1], parent.notes[-1]

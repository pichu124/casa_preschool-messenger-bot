"""Bot gửi ảnh Drive (app/media.py) cho phụ huynh đúng lúc: học phí, thời khoá biểu, cơ sở vật chất, thực đơn.

Danh mục ảnh là bản giả theo cây thư mục thật của trường; model trả lời và model trích xuất là fake, nên test đọc được
cả dòng [HỆ THỐNG] mà code đưa vào khối nhắc nhở. process_message gọi thẳng bằng asyncio.run.
"""

import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

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


def test_fee_without_the_age_goes_only_to_a_parent_asking_the_fee(parent, catalog):
    known(interested_campus="Kim Mã")
    parent.say("Em quan tâm Kim Mã", reply=ASKED_PHONE)

    sent = parent.say("trường có xe đưa đón không", reply="Dạ em gửi Ba/Mẹ chính sách học phí cơ sở Kim Mã ạ.")

    assert parent.images(sent) == []
    # Phụ huynh không hỏi học phí: không chờ tuổi bé để rồi tự gửi ảnh học phí ở lượt sau
    assert not customer_memory.get_profile(CUSTOMER_ID).get("fee_asked")
    assert parent.images(parent.say("bé nhà em 4 tuổi ạ", extracted={"kid_age": "4 tuổi"})) == []


def test_parent_not_leaving_the_phone_and_naming_the_fee_gets_it_when_the_reply_sends_it(parent, catalog):
    known(interested_campus="Kim Mã")
    parent.say("Em quan tâm Kim Mã", reply=ASKED_PHONE)

    sent = parent.say("em cứ báo học phí luôn đi", reply="Dạ em gửi Ba/Mẹ chính sách học phí cơ sở Kim Mã ạ.")

    assert parent.images(sent) == [url("sn-fee-10")]


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
# chủ đề. Câu trả lời đã báo em gửi loại ảnh đó thì ảnh đi theo.
@pytest.mark.parametrize(
    ("reply", "goes"),
    [
        ("Dạ thời khoá biểu lớp của bé em gửi ngay bên dưới ạ.", True),
        ("Dạ em xin phép gửi Ba/Mẹ thời khóa biểu để tham khảo ạ.", True),
        ("Dạ thời khoá biểu tư vấn viên sẽ gửi Ba/Mẹ ạ.", False),
        ("Dạ em chưa gửi được thời khoá biểu ạ.", False),
        ("Dạ em gửi Ba/Mẹ thông tin chương trình ạ. Thời khoá biểu thì theo từng lớp ạ.", False),
        ("Dạ Ba/Mẹ có muốn em gửi thời khoá biểu lớp của bé không ạ?", False),
    ],
)
def test_an_image_the_reply_says_the_bot_sends_goes_even_if_the_extraction_missed_its_topic(parent, catalog, reply, goes):
    known(kid_age="4 tuổi", interested_campus="Kim Mã")

    sent = parent.say("Trường dạy chương trình gì ạ?", reply=reply)

    assert "Nếu phụ huynh hỏi chương trình học/Cambridge/thời khoá biểu: sau câu trả lời" in parent.notes[-1]
    assert parent.images(sent) == ([url("km-tkb-36-72")] if goes else [])


# Review vòng thời khoá biểu v2: câu mời "Ba/Mẹ có muốn em gửi ảnh cơ sở vật chất không ạ?" bị đọc là báo gửi, nên
# 4 ảnh đi ngay khi phụ huynh chưa trả lời. Câu hỏi, câu mời không phải báo gửi.
@pytest.mark.parametrize(
    ("reply", "goes"),
    [
        ("Dạ Kim Mã có sân vườn rộng ạ. Ba/Mẹ có muốn em gửi ảnh cơ sở vật chất không ạ?", False),
        ("Dạ Kim Mã có sân vườn rộng ạ, em gửi Ba/Mẹ ảnh cơ sở vật chất nhé?", False),
        ("Dạ Ba/Mẹ có muốn em gửi ảnh trường không ạ", False),
        ("Dạ Kim Mã có sân vườn rộng ạ! Em gửi Ba/Mẹ ảnh cơ sở vật chất bên dưới ạ.", True),
        ("Dạ em gửi Ba/Mẹ ảnh cơ sở vật chất ạ, Ba/Mẹ có muốn ghé tham quan không ạ?", True),
    ],
)
def test_an_offer_to_send_images_is_not_saying_they_are_sent(parent, catalog, reply, goes):
    known(interested_campus="Kim Mã")

    sent = parent.say("Kim Mã có rộng không ạ", reply=reply)

    assert parent.images(sent) == ([url(f"km-csvc-{i}") for i in range(1, 5)] if goes else [])
    assert bool(customer_memory.get_profile(CUSTOMER_ID).get("media_sent")) == goes


def test_fee_image_the_reply_says_the_bot_sends_goes_without_the_fee_topic(parent, catalog):
    known(kid_age="3 tuổi", interested_campus="Mỹ Đình")

    sent = parent.say("vậy chi phí thế nào ạ", reply="Dạ em gửi Ba/Mẹ chính sách học phí cơ sở Mỹ Đình để tham khảo ạ.")

    assert parent.images(sent) == [url("qt-fee-10")]


def test_daily_schedule_question_gets_the_timetable(parent, catalog):
    known(interested_campus="Kim Mã", kid_age="4 tuổi")

    assert parent.images(parent.say("Thời gian biểu trong ngày của bé thế nào ạ?")) == [url("km-tkb-36-72")]


def test_trial_week_schedule_is_not_a_timetable_question(parent, catalog):
    assert parent.images(parent.say("lịch học thử tuần sau thế nào ạ")) == []


# "lịch học thứ 2–6" bỏ dấu giống "lịch học thử": thứ trong tuần vẫn là hỏi thời khoá biểu.
@pytest.mark.parametrize("text", ["Lịch học thứ 2 đến thứ 6 thế nào ạ?", "lịch học thứ hai của bé ra sao ạ"])
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


def test_a_failed_image_does_not_break_the_turn_and_is_tried_again_later(parent, catalog, caplog):
    known(kid_age="3 tuổi", interested_campus="Kim Mã")
    parent.failing = {url("sn-fee-10")}

    with caplog.at_level(logging.WARNING):
        sent = parent.say("học phí bao nhiêu ạ", extracted={"topics": ["Học phí"]})

    assert sent == [("text", SHOWN, None)]
    assert [r.levelname for r in caplog.records if "not sent" in r.getMessage()] == ["WARNING"]
    assert parent.history()[-1] == REPLY
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


def test_no_apology_when_one_of_the_images_went(parent, catalog):
    known(kid_age="4 tuổi", interested_campus="Chùa Láng, Kim Mã")
    parent.failing = {url("km-tkb-36-72")}

    sent = parent.say("Cho em xin thời khoá biểu ạ", reply=TIMETABLE_SENT)

    assert parent.images(sent) == [url("cl-tkb-36-60")]
    assert ("text", main.IMAGES_FAILED_MESSAGE, VISIT_BUTTONS) not in sent
    assert len(image_alerts(parent)) == 1


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
    assert len(images) == 3  # 4 ảnh cơ sở vật chất không vừa: chờ lần hỏi cơ sở vật chất sau
    assert sent[-1][2] == VISIT_BUTTONS


def test_model_copying_the_sent_note_is_not_shown_to_the_parent(parent, catalog):
    sent = parent.say("dạ vâng", reply="Dạ vâng ạ. [đã gửi ảnh học phí hệ Song ngữ] Ba/Mẹ cần thêm gì không ạ?")

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

"""Bot gửi ảnh Drive (app/media.py) cho phụ huynh đúng lúc: học phí, thời khoá biểu, cơ sở vật chất, thực đơn.

Danh mục ảnh là bản giả theo cây thư mục thật của trường; model trả lời và model trích xuất là fake, nên test đọc được
cả dòng [HỆ THỐNG] mà code đưa vào khối nhắc nhở. process_message gọi thẳng bằng asyncio.run.
"""

import asyncio
import logging
from datetime import date

import pytest

import app.main as main
from app import customer_memory, escalation, media
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
    item("md-tkb-15-36", "TKB 15 tháng - 3 tuổi.png", QT, "CƠ SỞ MỸ ĐÌNH", TKB),
    item("md-tkb-36-60", "TKB 3-5 tuổi.png", QT, "CƠ SỞ MỸ ĐÌNH", TKB),
    *[item(f"md-csvc-{i}", f"IMG_{i:02}.jpg", QT, "CƠ SỞ MỸ ĐÌNH", CSVC) for i in range(1, 7)],
    item("sn-fee-10", "Học phí Kim Mã - Tháng 10.png", SN, "HỌC PHÍ THÁNG 10"),
    item("sn-menu", "Thực đơn Kim Mã.png", SN, "THỰC ĐƠN"),
    item("km-tkb-15-36", "TKB 15 tháng  -3 tuổi.png", SN, "CƠ SỞ KIM MÃ", TKB),
    item("km-tkb-36-72", "TKB 3-6 tuổi.png", SN, "CƠ SỞ KIM MÃ", TKB),
    *[item(f"km-csvc-{i}", f"IMG_{i:02}.jpg", SN, "CƠ SỞ KIM MÃ", CSVC) for i in range(1, 6)],
]


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
            raise RuntimeError("Messenger image API error: 400")
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
        ("sinh năm 2023", None),
        ("bé nhà em", None),
        ("", None),
    ],
)
def test_kid_age_is_read_as_months(kid_age, months):
    assert media.age_months(kid_age) == months


@pytest.mark.parametrize(
    ("text", "campus"),
    [("Em quan tâm cơ sở Kim Mã ạ", "Kim Mã"), ("co so my dinh a", "Mỹ Đình"), ("cơ sở chùa láng", "Chùa Láng"),
     ("Kim Mã hay Mỹ Đình gần hơn ạ", None), ("trường ở đâu ạ", None), ("", None)],
)
def test_campus_named_in_a_message(text, campus):
    assert media.campus_in(text) == campus


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


def test_programme_question_without_age_or_campus_gets_the_3_to_5_timetable_of_my_dinh(parent, catalog):
    sent = parent.say("Trường dạy chương trình gì ạ?", extracted={"topics": ["Chương trình/phương pháp"]})

    assert parent.images(sent) == [url("md-tkb-36-60")]
    note = parent.notes[-1]
    assert "thời khoá biểu cơ sở Mỹ Đình" in note and "tuổi bé" in note and "cơ sở" in note
    assert "[đã gửi ảnh thời khoá biểu cơ sở Mỹ Đình" in parent.history()[-1]

    assert parent.images(parent.say("Trường dạy chương trình gì ạ?",
                                    extracted={"topics": ["Chương trình/phương pháp"]})) == []


def test_cambridge_question_gets_the_timetable_of_the_kids_age_and_campus(parent, catalog):
    known(kid_age="20 tháng", interested_campus="Kim Mã")

    sent = parent.say("Cambridge ở trường học thế nào ạ", extracted={"topics": ["Tiếng Anh/GV nước ngoài"]})

    assert parent.images(sent) == [url("km-tkb-15-36")]
    assert "[HỆ THỐNG] Sau câu trả lời này hệ thống gửi ảnh thời khoá biểu cơ sở Kim Mã" in parent.notes[-1]


@pytest.mark.parametrize(
    ("program", "timetable", "campus"),
    [("song ngữ", "km-tkb-36-72", "Kim Mã"), ("Hệ Song Ngữ", "km-tkb-36-72", "Kim Mã"),
     ("quốc tế", "md-tkb-36-60", "Mỹ Đình"), (None, "md-tkb-36-60", "Mỹ Đình")],
)
def test_timetable_without_a_campus_follows_the_programme_the_parent_wants(parent, catalog, program, timetable, campus):
    if program:
        known(interested_program=program)

    sent = parent.say("Trường dạy chương trình gì ạ?", extracted={"topics": ["Chương trình/phương pháp"]})

    assert parent.images(sent) == [url(timetable)]
    assert f"thời khoá biểu cơ sở {campus}" in parent.notes[-1]


def test_trial_week_schedule_is_not_a_timetable_question(parent, catalog):
    assert parent.images(parent.say("lịch học thử tuần sau thế nào ạ")) == []


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

"""Ma trận trường hợp gửi ảnh cho phụ huynh và các ca của bộ eval `media` (scripts/eval_chat.py media).

Luật: docs/quyet-dinh-noi-dung.md, mục "Ảnh gửi phụ huynh"; code: `_plan_images`, `_media_note`,
`_send_reply_with_images`, `_record_images`, `_wait_for_first_media_sync`, token `[SEND:<loại>]` trong app/main.py,
`ready` trong app/media.py, `media_note` trong app/ai_engine.py. Bản người đọc: docs/ma-tran-gui-anh.md (tests/test_eval_media.py giữ hai bản khớp nhau).

Mỗi dòng MATRIX là một nhánh của luật, có một bộ kiểm:
- "eval": câu chữ hoặc hành vi của model (chủ đề trích xuất, tuổi/cơ sở đọc được, token, [ESCALATE]) quyết định kết
  quả; MEDIA_CASES có ca cùng mã, chạy luồng thật của bot với model thật.
- "pytest": kết quả do code quyết định khi đã biết chủ đề/token (model giả); `test` là tên test trong tests/.
- "harness": cần app thật qua HTTP (Graph trả lỗi, ảnh phục vụ ở /static/media, cấu hình môi trường); mã nằm trong
  .claude/skills/verify-casa-bot/features/media.md.

File này chỉ là dữ liệu: không gọi mạng, không đọc data/customers.json.
"""
from dataclasses import dataclass, field
from datetime import date

from app import media

# Ngày "hôm nay" giờ Việt Nam của mọi ca: danh mục giả có ảnh học phí tháng 10, tuổi theo năm sinh tính tới ngày này.
TODAY = date(2026, 10, 24)
BASE_URL = "https://bot.eval.test"
QA_MENU_IMAGE = "static/thuc-don-mau.jpg"  # ảnh thực đơn mẫu của Q&A, gửi khi Drive chưa có ảnh thực đơn

QT, SN = "HỆ QUỐC TẾ", "HỆ SONG NGỮ"
TKB, CSVC = "THỜI KHÓA BIỂU", "ẢNH CƠ SỞ VẬT CHẤT"
CL, MD, KM = "CƠ SỞ CHÙA LÁNG", "CƠ SỞ MỸ ĐÌNH", "CƠ SỞ KIM MÃ"


def _item(file_id: str, name: str, *path: str) -> dict:
    return {"id": file_id, "name": name, "path": list(path), "modified": "2026-10-01T02:00:00.000Z",
            **media.classify(list(path), name)}


def catalog_items(variant: str = "default") -> list[dict]:
    """Danh mục ảnh Drive giả theo cây thư mục thật của trường: học phí 2 hệ, thực đơn 2 hệ, thời khoá biểu 3 cơ sở
    theo nhóm tuổi, cơ sở vật chất 3 cơ sở. "stale_fee": học phí chỉ có tháng 9 (ảnh cũ); "no_menu": Drive chưa có
    ảnh thực đơn."""
    month = 9 if variant == "stale_fee" else 10
    items = [
        _item(f"qt-fee-{month}", "7.png", QT, f"HỌC PHÍ THÁNG {month}"),
        _item(f"sn-fee-{month}", f"Học phí Kim Mã - Tháng {month}.png", SN, f"HỌC PHÍ THÁNG {month}"),
        _item("cl-tkb-15-36", "TKB 15 tháng - 3 tuổi.jpg", QT, CL, TKB),
        _item("cl-tkb-36-60", "TKB 3-5 tuổi.jpg", QT, CL, TKB),
        _item("md-tkb-15-36", "TKB 15 tháng - 3 tuổi.png", QT, MD, TKB),
        _item("md-tkb-36-60", "TKB 3-5 tuổi.png", QT, MD, TKB),
        _item("km-tkb-15-36", "TKB 15 tháng  -3 tuổi.png", SN, KM, TKB),
        _item("km-tkb-36-72", "TKB 3-6 tuổi.png", SN, KM, TKB),
        *[_item(f"cl-csvc-{i}", f"IMG_{i:02}.jpg", QT, CL, CSVC) for i in range(1, 5)],
        *[_item(f"md-csvc-{i}", f"IMG_{i:02}.jpg", QT, MD, CSVC) for i in range(1, 7)],
        *[_item(f"km-csvc-{i}", f"IMG_{i:02}.jpg", SN, KM, CSVC) for i in range(1, 6)],
    ]
    if variant != "no_menu":
        items += [_item("qt-menu", "Thực đơn mẫu.jpg", QT, "THỰC ĐƠN"), _item("sn-menu", "Thực đơn Kim Mã.png", SN, "THỰC ĐƠN")]
    return items


CATALOG_VARIANTS = ("default", "stale_fee", "no_menu")


def image_kind(image_id: str) -> str:
    """Loại ảnh (khoá của TOPICS_OF_IMAGE) của một id ảnh trong ca: id fixture, hoặc ảnh thực đơn mẫu của Q&A."""
    if image_id == QA_MENU_IMAGE:
        return "menu"
    return next(i["kind"] for v in CATALOG_VARIANTS for i in catalog_items(v) if i["id"] == image_id)


@dataclass(frozen=True)
class Row:
    code: str
    group: str
    case: str  # trường hợp
    expected: str  # ảnh nào đi, câu chữ phải/không được có gì
    checker: str  # "eval" | "pytest" | "harness"
    test: str = ""  # pytest: "tests/<file>.py::<tên test>"


@dataclass
class Step:
    """Một lượt phụ huynh nhắn: `say` (tự gõ) hoặc `tap` (bấm nút "<key>:<số thứ tự>", bot nhận nghĩa của nút)."""

    say: str = ""
    tap: str = ""
    images: tuple[str, ...] = ()  # id ảnh đi ra lượt này, chính xác (không thừa, không thiếu)
    escalate: bool = False  # có thẻ Telegram chuyển tư vấn viên
    alerts: tuple[str, ...] = ()  # tin Telegram cho admin về ảnh (chuỗi con); trống = không tin nào
    # Câu trả lời giám khảo (khoá của eval_chat.JUDGE_KEYS) mong đợi ở lượt này, vd {"asks_age": True}; thêm vào mặc định
    # của eval_chat.expected_answers (không ảnh: không hứa gửi ảnh; có ảnh: báo em gửi ảnh, không nói không gửi được ảnh;
    # mọi lượt: không nói tư vấn viên sẽ gửi ảnh).
    expect: dict = field(default_factory=dict)
    any_of: list[tuple[str, ...]] = field(default_factory=list)  # mỗi nhóm phải có ít nhất 1 cụm
    none_of: tuple[str, ...] = ()
    # Trích xuất đúng mong đợi của tin này: chỉ model giả của tests/test_eval_media.py dùng (eval thật chỉ in ra
    # bản model trích xuất để so).
    extract: dict = field(default_factory=dict)


@dataclass
class MediaCase:
    steps: list[Step]
    profile: dict = field(default_factory=dict)  # hồ sơ bot đã có trước lượt đầu
    history: list[tuple[str, str]] = field(default_factory=list)  # (tin phụ huynh, tin bot) trước lượt đầu
    catalog: str = "default"


# Câu bot đã gửi trước lượt đầu của ca; không xin SĐT trừ khi ca cần ("Ba/Mẹ để lại SĐT/Zalo" bật luật từ chối số).
ASK_PHONE_BOT = "Nếu tiện, Ba/Mẹ để lại SĐT/Zalo để em gửi bảng học phí chi tiết nhé ạ? [QUICK:phone]"
OK_BOT = "Dạ vâng ạ, Casa có Cambridge Early Years kết hợp Montessori cho các con. Ba/Mẹ muốn tìm hiểu thêm điều gì ạ?"
ALREADY_SENT = ("ở trên", "phía trên", "bên trên", "đã gửi", "vừa gửi")
ASKS_PHONE = ("sđt", "số điện thoại", "zalo")
SENT_AT = "2026-10-24T02:00:00+00:00"

SENT_ABOVE = ("ở trên", "phía trên", "bên trên")
MD3 = {"kid_age": "3 tuổi", "interested_campus": "Mỹ Đình"}
KM3 = {"kid_age": "3 tuổi", "interested_campus": "Kim Mã"}
KM4 = {"kid_age": "4 tuổi", "interested_campus": "Kim Mã"}
SAID_MD3 = ("bé nhà em 3 tuổi, em quan tâm cơ sở Mỹ Đình", OK_BOT)
# Lượt ảnh lỗi một phần: học phí tới, thời khoá biểu lỗi (bot đã xin lỗi; lịch sử chỉ giữ câu trả lời và ghi chú).
KM4_FEE_SENT = {**KM4, "media_sent": {"fee:song_ngu:2026-10": SENT_AT}}
TIMETABLE_FAILED = ("học phí và thời khoá biểu ạ", "Dạ em gửi Ba/Mẹ chính sách học phí và thời khoá biểu lớp của bé "
                    "để gia đình tham khảo ạ. [đã gửi ảnh học phí hệ Song ngữ (cơ sở Kim Mã)] "
                    "[ảnh thời khoá biểu cơ sở Kim Mã chưa gửi được]")
FEE = {"topics": ["Học phí"]}
PROGRAMME = {"topics": ["Chương trình/phương pháp"]}
FACILITIES = {"topics": ["Cơ sở vật chất"]}
MENU = {"topics": ["Ăn uống/thực đơn"]}


def csvc4(campus: str) -> tuple[str, ...]:
    """4 ảnh cơ sở vật chất đầu của một cơ sở ("km", "cl"): số ảnh bot gửi mỗi cơ sở."""
    return tuple(f"{campus}-csvc-{i}" for i in range(1, 5))


MEDIA_CASES: dict[str, MediaCase] = {
    # --- học phí ---
    "FEE-ASKED-READY": MediaCase(
        profile=MD3, history=[SAID_MD3],
        steps=[Step("học phí bên mình thế nào em", images=("qt-fee-10",), extract=FEE)],
    ),
    "FEE-WAIT-AGE": MediaCase(
        profile={"interested_campus": "Kim Mã"}, history=[("em quan tâm cơ sở Kim Mã", OK_BOT)],
        steps=[
            Step("cho em hỏi học phí ạ", expect={"asks_age": True, "asks_campus": False}, extract=FEE),
            Step(tap="age:2", images=("sn-fee-10",), extract={"kid_age": "3-5 tuổi"}),
        ],
    ),
    "FEE-WAIT-CAMPUS": MediaCase(
        profile={"kid_age": "20 tháng"}, history=[("bé nhà em 20 tháng", OK_BOT)],
        steps=[
            Step("học phí của trường bao nhiêu ạ", expect={"asks_campus": True, "asks_age": False}, extract=FEE),
            Step(tap="campus:0", images=("qt-fee-10",), extract={"interested_campus": "Chùa Láng"}),
        ],
    ),
    "FEE-BOTH-SYSTEMS": MediaCase(
        profile={"kid_age": "3 tuổi"}, history=[("bé nhà em 3 tuổi", OK_BOT)],
        steps=[Step("cho mình xin học phí 2 hệ nhé", images=("sn-fee-10", "qt-fee-10"), expect={"asks_campus": False},
                    extract=FEE)],
    ),
    "FEE-SENT-AGAIN": MediaCase(
        profile={**MD3, "media_sent": {"fee:quoc_te:2026-10": SENT_AT}},
        history=[SAID_MD3, ("học phí bên mình thế nào em", "Dạ em gửi Ba/Mẹ chính sách học phí tại cơ sở Mỹ Đình để "
                            "gia đình tham khảo ạ. [đã gửi ảnh học phí hệ Quốc tế (cơ sở Mỹ Đình)]")],
        steps=[Step("gửi lại bảng học phí cho em xem với", any_of=[ALREADY_SENT], extract=FEE)],
    ),
    "FEE-NOT-ASKED-READY": MediaCase(
        profile=MD3, history=[SAID_MD3],
        steps=[Step("trường có camera không ạ", extract={"topics": ["An toàn/sức khoẻ/camera"]})],
    ),
    "FEE-PHONE-ASK-OTHER-TOPIC": MediaCase(
        profile={"interested_campus": "Mỹ Đình"}, history=[("em quan tâm cơ sở Mỹ Đình", ASK_PHONE_BOT)],
        steps=[Step("trường có xe đưa đón không em", extract={"topics": ["Xe đưa đón"]})],
    ),
    "FEE-REFUSE-PHONE-CAMPUS": MediaCase(
        profile={"interested_campus": "Mỹ Đình", "phone_declined": True},
        history=[("em quan tâm cơ sở Mỹ Đình", ASK_PHONE_BOT), ("em chưa muốn để số ạ", OK_BOT)],
        steps=[Step("thôi em cứ báo học phí đi", images=("qt-fee-10",), none_of=ASKS_PHONE, extract=FEE)],
    ),
    "FEE-REFUSE-PHONE-NO-CAMPUS": MediaCase(
        profile={"kid_age": "3 tuổi", "phone_declined": True},
        history=[("bé nhà em 3 tuổi", ASK_PHONE_BOT)],
        steps=[Step("thôi mình chưa muốn để số đâu, em cứ báo học phí đi", expect={"asks_campus": True},
                    none_of=ASKS_PHONE, extract={**FEE, "phone_declined": True})],
    ),
    "FEE-ASKED-BEFORE-THEN-REFUSE": MediaCase(
        profile={"interested_campus": "Mỹ Đình", "fee_asked": True},
        history=[("học phí bên Mỹ Đình thế nào em", "Dạ học phí tuỳ độ tuổi của bé ạ. Nếu tiện, Ba/Mẹ để lại "
                  "SĐT/Zalo để tư vấn viên gửi bảng phí chi tiết nhé? [QUICK:phone]")],
        steps=[Step("thôi không để số đâu em", images=("qt-fee-10",),
                    none_of=ASKS_PHONE, extract={"phone_declined": True})],
    ),
    "FEE-STALE": MediaCase(
        profile=MD3, history=[SAID_MD3], catalog="stale_fee",
        steps=[Step("học phí bên mình thế nào em", images=("qt-fee-9",), alerts=("Chưa có ảnh học phí mới tháng 10",),
                    extract=FEE)],
    ),
    "FEE-NO-NUMBER": MediaCase(
        profile=KM4, history=[("bé nhà em 4 tuổi, em quan tâm Kim Mã", OK_BOT)],
        steps=[Step("học phí 1 tháng bao nhiêu tiền vậy em, báo con số cụ thể giúp mình", images=("sn-fee-10",),
                    extract=FEE)],
    ),
    # --- thời khoá biểu ---
    "TKB-WAIT-BOTH": MediaCase(
        steps=[
            Step("cho mình tham khảo thời khoá biểu của các con nhé", expect={"asks_campus": True, "asks_age": True},
                 extract=PROGRAMME),
            Step("Kim Mã, bé nhà mình 3 tuổi", images=("km-tkb-36-72",),
                 extract={"interested_campus": "Kim Mã", "kid_age": "3 tuổi"}),
        ],
    ),
    "TKB-WAIT-AGE": MediaCase(
        profile={"interested_campus": "Mỹ Đình"}, history=[("em quan tâm cơ sở Mỹ Đình", OK_BOT)],
        steps=[
            Step("cho em xin thời khoá biểu của lớp", expect={"asks_age": True, "asks_campus": False}, extract=PROGRAMME),
            Step(tap="age:0", images=("md-tkb-15-36",), extract={"kid_age": "dưới 2 tuổi"}),
        ],
    ),
    "TKB-WAIT-CAMPUS": MediaCase(
        profile={"kid_age": "4 tuổi"}, history=[("bé nhà em 4 tuổi", OK_BOT)],
        steps=[
            Step("cho em xin TKB của các con ạ", expect={"asks_campus": True, "asks_age": False}, extract=PROGRAMME),
            Step(tap="campus:0", images=("cl-tkb-36-60",), extract={"interested_campus": "Chùa Láng"}),
        ],
    ),
    "TKB-READY": MediaCase(
        profile=KM3, history=[("bé nhà em 3 tuổi, em quan tâm Kim Mã", OK_BOT)],
        steps=[Step("cho em xin thời khoá biểu của lớp bé ạ", images=("km-tkb-36-72",), extract=PROGRAMME)],
    ),
    "TKB-CAMBRIDGE": MediaCase(
        profile={"kid_age": "4 tuổi", "interested_campus": "Chùa Láng"}, history=[("bé 4 tuổi, cơ sở Chùa Láng", OK_BOT)],
        steps=[Step("Cambridge học thế nào ạ", images=("cl-tkb-36-60",), any_of=[("cambridge",)],
                    extract={"topics": ["Tiếng Anh/GV nước ngoài"]})],
    ),
    "TKB-PROGRAMME-TOPIC": MediaCase(
        profile={"kid_age": "20 tháng", "interested_campus": "Mỹ Đình"}, history=[("bé 20 tháng, cơ sở Mỹ Đình", OK_BOT)],
        steps=[Step("trường mình dạy chương trình gì ạ", images=("md-tkb-15-36",), extract=PROGRAMME)],
    ),
    # Hội thoại thật 2026-10-24: thời khoá biểu "Chùa Láng và Kim Mã", chọn tuổi bằng nút, rồi xin "2 hệ".
    "TKB-MULTI-CAMPUS": MediaCase(
        steps=[
            Step("Cho mình tham khảo thời khoá biểu nhé", expect={"asks_campus": True, "asks_age": True},
                 extract=PROGRAMME),
            Step("Chùa Láng và Kim Mã", expect={"asks_age": True, "asks_campus": False},
                 extract={"interested_campus": "Chùa Láng, Kim Mã"}),
            Step(tap="age:2", images=("cl-tkb-36-60", "km-tkb-36-72"), extract={"kid_age": "3-5 tuổi"}),
            Step("Gửi thời khoá biểu 2 hệ nhé", any_of=[ALREADY_SENT], extract=PROGRAMME),
        ],
    ),
    "TKB-BOTH-SYSTEMS-UNKNOWN": MediaCase(
        profile={"kid_age": "4 tuổi"}, history=[("bé nhà em 4 tuổi", OK_BOT)],
        steps=[
            Step("Gửi thời khoá biểu 2 hệ nhé", images=("km-tkb-36-72",), expect={"asks_campus": True},
                 extract=PROGRAMME),
            Step(tap="campus:1", images=("md-tkb-36-60",), extract={"interested_campus": "Mỹ Đình"}),
        ],
    ),
    "TKB-SENT-AGAIN": MediaCase(
        profile={**KM3, "media_sent": {"timetable:km-tkb-36-72": SENT_AT}},
        history=[("cho em xin thời khoá biểu ạ", "Dạ em gửi Ba/Mẹ thời khoá biểu của lớp để gia đình tham khảo ạ. "
                  "[đã gửi ảnh thời khoá biểu cơ sở Kim Mã]")],
        steps=[Step("gửi lại thời khoá biểu cho em với", any_of=[ALREADY_SENT], extract=PROGRAMME)],
    ),
    "TKB-TRIAL-WEEK": MediaCase(
        profile=MD3, history=[SAID_MD3],
        steps=[Step("lịch học thử 1 tuần thế nào ạ", any_of=[("học thử",)], extract={"topics": ["Học thử/tham quan"]})],
    ),
    "TKB-WEEKDAY": MediaCase(
        profile=KM4, history=[("bé nhà em 4 tuổi, em quan tâm Kim Mã", OK_BOT)],
        steps=[Step("lịch học từ thứ 2 đến thứ 6 của các con thế nào ạ", images=("km-tkb-36-72",),
                    extract={"topics": ["Giờ học/đón trả/trông muộn"]})],
    ),
    "TKB-DAILY-NO-ESCALATE": MediaCase(
        profile=MD3, history=[SAID_MD3],
        steps=[Step("các con học những gì trong ngày, lịch học cụ thể từng giờ thế nào ạ", images=("md-tkb-36-60",),
                    extract={"topics": ["Giờ học/đón trả/trông muộn"]})],
    ),
    "TKB-HOLIDAY-ESCALATE": MediaCase(
        profile=MD3, history=[SAID_MD3],
        steps=[Step("lịch học hè năm nay của trường thế nào ạ", escalate=True,
                    extract={"topics": ["Giờ học/đón trả/trông muộn"]})],
    ),
    "TKB-BIRTH-YEAR": MediaCase(
        profile={"interested_campus": "Mỹ Đình"}, history=[("em quan tâm cơ sở Mỹ Đình", OK_BOT)],
        steps=[Step("bé nhà em sinh năm 2022, cho em xem thời khoá biểu", images=("md-tkb-36-60",),
                    expect={"asks_age": False}, extract={"kid_age": "sinh năm 2022", **PROGRAMME})],
    ),
    # --- cơ sở vật chất ---
    "CSVC-WAIT-CAMPUS": MediaCase(
        profile={"kid_age": "3 tuổi"}, history=[("bé nhà em 3 tuổi", OK_BOT)],
        steps=[
            Step("trường có sân chơi không ạ, cho em xem ảnh trường với", expect={"asks_campus": True},
                 extract=FACILITIES),
            Step(tap="campus:2", images=csvc4("km"), extract={"interested_campus": "Kim Mã"}),
        ],
    ),
    "CSVC-READY": MediaCase(
        profile={"interested_campus": "Chùa Láng"}, history=[("em quan tâm cơ sở Chùa Láng", OK_BOT)],
        steps=[Step("cơ sở vật chất bên mình thế nào ạ", images=csvc4("cl"), extract=FACILITIES)],
    ),
    "CSVC-SENT-AGAIN": MediaCase(
        profile={"interested_campus": "Chùa Láng", "media_sent": {"facilities:Chùa Láng": SENT_AT}},
        history=[("cơ sở vật chất bên mình thế nào ạ", "Dạ em gửi Ba/Mẹ vài hình ảnh cơ sở Chùa Láng để gia đình tham "
                  "khảo ạ. [đã gửi ảnh cơ sở vật chất cơ sở Chùa Láng]")],
        steps=[Step("gửi lại ảnh trường cho mình xem với", any_of=[ALREADY_SENT], extract=FACILITIES)],
    ),
    "CSVC-OTHER-CAMPUS-AFTER": MediaCase(
        profile={"interested_campus": "Kim Mã", "media_sent": {"facilities:Kim Mã": SENT_AT}},
        history=[("trường có sân chơi không ạ", "Dạ em gửi Ba/Mẹ vài hình ảnh cơ sở Kim Mã để gia đình tham khảo ạ. "
                  "[đã gửi ảnh cơ sở vật chất cơ sở Kim Mã]")],
        steps=[Step("còn cơ sở Mỹ Đình thì ở đâu ạ", extract={"interested_campus": "Mỹ Đình"})],
    ),
    # --- thực đơn ---
    "MENU-KNOWN-SYSTEM": MediaCase(
        profile={"interested_campus": "Kim Mã"}, history=[("em quan tâm cơ sở Kim Mã", OK_BOT)],
        steps=[Step("thực đơn của các con thế nào ạ", images=("sn-menu",), extract=MENU)],
    ),
    "MENU-UNKNOWN-SYSTEM": MediaCase(
        profile={"kid_age": "2-3 tuổi"}, history=[("bé nhà em 2-3 tuổi", OK_BOT)],
        steps=[Step("bé ăn uống ở trường thế nào ạ, cho em xem thực đơn", images=("qt-menu",), extract=MENU)],
    ),
    "MENU-NO-DRIVE": MediaCase(
        profile={"interested_campus": "Kim Mã"}, history=[("em quan tâm cơ sở Kim Mã", OK_BOT)], catalog="no_menu",
        steps=[Step("cho em xem thực đơn của trường", images=(QA_MENU_IMAGE,), extract=MENU)],
    ),
    # --- chung ---
    "GEN-ESCALATE-NO-IMAGE": MediaCase(
        profile=MD3, history=[SAID_MD3],
        steps=[Step("cô giáo chủ nhiệm lớp 3 tuổi ở Mỹ Đình tên gì vậy em, cho em xem ảnh lớp luôn", escalate=True,
                    extract={"topics": ["Giáo viên/tỷ lệ cô trò", "Cơ sở vật chất"]})],
    ),
    "GEN-UPSET-NO-IMAGE": MediaCase(
        profile=KM3, history=[("bé nhà em 3 tuổi, em quan tâm Kim Mã", ASK_PHONE_BOT)],
        steps=[Step("sao cứ đòi số thế, gửi bảng học phí qua đây luôn đi", escalate=True,
                    extract={**FEE, "upset": True, "phone_declined": True})],
    ),
    "GEN-FAIL-RESEND-REPLY": MediaCase(
        profile=KM4_FEE_SENT, history=[TIMETABLE_FAILED],
        steps=[Step("em gửi lại ảnh đi", images=("km-tkb-36-72",), none_of=SENT_ABOVE)],
    ),
    "GEN-FAIL-NO-RESEND-REPLY": MediaCase(
        profile=KM4_FEE_SENT, history=[TIMETABLE_FAILED],
        steps=[Step("không cần em gửi lại đâu, chị xem web rồi")],
    ),
    "GEN-FAIL-OTHER-TOPIC": MediaCase(
        profile=KM4_FEE_SENT, history=[TIMETABLE_FAILED],
        steps=[Step("trường có xe đưa đón không ạ", none_of=("gửi lại",), extract={"topics": ["Xe đưa đón"]})],
    ),
}


MATRIX: list[Row] = [
    # --- học phí ---
    Row("FEE-ASKED-READY", "Học phí", "Hỏi học phí, đã biết tuổi bé và cơ sở",
        "Ảnh học phí của hệ (Mỹ Đình: qt-fee-10); câu báo em gửi, không con số, không nói không gửi được bảng phí",
        "eval"),
    Row("FEE-WAIT-AGE", "Học phí", "Hỏi học phí, biết cơ sở, chưa biết tuổi; lượt sau bấm nút tuổi",
        "Lượt 1 không ảnh, hỏi tuổi bé (không hỏi lại cơ sở); lượt 2 ảnh học phí hệ Song ngữ (cờ fee_asked chờ)",
        "eval"),
    Row("FEE-WAIT-CAMPUS", "Học phí", "Hỏi học phí, biết tuổi, chưa biết cơ sở; lượt sau bấm nút cơ sở",
        "Lượt 1 không ảnh, hỏi cơ sở; lượt 2 ảnh học phí hệ Quốc tế", "eval"),
    Row("FEE-BOTH-SYSTEMS", "Học phí", "Xin học phí \"2 hệ\" khi chưa rõ cơ sở Quốc tế",
        "Ảnh học phí cả hai hệ (sn-fee-10, qt-fee-10), không hỏi cơ sở", "eval"),
    Row("FEE-SENT-AGAIN", "Học phí", "Ảnh học phí tháng này đã gửi, phụ huynh xin lại",
        "Không ảnh; không hứa gửi; nói ảnh đã gửi ở trên", "eval"),
    Row("FEE-NOT-ASKED-READY", "Học phí", "Đủ tuổi và cơ sở nhưng hỏi chuyện khác (camera)",
        "Không ảnh học phí (dòng \"Nếu phụ huynh hỏi học phí\" không được gắn [SEND:fee])", "eval"),
    Row("FEE-PHONE-ASK-OTHER-TOPIC", "Học phí",
        "Tin bot trước xin SĐT \"để em gửi bảng học phí\", phụ huynh hỏi xe đưa đón, chưa biết tuổi",
        "Không ảnh nào", "eval"),
    Row("FEE-REFUSE-PHONE-CAMPUS", "Học phí", "Đã từ chối để số, biết cơ sở, chưa biết tuổi, đòi giá",
        "Ảnh học phí hệ Quốc tế; không [ESCALATE]; không xin SĐT lại", "eval"),
    Row("FEE-REFUSE-PHONE-NO-CAMPUS", "Học phí", "Từ chối để số mà đòi giá, chưa biết cơ sở",
        "Không ảnh; hỏi cơ sở; không [ESCALATE]; không xin SĐT", "eval"),
    Row("FEE-ASKED-BEFORE-THEN-REFUSE", "Học phí",
        "Tin trước hỏi học phí (cờ fee_asked), bot xin SĐT, tin này không để số; biết cơ sở, chưa biết tuổi",
        "Ảnh học phí hệ Quốc tế (dòng chắc chắn gửi); không xin SĐT lại", "eval"),
    Row("FEE-STALE", "Học phí", "Drive chỉ có ảnh học phí tháng trước",
        "Gửi ảnh tháng cũ (qt-fee-9) và một tin Telegram \"Chưa có ảnh học phí mới tháng 10\"", "eval"),
    Row("FEE-NO-NUMBER", "Học phí", "Đòi con số cụ thể, đủ tuổi và cơ sở",
        "Ảnh học phí hệ Song ngữ; không viết số tiền; không nói không gửi được bảng phí", "eval"),
    Row("FEE-ONCE-A-MONTH", "Học phí", "Ảnh học phí chờ đủ tuổi + cơ sở, rồi mỗi tháng 1 lần",
        "Đã gửi tháng này thì không gửi lại; tháng sau hỏi lại thì gửi", "pytest",
        "tests/test_media_replies.py::test_fee_image_waits_for_age_and_campus_then_goes_once_a_month"),
    Row("FEE-KIM-MA-NO-FOLDER", "Học phí", "Drive thiếu thư mục cơ sở Kim Mã",
        "Vẫn gửi ảnh học phí hệ Song ngữ (hệ theo bảng CAMPUS_SYSTEMS)", "pytest",
        "tests/test_media_replies.py::test_kim_ma_parent_gets_the_bilingual_fee_even_without_a_kim_ma_folder_on_drive"),
    Row("FEE-PHONE-ASK-NO-TOKEN", "Học phí", "Câu trả lời xin SĐT \"để em gửi bảng học phí chi tiết\" (không token)",
        "Không ảnh học phí, không cờ fee_asked", "pytest",
        "tests/test_media_replies.py::test_asking_the_phone_to_send_the_fee_table_sends_no_fee_image"),
    Row("FEE-NOAGE-ONLY-IF-ASKED", "Học phí",
        "Chưa biết tuổi, tin bot trước xin SĐT, phụ huynh hỏi chuyện khác mà câu trả lời gắn [SEND:fee]",
        "Không ảnh, không cờ fee_asked (tuổi biết sau cũng không tự gửi)", "pytest",
        "tests/test_media_replies.py::test_fee_without_the_age_goes_only_to_a_parent_asking_the_fee"),
    Row("FEE-MULTI-SYSTEM", "Học phí", "Hồ sơ nhiều cơ sở khác hệ (\"Chùa Láng, Kim Mã\")",
        "Mỗi hệ một ảnh học phí", "pytest",
        "tests/test_media_replies.py::test_fee_of_two_campuses_of_different_systems_is_one_image_each"),
    Row("FEE-BOTH-THEN-CAMPUS", "Học phí", "Sau ảnh học phí \"2 hệ\", tin sau nêu cơ sở Quốc tế",
        "Không ảnh nào nữa, cờ fee_asked đã xoá", "pytest",
        "tests/test_media_replies.py::test_fee_of_both_systems_goes_without_knowing_the_international_campus"),
    Row("FEE-STALE-ONCE-A-DAY", "Học phí", "Ảnh học phí tháng cũ gửi nhiều phụ huynh trong ngày",
        "Tin Telegram nhắc trường tối đa 1 lần mỗi hệ mỗi ngày", "pytest",
        "tests/test_media_replies.py::test_stale_fee_image_is_sent_and_the_school_is_reminded_once_a_day"),
    Row("FEE-LAST-YEAR-STALE", "Học phí", "Thư mục tháng này là ảnh sửa hơn 300 ngày trước",
        "Vẫn gửi, coi là ảnh cũ và nhắc trường", "pytest",
        "tests/test_media_replies.py::test_last_years_fee_image_of_this_month_is_sent_and_the_school_is_reminded"),
    Row("FEE-NEXT-MONTH-UNASKED", "Học phí", "Hỏi lại học phí trong tháng đã gửi",
        "Không để cờ chờ; tháng sau không tự gửi khi phụ huynh không hỏi", "pytest",
        "tests/test_media_replies.py::test_fee_asked_again_in_the_same_month_does_not_send_next_month_unasked"),
    Row("FEE-NO-DRIVE-IMAGE", "Học phí", "Drive không có ảnh học phí của hệ",
        "Không ảnh, không cờ chờ", "pytest",
        "tests/test_media_replies.py::test_fee_asked_while_drive_has_no_fee_image_of_the_system_does_not_wait"),
    # --- thời khoá biểu ---
    Row("TKB-WAIT-BOTH", "Thời khoá biểu", "Xin thời khoá biểu khi chưa biết cơ sở lẫn tuổi; lượt sau nêu cả hai",
        "Lượt 1 không ảnh, hỏi cơ sở và tuổi, không nói tư vấn viên sẽ gửi; lượt 2 ảnh km-tkb-36-72", "eval"),
    Row("TKB-WAIT-AGE", "Thời khoá biểu", "Biết cơ sở, thiếu tuổi; lượt sau bấm nút \"Dưới 2 tuổi\"",
        "Lượt 1 không ảnh, hỏi tuổi (không hỏi cơ sở); lượt 2 ảnh md-tkb-15-36", "eval"),
    Row("TKB-WAIT-CAMPUS", "Thời khoá biểu", "Biết tuổi, thiếu cơ sở; lượt sau bấm nút cơ sở",
        "Lượt 1 không ảnh, hỏi cơ sở (không hỏi tuổi); lượt 2 ảnh cl-tkb-36-60", "eval"),
    Row("TKB-READY", "Thời khoá biểu", "Xin thời khoá biểu, đã biết cơ sở và tuổi",
        "Ảnh thời khoá biểu đúng cơ sở và nhóm tuổi; câu báo em gửi", "eval"),
    Row("TKB-CAMBRIDGE", "Thời khoá biểu", "Hỏi Cambridge, đã biết cơ sở và tuổi",
        "Trả lời về Cambridge và gửi thời khoá biểu (cl-tkb-36-60)", "eval"),
    Row("TKB-PROGRAMME-TOPIC", "Thời khoá biểu", "Hỏi chương trình học (dòng \"Nếu phụ huynh hỏi …\"), đủ thông tin",
        "Ảnh md-tkb-15-36 (theo chủ đề trích xuất hoặc token [SEND:timetable])", "eval"),
    Row("TKB-MULTI-CAMPUS", "Thời khoá biểu",
        "Hội thoại thật: xin TKB, nêu \"Chùa Láng và Kim Mã\", bấm tuổi, rồi xin \"2 hệ\"",
        "Hỏi cơ sở + tuổi, rồi hỏi tuổi; lượt bấm tuổi gửi cl-tkb-36-60 và km-tkb-36-72; xin lại không ảnh, nói ảnh ở trên",
        "eval"),
    Row("TKB-BOTH-SYSTEMS-UNKNOWN", "Thời khoá biểu", "Xin TKB \"2 hệ\" khi chưa rõ cơ sở Quốc tế",
        "Gửi TKB Kim Mã, hỏi Chùa Láng hay Mỹ Đình; lượt sau nêu Mỹ Đình thì gửi md-tkb-36-60", "eval"),
    Row("TKB-SENT-AGAIN", "Thời khoá biểu", "Xin lại thời khoá biểu đã gửi",
        "Không ảnh; nói ảnh ở phía trên; không hứa gửi, không nói tư vấn viên sẽ gửi", "eval"),
    Row("TKB-TRIAL-WEEK", "Thời khoá biểu", "\"lịch học thử 1 tuần\" (tuần học thử, không phải TKB)",
        "Không ảnh thời khoá biểu", "eval"),
    Row("TKB-WEEKDAY", "Thời khoá biểu", "\"lịch học từ thứ 2 đến thứ 6\", đủ thông tin",
        "Ảnh thời khoá biểu; không [ESCALATE]", "eval"),
    Row("TKB-DAILY-NO-ESCALATE", "Thời khoá biểu", "Hỏi lịch học từng giờ trong ngày khi có ảnh TKB",
        "Ảnh thời khoá biểu; trả lời chung, không [ESCALATE]", "eval"),
    Row("TKB-HOLIDAY-ESCALATE", "Thời khoá biểu", "Hỏi lịch học hè (không có trong Q&A)",
        "[ESCALATE], thẻ Telegram, không ảnh", "eval"),
    Row("TKB-BIRTH-YEAR", "Thời khoá biểu", "Tuổi ghi theo năm sinh (\"sinh năm 2022\")",
        "Tính ra 51 tháng: ảnh md-tkb-36-60; không hỏi lại tuổi", "eval"),
    Row("TKB-NO-DRIVE-IMAGE", "Thời khoá biểu", "Drive không có TKB cho cơ sở/tuổi đó",
        "Không ảnh, không cờ chờ", "pytest",
        "tests/test_media_replies.py::test_timetable_that_drive_does_not_have_does_not_wait"),
    Row("TKB-PROGRAM-NOT-CAMPUS", "Thời khoá biểu", "Chỉ biết hệ quan tâm (song ngữ/quốc tế), chưa biết cơ sở",
        "Không đoán cơ sở theo hệ: không ảnh", "pytest",
        "tests/test_media_replies.py::test_the_programme_the_parent_wants_does_not_pick_the_timetable_campus"),
    Row("TKB-ENROL-YEAR", "Thời khoá biểu", "\"tuyển sinh 2025\" trong tin", "Không phải năm sinh, vẫn hỏi tuổi",
        "pytest", "tests/test_media_replies.py::test_enrolment_year_in_the_message_is_not_the_kids_age"),
    Row("TKB-TRIAL-NO-ACCENT", "Thời khoá biểu", "\"lich hoc thu …\" không dấu",
        "Chỉ là TKB khi sau \"thu\" là 2–7/hai/bay", "pytest",
        "tests/test_media_replies.py::test_trial_week_schedule_is_not_a_timetable_question"),
    Row("TKB-TRIAL-REPLY-NO-WAIT", "Thời khoá biểu", "Câu trả lời gửi lịch học thử",
        "Không ảnh TKB, không cờ chờ tuổi", "pytest",
        "tests/test_media_replies.py::test_a_reply_sending_the_trial_week_does_not_wait_for_the_kids_age"),
    Row("TKB-BOTH-NAMED-EARLIER", "Thời khoá biểu", "\"2 hệ\" sau khi đã nêu các cơ sở ở tin trước",
        "TKB của mọi cơ sở đã nêu", "pytest",
        "tests/test_media_replies.py::test_both_systems_asked_for_get_the_timetables_of_the_campuses_named_earlier"),
    Row("TKB-BOTH-CAMPUS-WORDS", "Thời khoá biểu", "\"cả 2 cơ sở\"/\"hai bên\"/\"2 trường\" (BOTH_WORDS không phải \"hệ\")",
        "TKB của mọi cơ sở đã nêu trong hội thoại; chỉ nêu Kim Mã thì chỉ TKB Kim Mã: không thêm hệ chưa rõ, không hỏi "
        "cơ sở, không cờ chờ", "pytest",
        "tests/test_media_replies.py::"
        "test_both_campuses_get_the_timetables_of_every_campus_named_and_no_system_not_named"),
    Row("TKB-DECLINED-IN-WORDS", "Thời khoá biểu",
        "Phụ huynh từ chối bằng chữ: \"Không cần gửi lại thời khoá biểu đâu em\" (TKB chưa gửi, đủ tuổi và cơ sở)",
        "Giới hạn đã biết, chưa sửa: _asks_timetable đọc chữ tin phụ huynh nên vẫn gửi km-tkb-36-72; test ghi hành vi "
        "hiện tại, người vận hành quyết sau", "pytest",
        "tests/test_eval_media.py::test_a_parent_declining_the_timetable_in_words_still_gets_it"),
    # --- cơ sở vật chất ---
    Row("CSVC-WAIT-CAMPUS", "Cơ sở vật chất", "Hỏi cơ sở vật chất khi chưa biết cơ sở; lượt sau bấm Kim Mã",
        "Lượt 1 không ảnh, hỏi cơ sở; lượt 2 bốn ảnh km-csvc-1..4", "eval"),
    Row("CSVC-READY", "Cơ sở vật chất", "Hỏi cơ sở vật chất, đã biết cơ sở", "Bốn ảnh cl-csvc-1..4", "eval"),
    Row("CSVC-SENT-AGAIN", "Cơ sở vật chất", "Xin lại ảnh cơ sở đã gửi",
        "Không ảnh; không hứa gửi; nói ảnh đã gửi ở trên", "eval"),
    Row("CSVC-OTHER-CAMPUS-AFTER", "Cơ sở vật chất", "Đã gửi ảnh Kim Mã, tin sau nhắc Mỹ Đình (không hỏi ảnh)",
        "Không ảnh (không tự gửi ảnh cơ sở khác)", "eval"),
    Row("CSVC-INVITE-NO-TOKEN", "Cơ sở vật chất", "Câu mời \"có muốn em gửi ảnh … không ạ?\" (không token)",
        "Không ảnh", "pytest", "tests/test_media_replies.py::test_an_offer_to_send_images_is_not_saying_they_are_sent"),
    Row("CSVC-MULTI-CAMPUS", "Cơ sở vật chất", "Nhiều cơ sở", "Một cơ sở mỗi lượt (2 cơ sở là 8 ảnh, quá trần 5)",
        "pytest", "tests/test_media_replies.py::test_facilities_of_two_campuses_go_one_campus_a_turn"),
    Row("CSVC-NO-IMAGES-NO-WAIT", "Cơ sở vật chất", "Cơ sở không có ảnh cơ sở vật chất", "Không ảnh, không cờ chờ",
        "pytest", "tests/test_media_replies.py::test_facilities_of_a_campus_without_images_do_not_wait"),
    Row("CSVC-ASKED-AGAIN-NO-WAIT", "Cơ sở vật chất", "Hỏi lại cơ sở vật chất khi ảnh cơ sở đó đã gửi",
        "Cờ facilities_asked không bật lại; tin sau nhắc cơ sở khác không nhận ảnh", "pytest",
        "tests/test_media_replies.py::test_facilities_asked_again_after_the_images_went_does_not_wait_for_another_campus"),
    # --- thực đơn ---
    Row("MENU-KNOWN-SYSTEM", "Thực đơn", "Hỏi thực đơn, biết cơ sở Kim Mã",
        "Ảnh thực đơn hệ Song ngữ (sn-menu), không ảnh mẫu cũ của Q&A", "eval"),
    Row("MENU-UNKNOWN-SYSTEM", "Thực đơn", "Hỏi thực đơn, chưa biết hệ", "Ảnh thực đơn hệ Quốc tế (qt-menu)", "eval"),
    Row("MENU-NO-DRIVE", "Thực đơn", "Drive chưa có ảnh thực đơn",
        "Ảnh thực đơn mẫu của Q&A (static/thuc-don-mau.jpg, model gắn [IMAGES:])", "eval"),
    Row("MENU-REPLACES-QA", "Thực đơn", "Model gắn ảnh mẫu của Q&A khi Drive có thực đơn",
        "Chỉ ảnh thực đơn Drive, bỏ ảnh mẫu cũ", "pytest",
        "tests/test_media_replies.py::test_menu_of_kim_ma_is_the_drive_image_not_the_old_sample"),
    Row("MENU-ONCE", "Thực đơn", "Xin lại thực đơn đã gửi", "Không ảnh (mỗi ảnh một lần: khoá menu:<id>), không dòng "
        "[HỆ THỐNG] thực đơn", "pytest", "tests/test_media_replies.py::test_menu_goes_once_to_each_parent"),
    Row("MENU-BY-PROGRAM", "Thực đơn", "Chưa biết cơ sở, hồ sơ có hệ quan tâm (interested_program)",
        "Ảnh thực đơn của hệ đó (song ngữ: sn-menu, quốc tế: qt-menu)", "pytest",
        "tests/test_media_replies.py::test_menu_without_a_campus_is_the_one_of_the_programme_the_parent_wants"),
    # --- chung ---
    Row("GEN-ESCALATE-NO-IMAGE", "Chung", "Lượt [ESCALATE] (tên giáo viên cụ thể) có kèm chủ đề ảnh",
        "Thẻ Telegram, không ảnh", "eval"),
    Row("GEN-UPSET-NO-IMAGE", "Chung", "Phụ huynh bực vì bị đòi số, đòi bảng học phí (đủ điều kiện gửi)",
        "Câu xin lỗi + thẻ Telegram, không ảnh", "eval"),
    Row("GEN-ESCALATE-UPSET-CODE", "Chung", "Chuyển tư vấn viên hoặc upset với model giả",
        "Không ảnh, không ghi media_sent", "pytest",
        "tests/test_media_replies.py::test_no_image_when_the_parent_goes_to_a_consultant"),
    Row("GEN-COMPOUND-SEND-INVITE", "Chung", "Câu ghép: báo gửi học phí + mời xem ảnh cơ sở vật chất",
        "Chỉ ảnh học phí", "pytest",
        "tests/test_media_replies.py::test_a_reply_sending_the_fee_and_offering_the_facilities_sends_only_the_fee"),
    Row("GEN-TOKEN-TAGGED", "Chung", "Câu trả lời gắn [SEND:<loại>] khi trích xuất sót chủ đề",
        "Ảnh của dòng \"Nếu phụ huynh hỏi …\" vẫn đi", "pytest",
        "tests/test_media_replies.py::test_an_image_the_reply_tags_as_sent_goes_even_if_the_extraction_missed_its_topic"),
    Row("GEN-TOKEN-NOT-READY", "Chung", "Token [SEND] cho ảnh chưa đủ điều kiện (thiếu tuổi/cơ sở)",
        "Không ảnh, không cờ chờ", "pytest",
        "tests/test_media_replies.py::test_a_send_token_of_an_image_not_ready_sends_nothing_and_waits_for_nothing"),
    Row("GEN-TOKEN-HIDDEN", "Chung", "Token [SEND:] trong câu trả lời",
        "Không lộ ra tin phụ huynh, không lưu vào lịch sử (eval cũng kiểm mọi lượt)", "pytest",
        "tests/test_media_replies.py::test_the_send_token_is_neither_shown_to_the_parent_nor_kept_in_the_history"),
    Row("GEN-SENT-NOTE-HIDDEN", "Chung", "Model chép ghi chú \"[đã gửi ảnh …]\" vào câu trả lời",
        "Ghi chú không lộ ra tin phụ huynh", "pytest",
        "tests/test_media_replies.py::test_model_copying_the_sent_note_is_not_shown_to_the_parent"),
    Row("GEN-MAX-FIVE", "Chung", "Một lượt có hơn 5 ảnh", "Tối đa 5 ảnh theo thứ tự học phí, thời khoá biểu, thực đơn, "
        "cơ sở vật chất; nút trên ảnh cuối", "pytest", "tests/test_media_replies.py::test_at_most_five_images_in_one_turn"),
    Row("GEN-NOT-FIT-NEXT-TURN", "Chung", "Nhóm ảnh cơ sở vật chất không vừa trần 5 ảnh",
        "Cờ facilities_asked còn: lượt sau (\"dạ vâng\") 4 ảnh đi, cờ xoá", "pytest",
        "tests/test_media_replies.py::test_images_that_did_not_fit_go_on_the_next_turn"),
    Row("GEN-NOT-FIT-MENU", "Chung", "Ảnh thực đơn không vừa trần 5 ảnh (2 học phí + 3 thời khoá biểu)",
        "Thực đơn không có cờ chờ: lượt sau không ảnh; hỏi lại thực đơn thì đi", "pytest",
        "tests/test_media_replies.py::test_a_menu_that_did_not_fit_waits_until_the_parent_asks_again"),
    Row("GEN-TOKENS-ONLY", "Chung", "Câu trả lời chỉ có token ([IMAGES:]/[QUICK:]), không chữ",
        "Không tin chữ rỗng; chỉ ảnh, nút trên ảnh cuối", "pytest",
        "tests/test_media_replies.py::test_a_reply_of_only_tokens_sends_only_the_images_with_the_buttons"),
    Row("GEN-QUICK-ON-LAST", "Chung", "Lượt có ảnh và nút trả lời nhanh", "Nút nằm trên ảnh cuối", "pytest",
        "tests/test_media_replies.py::test_facilities_wait_for_the_campus_then_go_once_with_buttons_on_the_last_image"),
    Row("GEN-FAIL-RETRY", "Chung", "Graph từ chối ảnh duy nhất của lượt (học phí)",
        "Lượt vẫn xong, câu xin lỗi chung, ảnh chưa tính là đã gửi, lịch sử ghi \"[ảnh … chưa gửi được]\"; không tự "
        "thử lại, chỉ gửi khi phụ huynh hỏi lại (lượt sau hỏi học phí thì ảnh đi)", "pytest",
        "tests/test_media_replies.py::test_a_failed_image_does_not_break_the_turn_and_goes_when_asked_again"),
    Row("GEN-FAIL-NO-AUTO-RETRY", "Chung", "Ảnh cơ sở vật chất lỗi, lượt sau phụ huynh chỉ bấm nút tuổi",
        "Không gửi lại, không xin lỗi lại, dòng [HỆ THỐNG] không có \"Sau câu trả lời này … cơ sở vật chất\"; hỏi lại "
        "ảnh trường thì gửi", "pytest",
        "tests/test_media_replies.py::test_failed_images_are_not_tried_again_until_the_parent_asks_again"),
    Row("GEN-FAIL-IN-GROUP", "Chung", "1 trong 4 ảnh cơ sở vật chất của cơ sở lỗi",
        "3 ảnh còn lại đi, nhóm tính là đã gửi (media_sent), không câu xin lỗi; báo nhóm Telegram", "pytest",
        "tests/test_media_replies.py::test_some_photos_of_the_facilities_failing_count_as_sent_without_an_apology"),
    Row("GEN-FAIL-QA-IMAGE", "Chung", "Ảnh Q&A (static/thuc-don-mau.jpg) lỗi",
        "Log WARNING, không câu xin lỗi, không báo nhóm Telegram (như trước khi có ảnh Drive)", "pytest",
        "tests/test_media_replies.py::test_a_failed_qa_image_is_skipped_without_an_apology_nor_an_alert"),
    Row("GEN-FAIL-ALERT", "Chung", "Ảnh Drive gửi lỗi",
        "Báo nhóm Telegram tối đa 1 lần mỗi giờ, không có tin của phụ huynh", "pytest",
        "tests/test_media_replies.py::test_a_failed_image_tells_the_admin_group_once_an_hour_without_the_parents_message"),
    Row("GEN-FAIL-APOLOGY", "Chung", "Mọi ảnh Drive định gửi của lượt đều lỗi", "Thêm câu xin lỗi ảnh lỗi kèm nút",
        "pytest", "tests/test_media_replies.py::test_parent_told_the_images_failed_when_every_drive_image_promised_failed"),
    Row("GEN-FAIL-PARTIAL", "Chung", "Ảnh lỗi một phần: xin \"học phí và thời khoá biểu\", chỉ ảnh thời khoá biểu lỗi",
        "Ảnh học phí đi; câu xin lỗi nêu \"thời khoá biểu cơ sở Kim Mã\" kèm nút; lịch sử \"[đã gửi ảnh học phí …] "
        "[ảnh thời khoá biểu … chưa gửi được]\"; không cờ chờ: \"dạ vâng\" không ảnh", "pytest",
        "tests/test_media_replies.py::"
        "test_a_partly_failed_turn_apologises_for_the_image_that_failed_and_does_not_try_it_again_unasked"),
    Row("GEN-FAIL-PARTIAL-CAMPUS", "Chung", "Thời khoá biểu hai cơ sở, chỉ ảnh Kim Mã lỗi",
        "Ảnh Chùa Láng đi; câu xin lỗi nêu \"thời khoá biểu cơ sở Kim Mã\"", "pytest",
        "tests/test_media_replies.py::test_apology_names_the_campus_whose_timetable_failed"),
    Row("GEN-FAIL-RESEND", "Chung",
        "Ngay sau câu xin lỗi (tin bot trước có \"[ảnh … chưa gửi được]\"), câu trả lời của model gắn [SEND:<loại>] "
        "(học phí, thời khoá biểu, cơ sở vật chất, thực đơn)",
        "Dòng [HỆ THỐNG] \"Ảnh <nhãn> tin trước chưa gửi được. Nếu phụ huynh xin gửi lại …\" cho đúng ảnh lỗi, không "
        "\"Sau câu trả lời này …\"; ảnh đó đi, ghi media_sent", "pytest",
        "tests/test_media_replies.py::test_a_failed_image_goes_again_when_the_reply_to_the_parent_asking_tags_it"),
    Row("GEN-FAIL-RESEND-PARTIAL", "Chung", "Lượt trước ảnh học phí tới, thời khoá biểu lỗi; câu trả lời gắn "
        "[SEND:timetable]", "Chỉ dòng ảnh lỗi của thời khoá biểu; chỉ ảnh thời khoá biểu đi (học phí không gửi lại); lượt "
        "sau không còn dòng ảnh lỗi", "pytest",
        "tests/test_media_replies.py::test_only_the_image_that_failed_is_offered_again_after_a_partly_failed_turn"),
    Row("GEN-FAIL-NO-RESEND", "Chung", "Sau câu xin lỗi, câu trả lời không gắn token (\"không cần em gửi lại đâu\", "
        "\"dạ vâng\", kể cả \"em gửi lại ảnh đi\")", "Không ảnh dù tin có chữ \"gửi lại\": code không đọc chữ của "
        "phụ huynh, model quyết định bằng token", "pytest",
        "tests/test_media_replies.py::test_a_failed_image_does_not_go_again_when_the_reply_does_not_tag_it"),
    Row("GEN-FAIL-RESEND-HARNESS", "Chung", "App thật, Graph từ chối mọi ảnh (fail.graph_image) của lượt học phí + thời khoá "
        "biểu, rồi hết lỗi", "Câu xin lỗi chung; \"dạ vâng\" chỉ TEXT; \"em gửi lại ảnh đi\" (fake chat trả câu có "
        "[SEND:fee] [SEND:timetable]) gửi cả hai ảnh, ghi media_sent; \"không cần em gửi lại đâu\" (câu không token) "
        "chỉ TEXT", "harness"),
    Row("GEN-FAIL-RESEND-REPLY", "Chung", "Lịch sử có ảnh thời khoá biểu lỗi, phụ huynh \"em gửi lại ảnh đi\" (trích "
        "xuất không chủ đề)", "Model gắn [SEND:timetable]: ảnh km-tkb-36-72; câu báo em gửi, không nói ảnh ở phía trên",
        "eval"),
    Row("GEN-FAIL-NO-RESEND-REPLY", "Chung", "Lịch sử có ảnh thời khoá biểu lỗi, phụ huynh \"không cần em gửi lại đâu, "
        "chị xem web rồi\"", "Model không gắn token: không ảnh; không hứa gửi ảnh", "eval"),
    Row("GEN-FAIL-OTHER-TOPIC", "Chung", "Lịch sử có ảnh thời khoá biểu lỗi, phụ huynh hỏi chuyện khác (xe đưa đón)",
        "Không ảnh; không hứa gửi lại ảnh, không nhắc \"gửi lại\"", "eval"),
    Row("GEN-FAIL-HARNESS", "Chung", "Graph thật trả 400 cho ảnh (app chạy cách ly)",
        "IMAGE 400, thẻ ⚠️ Gửi ảnh … bị lỗi, câu xin lỗi; log không có token", "harness"),
    Row("GEN-SYNC-OFF", "Chung", "Tắt đồng bộ hoặc danh mục rỗng", "Không ảnh Drive, không dòng [HỆ THỐNG]", "pytest",
        "tests/test_media_replies.py::test_without_drive_images_the_bot_behaves_as_before"),
    Row("GEN-SYNC-OFF-HARNESS", "Chung", "App chạy không MEDIA_SYNC_ENABLED, hỏi thực đơn",
        "Ảnh static/thuc-don-mau.jpg tải lên như ảnh Drive, không dòng [HỆ THỐNG]", "harness"),
    Row("GEN-URL-SERVED-HARNESS", "Chung", "Ảnh Drive xem qua trình duyệt (url trong GET /media)",
        "GET /static/media/<id>.jpg trả 200 image/jpeg; Messenger không dùng URL này", "harness"),
    Row("GEN-UPLOAD", "Chung", "Mỗi loại ảnh Drive (học phí, thời khoá biểu, cơ sở vật chất, thực đơn)",
        "Gửi bằng file tải lên (multipart filedata, không payload.url), nút trên ảnh cuối; phụ huynh sau nhận cùng ảnh "
        "bằng attachment_id, không tải lại", "pytest",
        "tests/test_media_replies.py::test_drive_images_are_uploaded_then_sent_by_attachment_id_to_the_next_parent"),
    Row("GEN-UPLOAD-ID-REFUSED", "Chung", "Graph từ chối attachment_id đã lưu (vd hết hạn)",
        "Bỏ id đó, tải file lại một lần; lần sau dùng id mới; tải lại cũng lỗi thì là ảnh lỗi như thường", "pytest",
        "tests/test_image_upload.py::test_a_refused_attachment_id_is_forgotten_and_the_file_uploaded_again_once"),
    Row("GEN-UPLOAD-FILE-CHANGED", "Chung", "File ảnh đổi (mtime/kích thước) sau lần tải trước",
        "Tải lại, không dùng attachment_id cũ", "pytest", "tests/test_image_upload.py::test_a_changed_file_is_uploaded_again"),
    Row("GEN-UPLOAD-QA", "Chung", "Ảnh Q&A static/thuc-don-mau.jpg khi tắt đồng bộ",
        "Tải file trong static/ lên", "pytest",
        "tests/test_media_replies.py::test_the_qa_sample_menu_is_uploaded_when_drive_sync_is_off"),
    Row("GEN-QA-PATH-BLOCKED", "Chung", "Ảnh Q&A static/../<file>, file không có hoặc không phải ảnh",
        "Không gửi, log WARNING; nút sang ảnh/tin cuối còn lại", "pytest",
        "tests/test_media_replies.py::test_a_qa_image_that_is_not_an_image_file_in_static_is_not_sent"),
    Row("GEN-UPLOAD-HARNESS", "Chung", "App thật: hành trình thời khoá biểu, rồi phụ huynh khác xin cùng ảnh",
        "IMAGE upload <id>.jpg -> attachment_id=…; phụ huynh sau IMAGE attachment_id=…", "harness"),
    Row("GEN-LOG-PLANNED", "Chung", "Mỗi lượt khi bật đồng bộ", "Log INFO các ảnh định gửi", "pytest",
        "tests/test_media_replies.py::test_every_turn_logs_the_drive_images_it_plans_to_send"),
    Row("GEN-GRAPH-NO-TOKEN", "Chung", "Lỗi Graph khi gửi ảnh/tin", "Log và lỗi không có access token", "pytest",
        "tests/test_media_replies.py::test_graph_errors_are_logged_and_raised_without_the_access_token"),
    Row("GEN-TEST-CHAT", "Chung", "/test-chat", "Model nhận đúng dòng [HỆ THỐNG] như Messenger", "pytest",
        "tests/test_media_replies.py::test_test_chat_tells_the_model_which_images_follow_like_messenger"),
    Row("GEN-TEST-CHAT-NO-TOKEN", "Chung", "/test-chat với câu trả lời có [SEND:]", "Lịch sử không giữ token", "pytest",
        "tests/test_media_replies.py::test_test_chat_keeps_no_send_token_in_the_history"),
    # --- lần đồng bộ ảnh đầu sau khởi động ---
    Row("SYNC-WAIT", "Đồng bộ đầu", "Tin tới khi lần đồng bộ đầu còn chạy (đĩa trống)",
        "Chờ đồng bộ xong rồi trả lời: dòng \"Sau câu trả lời này …\" và ảnh; không WARNING", "pytest",
        "tests/test_media_replies.py::test_a_message_right_after_start_waits_for_the_first_sync_and_gets_the_timetable"),
    Row("SYNC-START-HARNESS", "Đồng bộ đầu", "App thật, tin ngay sau READY", "TEXT rồi IMAGE; log first sync done",
        "harness"),
    Row("SYNC-SLOW", "Đồng bộ đầu", "Đồng bộ đầu lâu hơn MEDIA_FIRST_SYNC_WAIT",
        "Trả lời không ảnh sau hạn; một WARNING", "pytest",
        "tests/test_media_replies.py::test_a_first_sync_slower_than_the_wait_still_gets_an_answer_without_images"),
    Row("SYNC-DEADLINE", "Đồng bộ đầu", "Nhiều tin tới trong và sau lúc chờ đồng bộ đầu",
        "Một hạn chung = lúc bắt đầu đồng bộ + MEDIA_FIRST_SYNC_WAIT: tin giữa chừng chờ phần còn lại, tin sau hạn không "
        "chờ; WARNING một lần", "pytest",
        "tests/test_media_replies.py::test_every_message_waits_for_the_first_sync_until_one_deadline"),
    Row("SYNC-TYPING", "Đồng bộ đầu", "Đang chờ đồng bộ đầu", "\"đang soạn\" bật lại mỗi TYPING_REFRESH_EVERY, dừng khi xong",
        "pytest", "tests/test_media_replies.py::test_waiting_for_the_first_sync_keeps_the_typing_indicator_on"),
    Row("SYNC-OFF-NO-WAIT", "Đồng bộ đầu", "Tắt MEDIA_SYNC_ENABLED hoặc thiếu LEADS_SHEET_WEBHOOK_URL",
        "Không chờ, không gọi Apps Script", "pytest",
        "tests/test_media_replies.py::test_with_media_sync_off_a_message_does_not_wait"),
    Row("SYNC-FAILED", "Đồng bộ đầu", "Lần đồng bộ đầu lỗi", "Tin đó trả lời khi lỗi; tin sau không chờ lần đồng bộ kế",
        "pytest", "tests/test_media_replies.py::test_a_failed_first_sync_answers_then_and_no_later_message_waits"),
    Row("SYNC-DISK", "Đồng bộ đầu", "Ảnh của lần chạy trước còn trên đĩa", "Dùng ngay, không chờ", "pytest",
        "tests/test_media_replies.py::test_images_kept_on_disk_from_before_the_restart_are_used_without_waiting"),
    Row("SYNC-TEST-CHAT", "Đồng bộ đầu", "/test-chat ngay sau khởi động", "Chờ đồng bộ đầu như Messenger", "pytest",
        "tests/test_media_replies.py::test_test_chat_right_after_start_waits_for_the_first_sync"),
]

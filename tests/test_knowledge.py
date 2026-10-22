"""Kiến thức của bot khớp kịch bản tư vấn mới và các quyết định của trường.

Mỗi test ứng với một quyết định; sửa dữ liệu chứ đừng nới test, trừ khi trường đổi quyết định.
"""
import asyncio
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import customer_memory
from app.ai_engine import AIProvider
from app.config import settings
from app.coverage import topics_in_reply
from app.qa_database import QADatabase

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "qa_database.json"
PAIRS = json.loads(DB_PATH.read_text(encoding="utf-8"))["qa_pairs"]


def _norm(text: str) -> str:
    text = text.lower().replace("–", "-").replace("—", "-").replace("m²", "m2")
    return re.sub(r"\s+", " ", text)


ANSWERS = [_norm(p["answer"]) for p in PAIRS]
ALL_ANSWERS = "\n".join(ANSWERS)
ALL_TEXT = "\n".join(_norm(" ".join(p["questions"]) + " " + p["answer"]) for p in PAIRS)
# Gồm cả category và keywords: thứ bot không được nói thì cũng không được còn làm từ khóa gợi ý.
RAW_TEXT = "\n".join(_norm(json.dumps(p, ensure_ascii=False)) for p in PAIRS)


def _answers_with(*needles: str) -> list[str]:
    return [a for a in ANSWERS if all(_norm(n) in a for n in needles)]


# --- Cấu trúc -----------------------------------------------------------------

def test_every_pair_has_valid_shape():
    assert len(PAIRS) >= 60
    for p in PAIRS:
        assert isinstance(p["category"], str) and p["category"].strip()
        assert isinstance(p["questions"], list) and p["questions"]
        assert all(isinstance(q, str) and q.strip() for q in p["questions"])
        assert isinstance(p["answer"], str) and p["answer"].strip()
        assert isinstance(p.get("keywords", []), list)
        for url in p.get("images", []):
            # "static/<file>": bot tự phục vụ tại {PUBLIC_BASE_URL}/static/<file>, nên file phải có trong repo
            assert url.startswith(("http://", "https://")) or (
                url.startswith("static/") and (DB_PATH.parents[1] / url).is_file()
            ), url


def test_no_question_is_duplicated_across_pairs():
    seen = {}
    for i, p in enumerate(PAIRS):
        for q in p["questions"]:
            key = _norm(q).strip(" ?.")
            assert key not in seen, f"câu hỏi trùng ở cặp {seen[key]} và {i}: {q}"
            seen[key] = i


def test_prompt_context_stays_compact():
    context = QADatabase(str(DB_PATH)).build_context()
    assert len(context) <= 75_000, len(context)


def test_internal_notes_are_not_in_answers():
    for word in ["sửa lại", "remarketing", "telesale", "chốt sale", "lưu sẵn"]:
        assert word not in ALL_TEXT, word


def test_admin_learned_questions_are_kept():
    questions = {_norm(q) for p in PAIRS for q in p["questions"]}
    assert _norm("Bên hệ quốc tế có được xem camera 24/7 k") in questions
    assert _norm("các bé chưa ăn cơmthì trường có bữa cháo cho bé k") in questions


# --- Quyết định 1: tuổi nhận ---------------------------------------------------

def test_admission_age_is_15_months_walking_steadily():
    assert _answers_with("15 tháng", "đi vững")
    assert not re.search(r"18 tháng (đến|tới|-) ?6 tuổi", ALL_TEXT)
    assert not re.search(r"nhận (bé|trẻ|con)[^.\n]{0,40}18 tháng", ALL_TEXT)


# --- Quyết định 2–3: ưu đãi ----------------------------------------------------

def test_payment_term_discounts_have_no_percentages():
    patterns = [
        r"(giảm|ưu đãi)[^.\n]{0,30}\d+ ?%[^.\n]{0,40}(đóng|thanh toán) ?(6|12|sáu|mười hai) tháng",
        r"(đóng|thanh toán) ?(6|12) tháng[^.\n]{0,20}(giảm|ưu đãi)[^.\n]{0,20}\d+ ?%",
        r"giảm (đến|tới) \d+ ?%",
        r"cộng dồn[^.\n]{0,80}\d+ ?%",
    ]
    for pattern in patterns:
        match = re.search(pattern, ALL_TEXT)
        assert not match, match and match.group(0)


def test_generic_offer_wording_exists():
    assert "ưu đãi hấp dẫn" in ALL_ANSWERS


def test_sibling_and_resident_policy_per_campus():
    sibling = "\n".join(_answers_with("bé thứ 2"))
    assert sibling, "thiếu câu trả lời về ưu đãi bé thứ 2"
    assert re.search(r"(quốc tế|mỹ đình|chùa láng)[^\n]*10 ?%", sibling)
    assert re.search(r"kim mã[^\n]*5 ?%", sibling)
    resident = "\n".join(_answers_with("cư dân"))
    assert re.search(r"cư dân[^.\n]{0,40}5 ?%|5 ?%[^.\n]{0,40}cư dân", resident)
    assert re.search(r"kim mã[^.\n]{0,80}không[^.\n]{0,40}cư dân|không[^.\n]{0,40}cư dân[^.\n]{0,80}kim mã", resident)
    assert "15%" not in sibling.replace(" %", "%")


# --- Quyết định 4: đồng phục ---------------------------------------------------

def test_no_uniform_voucher():
    assert not re.search(r"voucher[^.\n]{0,40}đồng phục|đồng phục[^.\n]{0,80}voucher", ALL_TEXT)


# --- Quyết định 5–6: đón muộn, đón sớm, đón con -------------------------------

def test_late_and_early_pickup_packages():
    assert "500.000" not in ALL_TEXT and "500k" not in ALL_TEXT
    late = _answers_with("17h30", "trông muộn")
    assert late and any("theo tháng" in a for a in late)
    assert _answers_with("trông sớm")


def test_pickup_only_down_to_lobby():
    assert _answers_with("xuống sảnh")
    assert not re.search(r"ra (tận )?xe\b", ALL_TEXT)


# --- Quyết định 7: diện tích ---------------------------------------------------

def test_classroom_area_per_campus():
    assert re.search(r"mỹ đình[^.\n]{0,60}80 ?- ?90 ?m2", ALL_ANSWERS)
    assert not re.search(r"mỹ đình[^.\n]{0,80}90 ?- ?100", ALL_TEXT)
    assert re.search(r"chùa láng[^.\n]{0,60}90 ?- ?100 ?m2", ALL_ANSWERS)


# --- Quyết định 8: dã ngoại ----------------------------------------------------

def test_field_trips_six_per_year():
    assert re.search(r"6 chuyến ?(/|mỗi|một|trong) ?(năm|1 năm)", ALL_ANSWERS)
    assert not re.search(r"2 tháng ?(/|một|1) ?lần", ALL_TEXT)


# --- Quyết định 9: chương trình Cambridge --------------------------------------

def test_programme_is_cambridge_early_years():
    assert len(_answers_with("cambridge early years")) >= 3
    for outdated in ["ams/ami", "ams", "ami", "oxford phonics", "montessori nguyên bản", "chuẩn montessori quốc tế"]:
        assert not re.search(rf"\b{re.escape(outdated)}\b", ALL_TEXT), outdated


# --- Dữ kiện cốt lõi từ kịch bản ----------------------------------------------

@pytest.mark.parametrize("address", ["185 huỳnh thúc kháng", "36 phạm hùng", "294 kim mã"])
def test_campus_addresses(address):
    assert address in ALL_ANSWERS


def test_campus_systems():
    assert re.search(r"kim mã[^.\n]{0,40}song ngữ|song ngữ[^.\n]{0,40}kim mã", ALL_ANSWERS)
    assert re.search(r"(chùa láng|mỹ đình)[^.\n]{0,40}quốc tế|quốc tế[^.\n]{0,40}(chùa láng|mỹ đình)", ALL_ANSWERS)


def test_opening_day_and_rolling_admission():
    assert _answers_with("05/09", "quanh năm")


def test_free_one_week_trial():
    assert re.search(r"1 tuần học thử[^.\n]{0,40}miễn phí|học thử[^.\n]{0,20}1 tuần[^.\n]{0,40}miễn phí", ALL_ANSWERS)
    assert "tối đa 2 tuần" not in ALL_TEXT


def test_no_tuition_fee_amounts():
    assert not re.search(r"học phí[^.\n]{0,40}\d{1,3}([.,]\d{3}){2}", ALL_ANSWERS)


# --- Phản hồi đợt 2 -----------------------------------------------------------

def test_workshop_is_removed():
    assert not [p["questions"][0] for p in PAIRS if _norm(p["category"]) == "workshop"]
    assert "phan thúy" not in RAW_TEXT
    assert "cô thúy" not in RAW_TEXT


# --- Phản hồi đợt 3 -----------------------------------------------------------

BUS = r"xe (bus|buýt)"


def _without_bus_promise(text: str) -> str:
    return text.replace("chưa có tuyến", "").replace("mở tuyến", "")


def test_bus_answer_says_no_route_until_enough_parents_register():
    # Phản hồi đợt 3: chưa có tuyến xe bus; khi đủ phụ huynh đăng ký, Nhà trường sẽ mở tuyến.
    bus_answers = [a for p, a in zip(PAIRS, ANSWERS) if re.search(BUS, _norm(" ".join(p["questions"])))]
    assert bus_answers, "thiếu câu trả lời về xe bus"
    for answer in bus_answers:
        assert "chưa có tuyến" in answer and "đủ phụ huynh đăng ký" in answer, answer
        assert "khu vực" in answer and "sđt" in answer, answer
        assert "tuyến" not in _without_bus_promise(answer), answer


def test_bus_has_no_route_radius_fee_or_offer():
    assert "bán kính" not in RAW_TEXT
    # Chỉ được nói chưa có tuyến / sẽ mở tuyến, không nêu tuyến cụ thể.
    assert not re.search(r"tuyến (xe|gần nhất|phù hợp|đưa đón)", _without_bus_promise(RAW_TEXT))
    for pattern in (rf"{BUS}[^.\n]{{0,60}}(phí|ưu đãi|tính riêng)", rf"(phí|ưu đãi)[^.\n]{{0,30}}{BUS}"):
        match = re.search(pattern, RAW_TEXT)
        assert not match, match and match.group(0)


# --- Phản hồi đợt 4 -----------------------------------------------------------

MENU_IMAGE = "static/thuc-don-mau.jpg"
MENU_QUESTION = "Thực đơn của trường như thế nào ạ?"


def _pair_with_question(question: str) -> dict:
    return next(p for p in PAIRS if question in p["questions"])


def test_sample_menu_image_is_a_jpeg_messenger_accepts():
    data = (DB_PATH.parents[1] / MENU_IMAGE).read_bytes()

    assert data[:3] == b"\xff\xd8\xff" and data[-2:] == b"\xff\xd9"
    assert len(data) < 8 * 1024 * 1024


def test_general_menu_question_sends_the_sample_menu():
    assert _pair_with_question(MENU_QUESTION).get("images") == [MENU_IMAGE]
    # Cặp chỉ hỏi cháo/ăn thô không kèm ảnh thực đơn.
    assert "images" not in _pair_with_question("Trường có nấu cháo cho bé không?")


def test_menu_answer_matches_the_sample_menu_image():
    menu = _norm(_pair_with_question(MENU_QUESTION)["answer"])

    for meal in ("bữa sáng", "bữa nhẹ sáng", "bữa trưa", "bữa chiều", "phụ chiều"):
        assert meal in menu, meal
    for dish in ("bún mọc", "cơm tám thơm", "cá sốt cà chua", "sữa tươi vinamilk không đường"):
        assert dish in menu, dish
    for old_dish in ("tứ xuyên", "bún thịt nấu chua", "phở bò sốt vang", "thịt ngâm mắm"):
        assert old_dish not in RAW_TEXT, old_dish


def test_menu_reply_sends_the_real_menu_image_parents_can_open(monkeypatch):
    """Model đọc dòng Images của cặp thực đơn trong Q&A thật; bot gửi ảnh tới URL công khai, và URL đó mở được."""
    images_line = re.compile(rf"Q: {re.escape(MENU_QUESTION)}[^\n]*\n   A: [^\n]*\n   Images: ([^\n]+)")

    class MenuModel(AIProvider):
        async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024):
            match = images_line.search(system_prompt)
            return f"Dạ đây là thực đơn mẫu của Casa ạ. [IMAGES:{match.group(1)}]" if match else "Dạ vâng ạ."

    sent = []

    async def send_message(recipient_id, text, quick_replies=None):
        sent.append(("text", text))

    async def send_image(recipient_id, image_url, quick_replies=None):
        sent.append(("image", image_url))

    async def nothing(*args, **kwargs):
        return {}

    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://casa.example/")
    monkeypatch.setattr(settings, "AI_MODEL_ORDER", ["menu"])
    monkeypatch.setattr(main.ai_engine, "_providers", {"menu": MenuModel()})
    monkeypatch.setattr(main.ai_engine, "extract_customer_info", nothing)
    monkeypatch.setattr(main, "send_message", send_message)
    monkeypatch.setattr(main, "send_image", send_image)
    monkeypatch.setattr(main, "send_typing_indicator", nothing)
    monkeypatch.setattr(main, "get_user_profile", nothing)
    monkeypatch.setattr(customer_memory, "sync_to_github", nothing)

    asyncio.run(main.process_message("9000000000000601", "Cho em xem thực đơn của trường"))

    assert sent == [
        ("text", "Dạ đây là thực đơn mẫu của Casa ạ."),
        ("image", "https://casa.example/static/thuc-don-mau.jpg"),
    ]
    resp = TestClient(main.app).get("/static/thuc-don-mau.jpg")
    assert resp.status_code == 200 and resp.headers["content-type"] == "image/jpeg"


FULL_CAMBRIDGE = ("mathematics", "let's explore", "understanding the world", "toán")


def _clauses(text: str) -> list[str]:
    return [c for c in re.split(r"[.;:\n]", text) if c.strip()]


def test_only_international_system_studies_all_three_cambridge_subjects():
    # Phản hồi đợt 4 (G2): hệ Quốc tế học đủ English, Mathematics, Let's Explore; Kim Mã chỉ môn English.
    assert "understanding the world" not in RAW_TEXT
    for answer in ANSWERS:
        for clause in _clauses(answer):
            if "kim mã" in clause or "song ngữ" in clause:
                assert not any(s in clause for s in FULL_CAMBRIDGE), clause
        if "mathematics" in answer or "let's explore" in answer:
            assert "quốc tế" in answer, answer


@pytest.mark.parametrize("question", ["Hiện Casa đang áp dụng chương trình học nào?", "Con học những môn gì ở trường?"])
def test_programme_answer_states_cambridge_subjects_per_system(question):
    answer = _norm(_pair_with_question(question)["answer"])

    assert re.search(r"quốc tế[^.;]{0,120}english[^.;]{0,40}mathematics[^.;]{0,40}let's explore", answer), answer
    assert re.search(r"kim mã[^.;]{0,80}english", answer), answer


def test_kim_ma_cambridge_question_is_answered():
    answer = _norm(_pair_with_question("Kim Mã có học Cambridge không?")["answer"])

    assert re.search(r"kim mã[^.;]{0,80}english", answer), answer


# --- Phản hồi đợt 5 -----------------------------------------------------------

# Phản hồi đợt 6: 5 lĩnh vực Montessori ("văn hoá" hay "văn hóa" đều được).
MONTESSORI_AREAS = ("ngôn ngữ", "toán", "thực hành cuộc sống", "giác quan", r"văn h(?:oá|óa)")


def _missing_areas(text: str) -> list[str]:
    return [area for area in MONTESSORI_AREAS if not re.search(area, text)]


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.?!])\s+|\n", text) if s.strip()]


def test_school_has_more_than_ten_years():
    # D7: "Hơn 10 năm". Kinh nghiệm cá nhân của giáo viên ("10 năm chuyên sâu Montessori") giữ nguyên.
    assert "gần 10 năm" not in RAW_TEXT
    assert re.search(r"hơn 10 năm[^.\n]{0,20}(montessori|hoạt động)", ALL_ANSWERS)


def test_kim_ma_classroom_is_80_m2_per_floor_in_a_garden_villa():
    # D1: biệt thự sân vườn xanh mát, mỗi tầng 1 lớp học rộng 80 m².
    assert "điều kiện thực tế của địa điểm" not in RAW_TEXT
    kim_ma = _answers_with("kim mã", "biệt thự sân vườn", "mỗi tầng là 1 lớp học")
    assert len(kim_ma) >= 2, "thiếu câu diện tích lớp / so sánh cơ sở cho Kim Mã"
    for answer in kim_ma:
        assert re.search(r"kim mã[^.\n]{0,120}80 ?m2", answer), answer
    area = _norm(_pair_with_question("Diện tích lớp học của trường khoảng bao nhiêu m²?")["answer"])
    for campus, size in (("chùa láng", r"90 ?- ?100 ?m2"), ("mỹ đình", r"80 ?- ?90 ?m2"), ("kim mã", r"80 ?m2")):
        assert re.search(rf"{campus}[^.\n]{{0,120}}{size}", area), campus


def test_kim_ma_facilities_answers_are_still_detected_as_facilities():
    for question in ("Diện tích lớp ở Kim Mã bao nhiêu?", "Cơ sở vật chất ở Kim Mã như thế nào?"):
        assert "facilities" in topics_in_reply(_pair_with_question(question)["answer"]), question


@pytest.mark.parametrize("question", ["Kim Mã học toán như thế nào?", "Hệ Song ngữ học những gì ngoài tiếng Anh?"])
def test_kim_ma_continues_montessori_in_its_areas(question):
    # D2 + đợt 6: Montessori theo đủ 5 lĩnh vực + ngoại khóa phong phú.
    reply = _pair_with_question(question)["answer"]
    answer = _norm(reply)

    assert "kim mã" in answer and "montessori" in answer and "english" in answer
    assert not _missing_areas(answer), answer
    assert "ngoại khóa phong phú" in answer
    assert {"program", "extracurricular"} <= set(topics_in_reply(reply))


def test_tuition_is_paid_by_quarter_6_or_12_months_never_monthly():
    # Đợt 6: "học phí thu theo quý, 6 tháng hoặc 12 tháng"; D3: không thu theo tháng.
    payment = _norm(_pair_with_question("Có đóng học phí theo tháng được không?")["answer"])
    assert "thu theo quý, 6 tháng hoặc 12 tháng" in payment, payment
    assert re.search(r"không thu (học phí )?theo tháng", payment), payment
    # Học phí hay tổng chi phí "theo tháng" chỉ được nói ở câu phủ định. Gói trông sớm/muộn theo tháng và phí
    # đầu kỳ thu tròn theo tháng là dữ kiện đúng, không phải học phí.
    for answer in ANSWERS:
        for sentence in _sentences(answer):
            if re.search(r"(học|chi) phí", sentence) and re.search(r"(theo|hằng|mỗi) tháng", sentence):
                assert re.search(r"không (thu|đóng)[^.;]*(theo|hằng|mỗi) tháng", sentence), sentence


def test_camera_can_be_viewed_at_the_office_during_office_hours():
    # D4: trong giờ hành chính, không cần có sự việc cụ thể.
    assert "sự việc cụ thể" not in RAW_TEXT
    camera = _norm(_pair_with_question("Phụ huynh có được xem camera không?")["answer"])
    assert "văn phòng" in camera and "giờ hành chính" in camera
    assert re.search(r"không[^.\n]{0,40}trực tiếp trên điện thoại", camera)


def test_resident_discount_names_the_two_buildings():
    # D5: cư dân tòa Hongkong Tower (Chùa Láng) và FLC Complex (Mỹ Đình); Kim Mã không có.
    resident = _norm(_pair_with_question("Cư dân tòa nhà có được ưu đãi không?")["answer"])
    assert re.search(r"cư dân[^.\n]{0,120}hongkong tower[^.\n]{0,20}chùa láng", resident), resident
    assert re.search(r"cư dân[^.\n]{0,160}flc complex[^.\n]{0,20}mỹ đình", resident), resident


def test_upfront_fees_are_rounded_by_month_until_june_and_collected_in_july():
    # D6: nhập học giữa năm → phí phát triển trường, phí học liệu và hoạt động ngoại khóa thu tròn theo tháng tới
    # hết tháng 6; thu tròn năm vào tháng 7. Các dữ kiện cũ giữ nguyên.
    questions = ("Nếu bé nhập học giữa tháng thì học phí được tính thế nào?", "Nhập học giữa năm thì các khoản phí đầu kỳ tính thế nào?")
    for question in questions:
        answer = _norm(_pair_with_question(question)["answer"])
        assert "phí phát triển trường" in answer and "phí học liệu và hoạt động ngoại khóa" in answer, question
        assert re.search(r"tròn theo tháng[^.\n]{0,60}tháng bé nhập học[^.\n]{0,30}tháng 6", answer), question
        assert re.search(r"tròn năm[^.\n]{0,40}tháng 7", answer), question
    assert _answers_with("số ngày thực tế đi học", "tháng đầu")
    assert _answers_with("tối thiểu 1 tháng", "tối đa 6 tháng")
    assert _answers_with("5 ngày làm việc đầu tiên của quý", "nộp muộn")
    assert _answers_with("trước 7:00", "quý tiếp theo")


# --- Vòng sửa sau review đợt 5 ------------------------------------------------

FIVE_AREAS_QUESTIONS = ("5 lĩnh vực Montessori là những gì?", "5 lĩnh vực đó gồm những gì?")
# Lĩnh vực trường không kể thì bot không được thêm vào 5 lĩnh vực Montessori.
UNLISTED_AREAS = ("tiếng việt", "khoa học", "địa lý", "nghệ thuật")


def _full_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.?!…])\s+|\n", text) if s.strip()]


def test_kim_ma_cambridge_answers_say_cambridge_is_for_3_to_6():
    # Quy tắc chương trình: Cambridge cho trẻ 3–6 tuổi; 15 tháng–3 tuổi chưa học Cambridge.
    for answer in _answers_with("kim mã", "cambridge"):
        assert any("cambridge" in s and "3-6 tuổi" in s for s in _full_sentences(answer)), answer
    kim_ma = _norm(_pair_with_question("Chương trình học ở cơ sở Kim Mã như thế nào?")["answer"])
    assert re.search(r"(dưới 3 tuổi|15 tháng-3 tuổi)[^.]{0,80}montessori", kim_ma), kim_ma


def test_montessori_five_areas_answer_names_all_five():
    pairs = [_pair_with_question(q) for q in FIVE_AREAS_QUESTIONS]
    assert pairs[0] is pairs[1]
    reply = pairs[0]["answer"]
    answer = _norm(reply)
    assert not _missing_areas(answer), answer
    assert "tư vấn viên" in answer and "sđt/zalo" in answer and "tham quan" in answer, answer
    assert "program" in topics_in_reply(reply)


@pytest.mark.parametrize(
    "question",
    [
        "Hiện Casa đang áp dụng chương trình học nào?",
        "Con học những môn gì ở trường?",
        "Chương trình học ở cơ sở Kim Mã như thế nào?",
        "Giáo cụ, đồ chơi của trường được lựa chọn như thế nào?",
    ],
)
def test_programme_answers_list_the_five_montessori_areas(question):
    answer = _norm(_pair_with_question(question)["answer"])
    assert any("5 lĩnh vực" in s and not _missing_areas(s) for s in _full_sentences(answer)), answer


def test_every_montessori_area_list_is_complete():
    # Không còn liệt kê dở kiểu "toán, tiếng Việt, thực hành cuộc sống, giác quan…".
    assert not re.search(r"(tiếng việt|giác quan|toán)\s*(…|\.\.\.)", ALL_ANSWERS)
    for text in ANSWERS:
        for sentence in _full_sentences(text):
            if "5 lĩnh vực" in sentence:
                assert not _missing_areas(sentence), sentence
                assert "…" not in sentence, sentence
                assert not any(a in sentence for a in UNLISTED_AREAS), sentence


def test_playground_answer_does_not_claim_kim_ma_garden_play():
    reply = _pair_with_question("Trường có sân chơi không?")["answer"]

    assert "biệt thự sân vườn" not in _norm(reply)
    assert "facilities" in topics_in_reply(reply)

"""Kiến thức của bot khớp kịch bản tư vấn mới và các quyết định của trường.

Mỗi test ứng với một quyết định; sửa dữ liệu chứ đừng nới test, trừ khi trường đổi quyết định.
"""
import json
import re
from pathlib import Path

import pytest

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
            assert url.startswith(("http://", "https://"))


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


def test_bus_is_not_advised():
    # Tạm thời không tư vấn xe bus: không tuyến, bán kính, phí hay ưu đãi xe bus.
    bus = r"xe (bus|buýt)"
    assert "bán kính" not in RAW_TEXT
    assert not re.search(r"tuyến (xe|gần nhất|phù hợp|đưa đón)", RAW_TEXT)
    for pattern in (rf"{bus}[^.\n]{{0,60}}(phí|ưu đãi|tuyến|tính riêng)", rf"(phí|ưu đãi)[^.\n]{{0,30}}{bus}"):
        match = re.search(pattern, RAW_TEXT)
        assert not match, match and match.group(0)

"""Trạng thái tư vấn của từng khách: giai đoạn, thông tin còn thiếu, khối [TRẠNG THÁI TƯ VẤN] trong prompt,
và set_fields ghi trường không phải tin nhắn mới (referral, follow-up) mà không đổi last_seen/message_count."""

import asyncio
import json
from pathlib import Path

import pytest

from app import customer_memory
from app.customer_memory import STAGES, format_profile_for_prompt, lead_stage, missing_fields

CUSTOMER_ID = "9000000000000301"
PHONE = "0900000301"
AD_TITLE = "Học thử 1 tuần miễn phí"


def test_stages_in_funnel_order():
    assert STAGES == ("Mới", "Đã biết tuổi/cơ sở", "Đã có SĐT", "Đã hẹn tham quan/học thử")


@pytest.mark.parametrize(
    ("profile", "stage"),
    [
        ({}, "Mới"),
        ({"parent_name": "Lan Thử", "message_count": 3, "concerns": ["học phí"]}, "Mới"),
        ({"phone_declined": True}, "Mới"),
        ({"kid_age": "3 tuổi"}, "Đã biết tuổi/cơ sở"),
        ({"interested_campus": "Kim Mã"}, "Đã biết tuổi/cơ sở"),
        ({"area": "Cầu Giấy"}, "Đã biết tuổi/cơ sở"),
        ({"address": "Cầu Giấy"}, "Đã biết tuổi/cơ sở"),
        ({"kid_age": "3 tuổi", "phone_declined": True}, "Đã biết tuổi/cơ sở"),
        ({"phone": PHONE}, "Đã có SĐT"),
        ({"kid_age": "3 tuổi", "interested_campus": "Kim Mã", "phone": PHONE}, "Đã có SĐT"),
        ({"visit_request": "tham quan sáng thứ 7"}, "Đã hẹn tham quan/học thử"),
        ({"kid_age": "3 tuổi", "phone": PHONE, "visit_request": "học thử tuần sau"}, "Đã hẹn tham quan/học thử"),
    ],
)
def test_lead_stage(profile, stage):
    assert lead_stage(profile) == stage


@pytest.mark.parametrize(
    ("profile", "missing"),
    [
        ({}, ["tuổi bé", "cơ sở/khu vực", "SĐT/Zalo"]),
        ({"kid_age": "3 tuổi"}, ["cơ sở/khu vực", "SĐT/Zalo"]),
        ({"interested_campus": "Mỹ Đình"}, ["tuổi bé", "SĐT/Zalo"]),
        ({"area": "Cầu Giấy"}, ["tuổi bé", "SĐT/Zalo"]),
        ({"address": "Cầu Giấy"}, ["tuổi bé", "SĐT/Zalo"]),
        ({"phone": PHONE}, ["tuổi bé", "cơ sở/khu vực"]),
        ({"kid_age": "3 tuổi", "phone_declined": True}, ["cơ sở/khu vực"]),
        ({"kid_age": "3 tuổi", "interested_campus": "Kim Mã", "phone": PHONE}, []),
    ],
)
def test_missing_fields(profile, missing):
    assert missing_fields(profile) == missing


def test_empty_profile_gives_no_prompt_context():
    assert format_profile_for_prompt({}) == ""


def test_prompt_shows_known_info_then_state_then_summaries():
    profile = {
        "parent_name": "Lan Thử",
        "area": "Cầu Giấy",
        "expected_start": "tháng 9",
        "phone_declined": True,
        "lead_source": "ads",
        "ad_title": AD_TITLE,
        "session_summaries": [{"date": "2026-10-01", "summary": "Hỏi học phí hệ song ngữ"}],
    }

    assert format_profile_for_prompt(profile) == (
        "[THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT]:\n"
        "- Phụ huynh: Lan Thử\n"
        "- Khu vực: Cầu Giấy\n"
        "- Dự kiến nhập học: tháng 9\n"
        "\n"
        "[TRẠNG THÁI TƯ VẤN]:\n"
        "- Giai đoạn: Đã biết tuổi/cơ sở\n"
        "- Còn thiếu: tuổi bé\n"
        "- Phụ huynh đã từ chối để lại SĐT: có\n"
        f'- Nguồn: quảng cáo "{AD_TITLE}"\n'
        "\n"
        "[TÓM TẮT CÁC LẦN TRÒ CHUYỆN TRƯỚC ĐÂY]:\n"
        "- [2026-10-01] Hỏi học phí hệ song ngữ\n"
    )


def test_prompt_state_for_visit_with_phone():
    profile = {
        "kid_age": "4 tuổi",
        "interested_campus": "Mỹ Đình",
        "phone": PHONE,
        "phone_declined": True,
        "visit_request": "tham quan sáng thứ 7",
        "lead_source": "link",
    }

    context = format_profile_for_prompt(profile)

    assert context.endswith(
        "[TRẠNG THÁI TƯ VẤN]:\n"
        "- Giai đoạn: Đã hẹn tham quan/học thử\n"
        "- Đã hẹn: tham quan sáng thứ 7"
    )
    assert f"- SĐT: {PHONE}" in context
    for absent in ("Còn thiếu", "từ chối", "Nguồn"):
        assert absent not in context


def test_prompt_state_for_new_customer_from_ads():
    """Khách vừa bấm quảng cáo, chưa nói gì: chỉ có khối trạng thái."""
    context = format_profile_for_prompt({"lead_source": "ads", "ad_title": AD_TITLE})

    assert context == (
        "[TRẠNG THÁI TƯ VẤN]:\n"
        "- Giai đoạn: Mới\n"
        "- Còn thiếu: tuổi bé, cơ sở/khu vực, SĐT/Zalo\n"
        f'- Nguồn: quảng cáo "{AD_TITLE}"'
    )


def saved_profile() -> dict:
    return json.loads(Path(customer_memory.CUSTOMERS_PATH).read_text(encoding="utf-8"))[CUSTOMER_ID]


def test_set_fields_keeps_last_seen_and_message_count():
    customer_memory._customers[CUSTOMER_ID] = {
        "kid_age": "3 tuổi",
        "first_seen": "2026-10-01T08:00:00",
        "last_seen": "2026-10-01T09:00:00",
        "message_count": 4,
    }

    customer_memory.set_fields(CUSTOMER_ID, {"followup_sent_at": "2026-10-01T15:00:00+07:00"})

    expected = {
        "kid_age": "3 tuổi",
        "first_seen": "2026-10-01T08:00:00",
        "last_seen": "2026-10-01T09:00:00",
        "message_count": 4,
        "followup_sent_at": "2026-10-01T15:00:00+07:00",
    }
    assert customer_memory.get_profile(CUSTOMER_ID) == expected
    assert saved_profile() == expected


def test_set_fields_on_new_customer_does_not_count_as_a_message():
    customer_memory.set_fields(CUSTOMER_ID, {"lead_source": "ads", "ad_title": AD_TITLE})

    assert saved_profile() == {"lead_source": "ads", "ad_title": AD_TITLE}
    assert customer_memory.get_last_seen_gap_hours(CUSTOMER_ID) == 0.0

    profile = asyncio.run(customer_memory.update_profile(CUSTOMER_ID, {"kid_age": "3 tuổi"}))

    assert profile["message_count"] == 1
    assert profile["lead_source"] == "ads"

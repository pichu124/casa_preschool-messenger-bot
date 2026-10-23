"""Số liệu cho người vận hành: phễu tư vấn tính từ hồ sơ khách (không mất khi deploy như analytics.jsonl),
file Excel /customers/export, và /test-chat xử lý kết quả trích xuất giống tin Messenger thật."""

import io
import re
from types import SimpleNamespace

import openpyxl
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import analytics, customer_memory
from app.ai_engine import AIResponse
from app.config import settings

client = TestClient(main.app)

WEBHOOK_SECRET = "tg-secret_funnel"

SAMPLE_PROFILES = {
    "9000000000000301": {"parent_name": "Lan Thử", "message_count": 1},
    "9000000000000302": {"kid_age": "3 tuổi"},
    "9000000000000303": {"interested_campus": "Mỹ Đình", "lead_source": "ads", "ad_title": "Học thử 1 tuần"},
    "9000000000000304": {"area": "Cầu Giấy", "phone_declined": True},
    "9000000000000305": {
        "kid_age": "4 tuổi",
        "interested_campus": "Kim Mã",
        "phone": "0900000305",
        "lead_source": "ads",
    },
    "9000000000000306": {"phone": "0900000306", "visit_request": "tham quan sáng thứ 7", "lead_source": "link"},
    "9000000000000307": {"visit_request": "học thử tuần sau"},
}
SAMPLE_FUNNEL = {
    "total": 7,
    "with_kid_age": 2,
    "with_campus": 2,
    "with_phone": 2,
    "with_visit": 2,
    "from_ads": 2,
    "stages": {
        "Mới": 1,
        "Đã biết tuổi/cơ sở": 3,
        "Đã có SĐT": 1,
        "Đã hẹn tham quan/học thử": 2,
    },
}


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)


def test_funnel_stats_counts_sample_profiles():
    assert analytics.funnel_stats(SAMPLE_PROFILES) == SAMPLE_FUNNEL


def test_funnel_stats_of_no_customer_lists_every_stage_at_zero():
    funnel = analytics.funnel_stats({})

    assert funnel["total"] == 0
    assert funnel["stages"] == {stage: 0 for stage in customer_memory.STAGES}


def test_analytics_stats_carries_funnel_from_customer_profiles(admin):
    customer_memory._customers.update(SAMPLE_PROFILES)

    resp = client.get("/analytics/stats", params={"secret": WEBHOOK_SECRET})

    assert resp.status_code == 200
    body = resp.json()
    assert body["funnel"] == SAMPLE_FUNNEL
    assert body["total_messages"] == 0  # analytics.jsonl trống: phễu vẫn có số


def test_dashboard_shows_every_funnel_figure_and_the_deploy_caveat(admin):
    html = client.get("/dashboard", params={"secret": WEBHOOK_SECRET}).text

    for key in SAMPLE_FUNNEL:
        assert re.search(rf"\b{key}\b", html), f"dashboard không hiển thị funnel.{key}"
    assert "funnel" in html
    assert "chỉ tính từ lần deploy gần nhất" in html


NEW_EXPORT_COLUMNS = {
    "Khu vực": "Cầu Giấy",
    "Dự kiến nhập học": "tháng 9/2027",
    "Hẹn tham quan/học thử": "tham quan sáng thứ 7",
    "Nguồn": "Học thử 1 tuần",
    "Giai đoạn": "Đã hẹn tham quan/học thử",
    "Đã từ chối SĐT": "Có",
}


def export_rows() -> dict[str, dict]:
    resp = client.get("/customers/export", params={"secret": WEBHOOK_SECRET})
    assert resp.status_code == 200
    rows = list(openpyxl.load_workbook(io.BytesIO(resp.content)).active.iter_rows(values_only=True))
    headers = rows[0]
    return {row[0]: dict(zip(headers, row)) for row in rows[1:]}


def test_export_has_consulting_columns(admin):
    customer_memory._customers.update(
        {
            "9000000000000311": {
                "kid_age": "3 tuổi",
                "area": "Cầu Giấy",
                "expected_start": "tháng 9/2027",
                "visit_request": "tham quan sáng thứ 7",
                "lead_source": "ads",
                "ad_title": "Học thử 1 tuần",
                "phone_declined": True,
            },
            "9000000000000312": {"kid_age": "2 tuổi"},
        }
    )

    rows = export_rows()

    full = rows["9000000000000311"]
    assert {column: full[column] for column in NEW_EXPORT_COLUMNS} == NEW_EXPORT_COLUMNS
    assert full["Tuổi bé"] == "3 tuổi"
    bare = rows["9000000000000312"]
    assert bare["Giai đoạn"] == "Đã biết tuổi/cơ sở"
    assert [c for c in NEW_EXPORT_COLUMNS if c != "Giai đoạn" and bare[c]] == []


# --- /test-chat giống tin Messenger thật ---

TEST_USER = "test_user_funnel"
ASK_PHONE = "Dạ Ba/Mẹ cho em xin SĐT hoặc Zalo để tư vấn viên gửi chi tiết nhé ạ? [QUICK:phone]"


@pytest.fixture
def model(monkeypatch):
    """Model giả: ghi lại câu bot vừa hỏi mà bước trích xuất nhận được; `extracted` là kết quả trích xuất thô."""
    model = SimpleNamespace(extracted={}, last_bot_messages=[])

    async def get_response(**kwargs):
        return AIResponse(text="Dạ vâng ạ, em ghi nhận ạ.", should_escalate=False, model_used="fake-model")

    async def extract_customer_info(user_message, existing_profile=None, last_bot_message=""):
        model.last_bot_messages.append(last_bot_message)
        return dict(model.extracted)

    monkeypatch.setattr(main.ai_engine, "get_response", get_response)
    monkeypatch.setattr(main.ai_engine, "extract_customer_info", extract_customer_info)
    return model


def chat(text: str) -> dict:
    resp = client.post("/test-chat", params={"secret": WEBHOOK_SECRET}, json={"message": text, "user_id": TEST_USER})
    assert resp.status_code == 200
    return resp.json()["profile"]


def test_test_chat_gives_extraction_the_bot_message_just_sent(admin, model):
    customer_memory._customers[TEST_USER] = {
        "conversation_history": [
            {"role": "user", "content": "Trường có ưu đãi gì không ạ?"},
            {"role": "assistant", "content": ASK_PHONE},
        ]
    }

    chat("không ạ")

    assert model.last_bot_messages == [ASK_PHONE]


def test_test_chat_cleans_extraction_like_messenger(admin, model):
    model.extracted = {"phone": "không có", "phone_declined": "false", "kid_age": "3 tuổi"}

    profile = chat("Bé nhà mình 3 tuổi, mình chưa có số ạ")

    assert profile["kid_age"] == "3 tuổi"
    assert "phone" not in profile
    assert "phone_declined" not in profile

    model.extracted = {"phone_declined": True}

    assert chat("Mình chưa muốn để số ạ")["phone_declined"] is True


def test_test_chat_does_not_save_topics_in_the_profile(admin, model):
    model.extracted = {"topics": ["Học phí"], "kid_age": "3 tuổi"}

    profile = chat("Bé 3 tuổi học phí bao nhiêu ạ?")

    assert profile["kid_age"] == "3 tuổi"
    assert "topics" not in profile

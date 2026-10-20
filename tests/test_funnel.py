"""Số liệu cho người vận hành: phễu tư vấn tính từ hồ sơ khách (không mất khi deploy như analytics.jsonl),
và file Excel /customers/export."""

import io
import re

import openpyxl
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import analytics, customer_memory
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


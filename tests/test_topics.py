"""Chủ đề phụ huynh hỏi trong từng tin (app/topics.py): model trích xuất gắn, bot lọc theo danh sách cố định,
dashboard đếm (analytics.jsonl); câu hỏi lưu lại đã che SĐT."""

import json
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import analytics
from app.config import settings
from app.topics import TOPICS, clean_topics


@pytest.mark.parametrize(
    ("given", "escalated", "expected"),
    [
        (["Học phí"], False, ["Học phí"]),
        (["học phí", "  XE   ĐƯA  ĐÓN "], False, ["Học phí", "Xe đưa đón"]),
        (["Học thử / tham quan", "giờ học/ đón trả /trông muộn"], False, ["Học thử/tham quan", "Giờ học/đón trả/trông muộn"]),
        (["An toàn/sức khỏe/camera", "Giáo viên/tỉ lệ cô trò"], False, ["An toàn/sức khoẻ/camera", "Giáo viên/tỷ lệ cô trò"]),
        ([unicodedata.normalize("NFD", "Ưu đãi")], False, ["Ưu đãi"]),
        (["Học phí", "Giá vé máy bay", "học  phí", "Ăn uống/thực đơn"], False, ["Học phí", "Ăn uống/thực đơn"]),
        (["Ăn uống/thực đơn", "Học phí"], False, ["Ăn uống/thực đơn", "Học phí"]),
        ("Học phí", False, ["Học phí"]),
        ([42, None, {"topic": "Học phí"}], False, []),
        ([], False, []),
        (None, False, []),
        ([], True, ["Khác"]),
        (None, True, ["Khác"]),
        (["Giá vé máy bay"], True, ["Khác"]),
        (["Học phí"], True, ["Học phí"]),
    ],
    ids=[
        "một chủ đề",
        "hoa thường, khoảng trắng",
        "khoảng trắng quanh dấu /",
        "khỏe, tỉ lệ",
        "dấu tổ hợp (NFD)",
        "khoá lạ bị bỏ, không trùng",
        "giữ thứ tự của model",
        "chuỗi thay vì list",
        "phần tử không phải chuỗi",
        "list rỗng",
        "không có khoá topics",
        "chuyển tư vấn viên, rỗng",
        "chuyển tư vấn viên, không có khoá",
        "chuyển tư vấn viên, chỉ khoá lạ",
        "chuyển tư vấn viên, có chủ đề",
    ],
)
def test_clean_topics(given, escalated, expected):
    assert clean_topics(given, escalated=escalated) == expected


def test_every_topic_is_kept_as_written():
    assert len(TOPICS) == 15 and TOPICS[-1] == "Khác"
    assert clean_topics(list(TOPICS)) == list(TOPICS)


# --- Che SĐT trong câu hỏi lưu lại (dashboard, tab "Chủ đề") ---


@pytest.mark.parametrize(
    ("text", "masked"),
    [
        ("Số mình 0912345678 ạ", "Số mình [SĐT] ạ"),
        ("zalo 0912 345 678, gọi sau 5h", "zalo [SĐT], gọi sau 5h"),
        ("số em 0912.345.678", "số em [SĐT]"),
        ("+84 912 345 678 nhé", "[SĐT] nhé"),
        ("số 912345678", "số [SĐT]"),
        ("máy bàn 024 3123 4567", "máy bàn [SĐT]"),
        ("số (091) 234 5678", "số ([SĐT]"),
        ("+33 6 12 34 56 78 là số bên Pháp", "[SĐT] là số bên Pháp"),
        ("gọi +1 650 555 1234", "gọi [SĐT]"),
        ("0912345678 hoặc 0987654321", "[SĐT] hoặc [SĐT]"),
        ("Học phí 4.500.000đ/tháng cho bé 3 tuổi ở 185 Huỳnh Thúc Kháng, năm 2026?", None),
        ("Mã lớp 12-34, phòng 0203", None),
    ],
    ids=[
        "di động",
        "có dấu cách",
        "có dấu chấm",
        "+84",
        "thiếu số 0",
        "máy bàn",
        "ngoặc",
        "nước ngoài",
        "Mỹ",
        "hai số",
        "tiền, tuổi, số nhà, năm",
        "số ngắn",
    ],
)
def test_mask_phones(text, masked):
    assert main.mask_phones(text) == (masked or text)


# --- Dashboard: chủ đề 7 ngày, câu chuyển tư vấn viên gần đây ---


def write_records(*records):
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    Path(analytics.ANALYTICS_PATH).write_text("\n".join(lines) + "\n", encoding="utf-8")


def record(age: timedelta, topics=None, escalated=False, question="Câu hỏi"):
    r = {
        "timestamp": (datetime.now() - age).isoformat(),
        "user_id": "9000000000000701",
        "user_name": "Lan Thử",
        "question": question,
        "model_used": "fake-model",
        "escalated": escalated,
    }
    if topics is not None:
        r["topics"] = topics
    return r


def test_stats_count_topics_of_the_last_7_days_escalated_included():
    write_records(
        record(timedelta(hours=1), ["Học phí", "Ưu đãi"]),
        record(timedelta(days=2), ["Học phí"], escalated=True),
        record(timedelta(days=3), ["Khác"], escalated=True),
        record(timedelta(days=3, hours=1), []),
        record(timedelta(days=8), ["Xe đưa đón"]),
        {**record(timedelta(hours=2)), "category": "Học phí"},  # bản ghi trước khi có topics
    )

    stats = analytics.get_stats()

    assert stats["top_topics_7d"] == [
        {"topic": "Học phí", "count": 2},
        {"topic": "Ưu đãi", "count": 1},
        {"topic": "Khác", "count": 1},
    ]
    assert stats["total_messages"] == 6


def test_stats_list_the_10_latest_escalated_questions_newest_first():
    write_records(
        *[record(timedelta(hours=20 - i), ["Khác"], escalated=True, question=f"Câu khó {i}") for i in range(12)],
        record(timedelta(minutes=1), ["Học phí"], question="Câu bot tự trả lời"),
    )

    escalations = analytics.get_stats()["recent_escalations"]

    assert [e["question"] for e in escalations] == [f"Câu khó {i}" for i in range(11, 1, -1)]
    assert set(escalations[0]) == {"timestamp", "question", "topics"}
    assert escalations[0]["topics"] == ["Khác"]


def test_stats_without_analytics_have_no_topics_and_no_escalations():
    stats = analytics.get_stats()

    assert (stats["top_topics_7d"], stats["recent_escalations"]) == ([], [])


def test_dashboard_shows_topics_and_escalated_questions_and_where_full_figures_are(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "tg-secret_topics")

    html = TestClient(main.app).get("/dashboard", params={"secret": "tg-secret_topics"}).text

    for key in ("stats.top_topics_7d", "stats.recent_escalations", "m.topics"):
        assert key in html, key
    assert "top_categories" not in html
    assert "tính từ lần khởi động gần nhất" in html and "Google Sheet" in html


def test_dashboard_escapes_every_parent_supplied_field():
    # Tên Facebook do phụ huynh tự đặt: chèn thẳng vào innerHTML là XSS trên trình duyệt người xem dashboard.
    html = (Path(__file__).resolve().parent.parent / "app" / "dashboard.html").read_text(encoding="utf-8")
    assert "${m.user_name" not in html
    assert "escapeHtml(m.user_name" in html


@pytest.mark.parametrize(
    "text",
    [
        "số em 0912345678 125 Trung Kính",
        "sđt 0912345678 - 2019",
        "0912,345,678",
        "0912/345/678",
        "0912–345–678",
        "0084 912 345 678",
        "+84 912 345 678",
    ],
)
def test_mask_phones_masks_the_parents_known_number_however_written(text):
    masked = main.mask_phones(text, ("0912345678",))
    assert "[SĐT]" in masked
    assert "912" not in masked.replace("[SĐT]", "")


def test_mask_phones_keeps_money_and_ages_with_a_known_number():
    assert main.mask_phones("học phí 4.500.000, bé 3 tuổi", ("0912345678",)) == "học phí 4.500.000, bé 3 tuổi"


def test_extract_prompt_does_not_ask_for_an_empty_object_when_only_topics_are_present():
    import inspect

    from app import ai_engine

    source = inspect.getsource(ai_engine)
    assert "không có thông tin hồ sơ mới và không có chủ đề nào thì trả về {}" in source

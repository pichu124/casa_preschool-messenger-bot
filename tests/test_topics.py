"""Chủ đề phụ huynh hỏi trong từng tin (app/topics.py): model trích xuất gắn, bot lọc theo danh sách cố định."""

import unicodedata

import pytest

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

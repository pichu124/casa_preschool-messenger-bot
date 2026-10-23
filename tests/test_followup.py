"""Tin nhắc lại phụ huynh còn dở cuộc tư vấn, trong cửa sổ 24 giờ của Messenger (mặc định TẮT).

due_followups là hàm thuần: bảng ca biên dưới đây gọi thẳng với giờ cố định. run_followups và /followup/run
dùng Messenger giả (patch trên app.followup) và giờ cố định (followup._now_utc). Workflow GitHub Actions được
đọc từ YAML, bước curl chạy thật bằng bash với curl giả.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import app.main as main
from app import customer_memory, followup
from app.config import settings
from app.coverage import TOPICS
from app.escalation import (
    ESCALATION_MESSAGE_ASK_PHONE,
    ESCALATION_MESSAGE_HAS_PHONE,
    ESCALATION_MESSAGE_PHONE_DECLINED,
    ESCALATION_MESSAGE_UPSET,
)

client = TestClient(main.app)

VN = timezone(timedelta(hours=7))
H = timedelta(hours=1)
M = timedelta(minutes=1)
NOW = datetime(2026, 10, 20, 10, 0, tzinfo=VN).astimezone(timezone.utc)
CID = "9000000000000201"
PAGE_ID = "9000000000000200"
WEBHOOK_SECRET = "tg-secret_followup"
FB_NAME = "Lan Thử"
KID_NAME = "Bin"
PHONE = "0900000201"
PARENT_TEXT = "Trường mình có cơ sở nào gần Cầu Giấy không ạ?"
BOT_TEXT = "Dạ Casa có cơ sở Chùa Láng, Mỹ Đình và Kim Mã ạ. Bé nhà mình năm nay mấy tuổi ạ?"
# Đủ 6 điều kiện "đã tư vấn tương đối đủ" của trường (phản hồi đợt 4)
CONSULTED = {"kid_age": "3 tuổi", "interested_campus": "Mỹ Đình", "topics_covered": list(TOPICS)}


def server_time(dt: datetime) -> str:
    """Timestamp như append_to_history ghi trên Render: datetime.now() của máy chủ UTC, không có múi giờ."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def vn(hour: int, minute: int = 0, second: int = 0, day: int = 20) -> datetime:
    return datetime(2026, 10, day, hour, minute, second, tzinfo=VN).astimezone(timezone.utc)


def profile(silence=22 * H, now=NOW, last="assistant", bot_text=BOT_TEXT, **fields) -> dict:
    """Hồ sơ có tin cuối của phụ huynh cách `now` một khoảng `silence`; tin cuối của history là của `last`."""
    parent_at = now - silence
    parent = {"role": "user", "content": PARENT_TEXT, "timestamp": server_time(parent_at)}
    if last == "assistant":
        bot_at = parent_at + timedelta(seconds=5)
        history = [parent, {"role": "assistant", "content": bot_text, "timestamp": server_time(bot_at)}]
    else:
        history = [{"role": "assistant", "content": bot_text, "timestamp": server_time(parent_at - H)}, parent]
    return {"parent_name": FB_NAME, "message_count": 2, "conversation_history": history, **fields}


# Giờ VN, phụ huynh nhắn lần cuối ngày 20. deadline = tin cuối + 23h; slot [deadline − 2h, deadline] không nằm
# trọn trong 8:00–20:59:59 thì lùi về 20:59:59 gần nhất trước deadline (latest_send). Gửi trong
# [latest_send − 2h, latest_send].
WINDOW_CASES = [
    # 10:00 → deadline 09:00 ngày 21 (slot 07:00–09:00 lẹm trước 8:00) → 20:59:59 ngày 20, 10h59 sau tin cuối
    ("10:00, 3h sau", vn(10), vn(13), False),
    ("10:00, ngày 20 18:59:58, trước slot", vn(10), vn(18, 59, 58), False),
    ("10:00, ngày 20 18:59:59, latest_send − 2h", vn(10), vn(18, 59, 59), True),
    ("10:00, ngày 20 20:59:59, đúng latest_send", vn(10), vn(20, 59, 59), True),
    ("10:00, ngày 20 21:00:59, quá 1 phút", vn(10), vn(21, 0, 59), False),
    ("10:00, ngày 21 08:00 (quy tắc cũ có gửi)", vn(10), vn(8, day=21), False),
    ("10:00, ngày 21 09:00, deadline (quy tắc cũ có gửi)", vn(10), vn(9, day=21), False),
    # 23:00 → deadline 22:00 ngày 21 (ngoài khung) → 20:59:59 ngày 21: slot 18:59:59–20:59:59
    ("23:00, ngày 21 10:00 (quy tắc cũ có gửi)", vn(23), vn(10, day=21), False),
    ("23:00, ngày 21 18:59:58, trước slot", vn(23), vn(18, 59, 58, day=21), False),
    ("23:00, ngày 21 18:59:59, latest_send − 2h", vn(23), vn(18, 59, 59, day=21), True),
    ("23:00, ngày 21 20:59:59, đúng latest_send", vn(23), vn(20, 59, 59, day=21), True),
    ("23:00, ngày 21 21:00:59, quá 1 phút", vn(23), vn(21, 0, 59, day=21), False),
    # 03:00 → deadline 02:00 ngày 21 → 20:59:59 ngày 20 (17h59 sau tin cuối): slot 18:59:59–20:59:59 ngày 20
    ("03:00, ngày 20 10:00 (quy tắc cũ có gửi)", vn(3), vn(10), False),
    ("03:00, ngày 20 18:59:58, trước slot", vn(3), vn(18, 59, 58), False),
    ("03:00, ngày 20 18:59:59, latest_send − 2h", vn(3), vn(18, 59, 59), True),
    ("03:00, ngày 20 20:59:59, đúng latest_send", vn(3), vn(20, 59, 59), True),
    ("03:00, ngày 20 21:00:59, quá 1 phút", vn(3), vn(21, 0, 59), False),
    ("03:00, ngày 21 08:00, quá 24h", vn(3), vn(8, day=21), False),
    # 22:30 → deadline 21:30 ngày 21 → 20:59:59 ngày 21
    ("22:30, ngày 21 18:59:58, trước slot", vn(22, 30), vn(18, 59, 58, day=21), False),
    ("22:30, ngày 21 18:59:59, latest_send − 2h", vn(22, 30), vn(18, 59, 59, day=21), True),
    ("22:30, ngày 21 20:59:59, đúng latest_send", vn(22, 30), vn(20, 59, 59, day=21), True),
    ("22:30, ngày 21 21:00:59, quá 1 phút", vn(22, 30), vn(21, 0, 59, day=21), False),
    # 20:50 → deadline 19:50 ngày 21 (trong khung): slot 17:50–19:50
    ("20:50, ngày 21 12:00 (quy tắc cũ có gửi)", vn(20, 50), vn(12, day=21), False),
    ("20:50, ngày 21 17:49:59, trước slot", vn(20, 50), vn(17, 49, 59, day=21), False),
    ("20:50, ngày 21 17:50, latest_send − 2h", vn(20, 50), vn(17, 50, day=21), True),
    ("20:50, ngày 21 19:50, đúng latest_send", vn(20, 50), vn(19, 50, day=21), True),
    ("20:50, ngày 21 19:51, quá 1 phút", vn(20, 50), vn(19, 51, day=21), False),
    # Biên của khung gửi tại deadline
    ("21:59:59 → deadline 20:59:59 trong khung, đúng deadline", vn(21, 59, 59), vn(20, 59, 59, day=21), True),
    ("22:00 → deadline 21:00 ngoài khung, 20:59:59", vn(22), vn(20, 59, 59, day=21), True),
    ("08:59 → deadline 07:59 → 20:59:59 cùng ngày tin cuối", vn(8, 59), vn(20), True),
    ("08:59 → deadline 07:59, ngày 21 07:30 không gửi", vn(8, 59), vn(7, 30, day=21), False),
    ("09:00 → deadline 08:00 → 20:59:59 cùng ngày tin cuối", vn(9), vn(20, 59, 59), True),
    ("09:00 → deadline 08:00, ngày 21 08:00 không gửi (quy tắc cũ có gửi)", vn(9), vn(8, day=21), False),
    ("10:59:59 → deadline 09:59:59 → 20:59:59 cùng ngày tin cuối", vn(10, 59, 59), vn(20, 59, 59), True),
    ("10:59:59 → deadline 09:59:59, ngày 21 09:17 không gửi (quy tắc cũ có gửi)", vn(10, 59, 59), vn(9, 17, day=21), False),
    ("11:00 → deadline 10:00, slot 08:00–10:00 trọn trong khung, đầu slot", vn(11), vn(8, day=21), True),
    ("11:00 → deadline 10:00, đúng deadline", vn(11), vn(10, day=21), True),
    ("11:00 → deadline 10:00, trước slot 1 giây", vn(11), vn(7, 59, 59, day=21), False),
    ("11:00 → deadline 10:00, ngày 20 20:59:59 không gửi", vn(11), vn(20, 59, 59), False),
]


@pytest.mark.parametrize(
    ("parent_at", "now", "due"), [c[1:] for c in WINDOW_CASES], ids=[c[0] for c in WINDOW_CASES]
)
def test_followup_goes_out_just_before_the_24_hour_window_closes(parent_at, now, due):
    customer = profile(silence=now - parent_at, now=now)
    expected = [(CID, "ask_age")] if due else []

    assert followup.due_followups({CID: customer}, now) == expected


def test_never_due_outside_sending_hours_or_after_23_hours():
    """Mọi cặp (tin cuối, lần chạy) theo bước 15 phút trong hai ngày: chỉ gửi trong 8:00–20:59, 3h–23h sau tin cuối."""
    step = 15 * M
    sent = 0
    for p in range(96):
        parent_at = vn(0) + p * step
        for n in range(1, 30 * 4 + 1):
            now = parent_at + n * step
            if followup.due_followups({CID: profile(silence=now - parent_at, now=now)}, now):
                sent += 1
                assert 3 * H <= now - parent_at <= 23 * H
                assert 8 <= now.astimezone(VN).hour <= 20
    assert sent > 0


def cron_minutes() -> list[int]:
    """Phút trong giờ của các lịch `M * * * *` trong workflow."""
    _, triggers = load_workflow()
    return sorted(int(entry["cron"].split()[0]) for entry in triggers["schedule"])


def cron_runs(parent_at: datetime) -> list[datetime]:
    """Các lần chạy của workflow (các phút cron_minutes, mỗi giờ) trong 24 giờ sau tin cuối mà phụ huynh đến hạn."""
    hour = parent_at.replace(minute=0, second=0, microsecond=0)
    runs = [hour + h * H + m * M for h in range(25) for m in cron_minutes()]
    runs = [now for now in runs if parent_at < now <= parent_at + 24 * H]
    return [now for now in runs if followup.due_followups({CID: profile(silence=now - parent_at, now=now)}, now)]


# Tin cuối mà quy tắc cũ (deadline trong 8:00–20:59 là đủ) bỏ sót hoặc chỉ cho 1 lần chạy, hoặc cho slot lẹm
# trước 8:00. (tin cuối, latest_send mong đợi, các lần chạy phút 17 và 47 trong slot)
EVENING_RUNS = [vn(19, 17), vn(19, 47), vn(20, 17), vn(20, 47)]
MORNING_CASES = [
    ("09:00", vn(9), vn(20, 59, 59), EVENING_RUNS),
    ("09:10", vn(9, 10), vn(20, 59, 59), EVENING_RUNS),
    ("09:16", vn(9, 16), vn(20, 59, 59), EVENING_RUNS),
    ("09:30", vn(9, 30), vn(20, 59, 59), EVENING_RUNS),
    ("10:00", vn(10), vn(20, 59, 59), EVENING_RUNS),
    ("10:59", vn(10, 59), vn(20, 59, 59), EVENING_RUNS),
    ("11:00", vn(11), vn(10, day=21), [vn(8, 17, day=21), vn(8, 47, day=21), vn(9, 17, day=21), vn(9, 47, day=21)]),
]


def is_due(parent_at: datetime, now: datetime) -> bool:
    return followup.due_followups({CID: profile(silence=now - parent_at, now=now)}, now) != []


@pytest.mark.parametrize(
    ("parent_at", "latest_send", "runs"), [c[1:] for c in MORNING_CASES], ids=[c[0] for c in MORNING_CASES]
)
def test_morning_last_message_gets_its_runs_in_a_slot_within_sending_hours(parent_at, latest_send, runs):
    assert cron_runs(parent_at) == runs
    slot_start = latest_send - followup.SEND_SLOT
    assert 8 <= slot_start.astimezone(VN).hour and latest_send.astimezone(VN).hour <= 20
    assert slot_start.astimezone(VN).date() == latest_send.astimezone(VN).date()
    assert is_due(parent_at, slot_start) and is_due(parent_at, latest_send)
    assert not is_due(parent_at, slot_start - timedelta(seconds=1))
    assert not is_due(parent_at, latest_send + timedelta(seconds=1))


def test_every_last_message_gets_three_runs_the_first_an_hour_before_latest_send():
    """Mọi tin cuối theo bước 1 phút trong 24 giờ: ít nhất 3 lần chạy (phút 17 và 47) đến hạn, cách tin cuối
    3h–23h, lần đầu còn ít nhất 60 phút trước latest_send (GitHub Actions hay trễ hoặc bỏ lượt)."""
    for minute in range(24 * 60):
        parent_at = vn(0) + minute * M
        label = parent_at.astimezone(VN).strftime("%H:%M")
        latest_send = followup._latest_send(parent_at)
        assert is_due(parent_at, latest_send) and not is_due(parent_at, latest_send + timedelta(seconds=1)), label
        runs = cron_runs(parent_at)
        assert len(runs) >= 3, label
        assert latest_send - runs[0] >= 60 * M, label
        for now in runs:
            assert 3 * H <= now - parent_at <= 23 * H
            assert 8 <= now.astimezone(VN).hour <= 20


def test_slot_too_close_to_the_last_message_is_not_due(monkeypatch):
    """latest_send − tin cuối < 3h không xảy ra với lề 1h; nếu lề đổi thì MIN_SILENCE vẫn chặn."""
    monkeypatch.setattr(followup, "WINDOW_MARGIN", 22 * H)
    parent_at = vn(10)  # deadline 12:00, slot 10:00–12:00

    for now in (vn(11), vn(12), vn(12, 59)):
        assert followup.due_followups({CID: profile(silence=now - parent_at, now=now)}, now) == []


DUE_CASES = [
    ("đã nhắc sau tin cuối", profile(followup_sent_at=(NOW - 4 * H).isoformat()), NOW, None),
    ("nhắc đúng lúc tin cuối", profile(followup_sent_at=(NOW - 22 * H).isoformat()), NOW, None),
    ("nhắc trước tin cuối mới hơn", profile(followup_sent_at=(NOW - 30 * H).isoformat()), NOW, "ask_age"),
    ("nhân viên nhắn tay sau tin cuối", profile(staff_replied_at=(NOW - 4 * H).isoformat()), NOW, None),
    ("nhân viên nhắn tay trước tin cuối", profile(staff_replied_at=(NOW - 30 * H).isoformat()), NOW, "ask_age"),
    ("staff_replied_at không đọc được", profile(staff_replied_at="không phải ngày"), NOW, None),
    ("tin cuối: chuyển tư vấn viên, xin SĐT", profile(bot_text=ESCALATION_MESSAGE_ASK_PHONE), NOW, None),
    ("tin cuối: chuyển tư vấn viên, có SĐT", profile(bot_text=ESCALATION_MESSAGE_HAS_PHONE), NOW, None),
    ("tin cuối: chuyển tư vấn viên, từ chối SĐT", profile(bot_text=ESCALATION_MESSAGE_PHONE_DECLINED), NOW, None),
    ("tin cuối: xin lỗi, chuyển tư vấn viên", profile(bot_text=ESCALATION_MESSAGE_UPSET), NOW, None),
    ("tin cuối là của phụ huynh", profile(last="user"), NOW, None),
    ("có phone", profile(kid_age="3 tuổi", phone=PHONE), NOW, None),
    ("có visit_request", profile(kid_age="3 tuổi", visit_request="tham quan sáng thứ 7"), NOW, None),
    ("chưa biết tuổi bé", profile(interested_campus="Mỹ Đình"), NOW, "ask_age"),
    ("biết tuổi, chưa có SĐT", profile(kid_age="3 tuổi"), NOW, "ask_phone"),
    ("phone_declined", profile(kid_age="3 tuổi", phone_declined=True), NOW, "ask_phone"),
    ("phone_declined, chưa biết tuổi", profile(phone_declined=True), NOW, "ask_age"),
    ("tư vấn đủ, chưa có SĐT", profile(**CONSULTED), NOW, "invite_visit"),
    ("tư vấn đủ, từ chối SĐT", profile(**CONSULTED, phone_declined=True), NOW, "invite_visit"),
    ("tư vấn đủ, có phone", profile(**CONSULTED, phone=PHONE), NOW, None),
    ("thiếu một nhóm", profile(**{**CONSULTED, "topics_covered": list(TOPICS[:-1])}), NOW, "ask_phone"),
    ("đủ nhóm, thiếu cơ sở", profile(kid_age="3 tuổi", topics_covered=list(TOPICS)), NOW, "ask_phone"),
    (
        "có tuổi, từ chối SĐT, chưa tư vấn đủ",
        profile(kid_age="3 tuổi", interested_campus="Mỹ Đình", topics_covered=["program"], phone_declined=True),
        NOW,
        "ask_phone",
    ),
    ("chỉ có referral, không history", {"lead_source": "ads", "ad_title": "Học thử 1 tuần"}, NOW, None),
]


def earlier(customer: dict, *messages: tuple[str, str, timedelta | None]) -> dict:
    """`customer` có thêm các tin (role, nội dung, cách tin cuối của phụ huynh bao lâu; None: giờ không đọc được)
    trước history của nó."""
    history = customer["conversation_history"]
    parent_at = datetime.fromisoformat(history[0]["timestamp"])
    before = [
        {"role": role, "content": content, "timestamp": (parent_at - ago).isoformat() if ago else "không phải ngày"}
        for role, content, ago in messages
    ]
    return {**customer, "conversation_history": before + history}


UPSET_TEXT = "sao cứ đòi số thế"
KID = {"kid_age": "3 tuổi"}
# Phụ huynh bực vì bị đòi số, bot xin lỗi và chuyển tư vấn viên, phụ huynh nhắn tiếp ("ừ nhanh nhé"), model trả lời
# thường rồi phụ huynh im: tin cuối của bot không còn là câu xin lỗi, nhưng không được nhắc (xin SĐT) người vừa bực.
UPSET_CASES = [
    (
        "xin lỗi rồi phụ huynh nhắn tiếp",
        earlier(profile(**KID), ("user", UPSET_TEXT, 3 * M), ("assistant", ESCALATION_MESSAGE_UPSET, 2 * M)),
        None,
    ),
    (
        "xin lỗi 23 giờ trước tin cuối",
        earlier(profile(**KID), ("user", UPSET_TEXT, 23 * H), ("assistant", ESCALATION_MESSAGE_UPSET, 23 * H)),
        None,
    ),
    (
        "xin lỗi hơn 24 giờ trước tin cuối: cuộc trò chuyện khác",
        earlier(profile(**KID), ("user", UPSET_TEXT, 25 * H), ("assistant", ESCALATION_MESSAGE_UPSET, 25 * H)),
        "ask_phone",
    ),
    ("câu xin lỗi không đọc được giờ", earlier(profile(**KID), ("assistant", ESCALATION_MESSAGE_UPSET, None)), None),
    (
        "chuyển tư vấn viên thường rồi nhắn tiếp: vẫn nhắc",
        earlier(profile(**KID), ("assistant", ESCALATION_MESSAGE_ASK_PHONE, 2 * M)),
        "ask_phone",
    ),
]


# Câu chuyển tư vấn viên trước 9694fb8 (chưa có hotline), nguyên văn: phụ huynh được chuyển trước khi deploy bản mới
# vẫn có câu này là tin cuối của bot.
OLD_HANDOVERS = {
    "có SĐT": (
        "Dạ, em cảm ơn Ba/Mẹ đã nhắn cho Casa ạ! Câu hỏi của Ba/Mẹ em đã chuyển đến bộ phận tư vấn, "
        "tư vấn viên sẽ liên hệ và trả lời Ba/Mẹ trong thời gian sớm nhất ạ."
    ),
    "xin SĐT": (
        "Dạ, em cảm ơn Ba/Mẹ đã nhắn cho Casa ạ! Câu hỏi của Ba/Mẹ em đã chuyển đến bộ phận tư vấn, bộ phận sẽ phản "
        "hồi Ba/Mẹ sớm nhất ạ. Nếu tiện, Ba/Mẹ để lại SĐT hoặc Zalo để tư vấn viên hỗ trợ Ba/Mẹ nhanh hơn nhé ạ."
    ),
    "từ chối SĐT": (
        "Dạ, em cảm ơn Ba/Mẹ đã nhắn cho Casa ạ! Câu hỏi của Ba/Mẹ em đã chuyển đến bộ phận tư vấn, "
        "nhân viên tư vấn sẽ trả lời Ba/Mẹ trực tiếp tại đây sớm nhất ạ."
    ),
}


@pytest.mark.parametrize("text", OLD_HANDOVERS.values(), ids=OLD_HANDOVERS.keys())
def test_parent_handed_over_before_the_hotline_wording_gets_no_followup(text):
    assert followup.due_followups({CID: profile(kid_age="3 tuổi", bot_text=text)}, NOW) == []


@pytest.mark.parametrize(("customer", "template_key"), [c[1:] for c in UPSET_CASES], ids=[c[0] for c in UPSET_CASES])
def test_parent_upset_in_this_conversation_gets_no_followup(customer, template_key):
    expected = [(CID, template_key)] if template_key else []

    assert followup.due_followups({CID: customer}, NOW) == expected


@pytest.mark.parametrize(("customer", "now", "template_key"), [c[1:] for c in DUE_CASES], ids=[c[0] for c in DUE_CASES])
def test_due_followups_edge_cases(customer, now, template_key):
    expected = [(CID, template_key)] if template_key else []

    assert followup.due_followups({CID: customer}, now) == expected


def test_history_timestamp_without_timezone_is_read_as_utc():
    """22h trước theo UTC (trong slot); đọc nhầm là giờ VN thì thành 29h trước, quá 24h, không được nhắc."""
    customer = profile()
    assert "+" not in customer["conversation_history"][0]["timestamp"]

    assert followup.due_followups({CID: customer}, NOW) == [(CID, "ask_age")]


def test_unreadable_timestamp_is_not_due_and_does_not_break_others():
    broken = profile()
    broken["conversation_history"][0]["timestamp"] = "không phải ngày"
    del broken["conversation_history"][1]["timestamp"]
    other = "9000000000000202"

    assert followup.due_followups({CID: broken, other: profile()}, NOW) == [(other, "ask_age")]


# Nguyên văn 3 mẫu nhắc lại của trường (phản hồi đợt 5).
SCHOOL_TEMPLATES = {
    # 1. Chưa biết tuổi bé
    "ask_age": (
        "Dạ em chào Ba/Mẹ ạ. Em xin phép nhắn lại để tiếp tục hỗ trợ Ba/Mẹ tìm hiểu về Casa. Ba/Mẹ cho em xin "
        "độ tuổi hiện tại của bé, để em có thể gửi đúng thông tin về chương trình và lớp học phù hợp với con ạ. "
        "Nếu Ba/Mẹ cần thêm thông tin nào khác, em cũng luôn sẵn sàng hỗ trợ."
    ),
    # 2. Đã biết tuổi bé, chưa có SĐT
    "ask_phone": (
        "Dạ em chào Ba/Mẹ ạ. Không biết Ba/Mẹ còn cần em hỗ trợ thêm thông tin nào về chương trình, học phí hay "
        "lớp phù hợp với bé không ạ? Nếu thuận tiện, Ba/Mẹ có thể để lại SĐT/Zalo để Casa tư vấn kỹ hơn cho mình nhé."
    ),
    # 3. Đã tư vấn tương đối đủ nhưng phụ huynh dừng trao đổi
    "invite_visit": (
        "Dạ em chào Ba/Mẹ ạ. Không biết Ba/Mẹ còn điều gì đang băn khoăn hay cần em tư vấn thêm không ạ? Nếu cần, "
        "Casa có thể hỗ trợ Ba/Mẹ tìm hiểu kỹ hơn về chương trình học hoặc sắp xếp một buổi tham quan để gia đình "
        "trực tiếp cảm nhận môi trường học của con."
    ),
}


def test_templates_are_the_school_wording():
    assert followup.TEMPLATES == SCHOOL_TEMPLATES


# Nhãn của trường quyết định mẫu, kể cả khi phụ huynh đã từ chối để lại SĐT.
SCHOOL_LABELS = [
    ("tư vấn đủ, từ chối SĐT: mẫu 3", {**CONSULTED, "phone_declined": True}, "invite_visit"),
    ("chưa biết tuổi, từ chối SĐT: mẫu 1", {"interested_campus": "Mỹ Đình", "phone_declined": True}, "ask_age"),
    (
        "có tuổi, từ chối SĐT, chưa tư vấn đủ: mẫu 2",
        {"kid_age": "3 tuổi", "interested_campus": "Mỹ Đình", "topics_covered": ["program"], "phone_declined": True},
        "ask_phone",
    ),
]


@pytest.mark.parametrize(("fields", "school_key"), [c[1:] for c in SCHOOL_LABELS], ids=[c[0] for c in SCHOOL_LABELS])
def test_followup_text_follows_the_school_labels(fields, school_key):
    [(_, key)] = followup.due_followups({CID: profile(**fields)}, NOW)

    assert followup.TEMPLATES[key] == SCHOOL_TEMPLATES[school_key]


# --- run_followups ---


class Outbox:
    """Messenger giả: ghi tin gửi đi; khách trong `failing` bị Graph từ chối (ngoài cửa sổ, đã chặn trang)."""

    def __init__(self):
        self.sent = []
        self.failing = set()

    async def send_message(self, recipient_id, text, quick_replies=None):
        await asyncio.sleep(0)
        if recipient_id in self.failing:
            raise Exception("Messenger API error: 400")
        self.sent.append((recipient_id, text))


@pytest.fixture
def outbox(monkeypatch):
    box = Outbox()
    monkeypatch.setattr(followup, "send_message", box.send_message)
    monkeypatch.setattr(followup, "_now_utc", lambda: NOW)
    return box


@pytest.fixture
def synced(monkeypatch):
    calls = []

    async def sync_to_github():
        calls.append(1)
        return True

    monkeypatch.setattr(customer_memory, "sync_to_github", sync_to_github)
    return calls


ASK_AGE_ID, INVITE_ID, HAS_PHONE_ID = "9000000000000211", "9000000000000212", "9000000000000213"


def seed_customers():
    customer_memory._customers.update(
        {
            ASK_AGE_ID: profile(kid_name=KID_NAME),
            INVITE_ID: profile(**CONSULTED, phone_declined=True),
            HAS_PHONE_ID: profile(kid_age="4 tuổi", phone=PHONE),
        }
    )


def test_disabled_sends_nothing_and_only_counts(outbox):
    """conftest đặt FOLLOWUP_ENABLED=False và cấm sync_to_github."""
    seed_customers()
    before = json.loads(json.dumps(customer_memory._customers))

    result = asyncio.run(followup.run_followups(dry_run=False))

    assert (result["due"], result["sent"], result["enabled"]) == (2, 0, False)
    assert outbox.sent == []
    assert customer_memory._customers == before


def test_conftest_keeps_followup_disabled():
    assert settings.FOLLOWUP_ENABLED is False


def test_enabled_sends_once_to_due_customers_and_records_it(monkeypatch, outbox, synced):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()

    result = asyncio.run(followup.run_followups(dry_run=False))

    assert (result["due"], result["sent"], result["enabled"]) == (2, 2, True)
    assert outbox.sent == [
        (ASK_AGE_ID, followup.TEMPLATES["ask_age"]),
        (INVITE_ID, followup.TEMPLATES["invite_visit"]),
    ]
    for customer_id, text in outbox.sent:
        saved = customer_memory.get_profile(customer_id)
        assert saved["followup_sent_at"] == NOW.isoformat()
        assert saved["message_count"] == 2
        assert "last_seen" not in saved
        assert saved["conversation_history"][-1]["role"] == "assistant"
        assert saved["conversation_history"][-1]["content"] == text
        assert len(saved["conversation_history"]) == 3
    assert "followup_sent_at" not in customer_memory.get_profile(HAS_PHONE_ID)
    assert synced == [1]

    again = asyncio.run(followup.run_followups(dry_run=False))

    assert (again["due"], again["sent"]) == (0, 0)
    assert len(outbox.sent) == 2
    assert synced == [1]


def test_followup_to_a_consulted_parent_leaves_topics_covered_as_is(monkeypatch, outbox, synced):
    """Tin nhắc lại không qua bộ dò nhóm thông tin, dù mẫu 3 có lời mời tham quan."""
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    partial = ["program", "menu"]
    consulted_id, partial_id = "9000000000000214", "9000000000000215"
    customer_memory._customers.update(
        {
            consulted_id: profile(**CONSULTED),
            partial_id: profile(kid_age="3 tuổi", phone_declined=True, topics_covered=partial),
        }
    )

    result = asyncio.run(followup.run_followups(dry_run=False))

    assert result["sent"] == 2
    assert outbox.sent == [
        (consulted_id, followup.TEMPLATES["invite_visit"]),
        (partial_id, followup.TEMPLATES["ask_phone"]),
    ]
    assert customer_memory.get_profile(consulted_id)["topics_covered"] == list(TOPICS)
    assert customer_memory.get_profile(partial_id)["topics_covered"] == partial


def test_send_error_skips_that_customer_only(monkeypatch, outbox, synced, caplog):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()
    outbox.failing.add(ASK_AGE_ID)

    with caplog.at_level(logging.WARNING, logger=followup.logger.name):
        result = asyncio.run(followup.run_followups(dry_run=False))

    assert (result["due"], result["sent"]) == (2, 1)
    assert outbox.sent == [(INVITE_ID, followup.TEMPLATES["invite_visit"])]
    failed = customer_memory.get_profile(ASK_AGE_ID)
    assert "followup_sent_at" not in failed and len(failed["conversation_history"]) == 2
    assert customer_memory.get_profile(INVITE_ID)["followup_sent_at"] == NOW.isoformat()
    assert synced == [1]
    assert [r for r in caplog.records if ASK_AGE_ID[-4:] in r.getMessage()], "không log khách gửi lỗi"


def test_dry_run_sends_nothing_even_when_enabled(monkeypatch, outbox):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()

    result = asyncio.run(followup.run_followups(dry_run=True))

    assert (result["due"], result["sent"], result["enabled"]) == (2, 0, True)
    assert outbox.sent == []
    assert "followup_sent_at" not in customer_memory.get_profile(ASK_AGE_ID)


def test_overlapping_runs_do_not_send_twice(monkeypatch, outbox, synced):
    """curl --retry gửi lại khi lần đầu quá giờ mà máy chủ vẫn đang gửi: hai lần chạy chồng nhau."""
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()

    async def two_runs():
        return await asyncio.gather(followup.run_followups(dry_run=False), followup.run_followups(dry_run=False))

    first, second = asyncio.run(two_runs())

    assert sorted(recipient for recipient, _ in outbox.sent) == [ASK_AGE_ID, INVITE_ID]
    assert first["sent"] + second["sent"] == 2
    assert synced == [1]


@pytest.mark.parametrize("pushed", [True, False], ids=["đẩy được", "không đẩy được"])
def test_unpushed_followup_marks_log_a_warning_without_personal_data(monkeypatch, outbox, caplog, pushed):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()

    async def sync_to_github():
        return pushed

    monkeypatch.setattr(customer_memory, "sync_to_github", sync_to_github)

    with caplog.at_level(logging.DEBUG):
        result = asyncio.run(followup.run_followups(dry_run=False))

    assert result["sent"] == 2
    warnings = [r.getMessage() for r in caplog.records if r.name == followup.logger.name and r.levelno == logging.WARNING]
    assert len(warnings) == int(not pushed)
    assert all("followup_sent_at" in m for m in warnings)
    private = (FB_NAME, KID_NAME, PHONE, PARENT_TEXT, BOT_TEXT, ASK_AGE_ID, INVITE_ID, *followup.TEMPLATES.values())
    assert [m for m in (r.getMessage() for r in caplog.records) if any(p in m for p in private)] == []


def staff_echo(customer_id: str, at: datetime) -> dict:
    """Webhook Facebook gửi khi nhân viên nhắn tay cho phụ huynh trong hộp thư Page (không có metadata của bot)."""
    event = {
        "sender": {"id": PAGE_ID},
        "recipient": {"id": customer_id},
        "timestamp": int(at.timestamp() * 1000),
        "message": {"is_echo": True, "app_id": 263902037430900, "mid": "m_echo", "text": "Dạ chị gọi cho mình nhé"},
    }
    return {"object": "page", "entry": [{"id": PAGE_ID, "messaging": [event]}]}


@pytest.mark.parametrize(
    ("staff_at", "sent_to"),
    [(NOW - 21 * H, [INVITE_ID]), (NOW - 23 * H, [ASK_AGE_ID, INVITE_ID])],
    ids=["sau tin cuối của phụ huynh", "trước tin cuối của phụ huynh"],
)
def test_staff_reply_in_page_inbox_after_parent_last_message_stops_the_followup(
    monkeypatch, outbox, synced, staff_at, sent_to
):
    """Tin cuối của phụ huynh (seed_customers) cách NOW 22 giờ."""
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    monkeypatch.setattr(settings, "FB_APP_SECRET", "")
    seed_customers()

    assert client.post("/webhook", json=staff_echo(ASK_AGE_ID, staff_at)).status_code == 200
    result = asyncio.run(followup.run_followups(dry_run=False))

    assert [recipient for recipient, _ in outbox.sent] == sent_to
    assert result["sent"] == len(sent_to)
    assert customer_memory.get_profile(ASK_AGE_ID)["staff_replied_at"] == staff_at.isoformat()
    assert synced == [1, 1]


def test_no_due_customer_does_not_sync(monkeypatch, outbox):
    """conftest cấm sync_to_github: không có gì thay đổi thì không đẩy customers.json."""
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    customer_memory._customers[HAS_PHONE_ID] = profile(phone=PHONE)

    result = asyncio.run(followup.run_followups(dry_run=False))

    assert (result["due"], result["sent"]) == (0, 0)


# --- /followup/run ---


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)


def run_endpoint(**params):
    return client.post("/followup/run", params={"secret": WEBHOOK_SECRET, **params})


def test_endpoint_without_secret_is_forbidden(admin, outbox):
    seed_customers()

    assert client.post("/followup/run").status_code == 403
    assert client.post("/followup/run", params={"secret": "sai"}).status_code == 403
    assert outbox.sent == []


def test_endpoint_returns_counts_only(monkeypatch, admin, outbox, synced):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()

    resp = run_endpoint()

    assert resp.status_code == 200
    assert resp.json() == {"due": 2, "sent": 2, "enabled": True}


def test_endpoint_dry_run_sends_nothing(monkeypatch, admin, outbox):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()

    resp = run_endpoint(dry_run=1)

    assert resp.json() == {"due": 2, "sent": 0, "enabled": True}
    assert outbox.sent == []


@pytest.mark.parametrize("enabled", [False, True], ids=["tắt", "bật"])
def test_endpoint_verbose_and_logs_carry_no_personal_data(monkeypatch, admin, outbox, synced, caplog, enabled):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", enabled)
    seed_customers()

    with caplog.at_level(logging.DEBUG):
        resp = run_endpoint(verbose=1)

    body = resp.json()
    assert body["due"] == 2 and body["enabled"] is enabled
    assert body["followups"] == [
        {"template_key": "ask_age", "customer_id": ASK_AGE_ID[-4:]},
        {"template_key": "invite_visit", "customer_id": INVITE_ID[-4:]},
    ]
    private = (FB_NAME, KID_NAME, PHONE, PARENT_TEXT, BOT_TEXT, ASK_AGE_ID, INVITE_ID, *followup.TEMPLATES.values())
    assert [p for p in private if p in resp.text] == []
    logs = [r.getMessage() for r in caplog.records]
    assert [m for m in logs if any(p in m for p in (FB_NAME, KID_NAME, PHONE, PARENT_TEXT, BOT_TEXT))] == []
    assert [m for m in logs if any(t in m for t in followup.TEMPLATES.values())] == []


# --- .github/workflows/followup.yml ---

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "followup.yml"
SECRETS = {"BOT_BASE_URL": "https://casa.example", "BOT_ADMIN_SECRET": "s3cret-actions"}


def load_workflow():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 đọc khoá `on` thành True
    return workflow, workflow.get("on", workflow.get(True))


def test_workflow_runs_twice_an_hour_or_by_hand_never_on_push_or_pr():
    _, triggers = load_workflow()

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["schedule"] == [{"cron": "17 * * * *"}, {"cron": "47 * * * *"}]


def test_workflow_jobs_run_only_when_repo_variable_enabled():
    workflow, _ = load_workflow()

    assert workflow["jobs"]
    for job in workflow["jobs"].values():
        assert job["if"] == "vars.FOLLOWUP_ENABLED == 'true'"


def with_secrets(value: str) -> str:
    return re.sub(r"\$\{\{\s*secrets\.(\w+)\s*\}\}", lambda m: SECRETS[m.group(1)], value)


@pytest.mark.parametrize(("http_code", "ok"), [("200", True), ("403", False), ("500", False), ("000", False)])
def test_workflow_step_fails_unless_200_without_printing_body(tmp_path, http_code, ok):
    """Repo public nên log Actions công khai: curl bỏ body (-o /dev/null), chỉ in mã HTTP."""
    workflow, _ = load_workflow()
    steps = [step for job in workflow["jobs"].values() for step in job["steps"] if "run" in step]
    assert len(steps) == 1
    step = steps[0]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "curl-args"
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{args_file}"\nprintf "{http_code}"\n')
    fake_curl.chmod(0o755)
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    env.update({name: with_secrets(str(value)) for name, value in step.get("env", {}).items()})

    out = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", with_secrets(step["run"])],
        env=env,
        capture_output=True,
        text=True,
    )

    assert (out.returncode == 0) is ok
    args = args_file.read_text().splitlines()
    pairs = list(zip(args, args[1:]))
    for pair in [("-o", "/dev/null"), ("-w", "%{http_code}"), ("-X", "POST"), ("--max-time", "120"), ("--retry", "2")]:
        assert pair in pairs
    assert args[-1] == "https://casa.example/followup/run?secret=s3cret-actions"
    assert SECRETS["BOT_ADMIN_SECRET"] not in out.stdout + out.stderr

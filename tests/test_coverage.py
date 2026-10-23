"""Nhóm thông tin bot đã tư vấn (app/coverage.py): bảng câu bot gửi → nhóm bắt được, và điều kiện "đã tư vấn
tương đối đủ" của trường (phản hồi đợt 4) cho mẫu nhắc lại thứ 3."""

import pytest

from app import customer_memory, followup
from app.coverage import TOPICS, fully_consulted, topics_in_reply
from app.escalation import (
    ESCALATION_MESSAGE_ASK_PHONE,
    ESCALATION_MESSAGE_HAS_PHONE,
    ESCALATION_MESSAGE_PHONE_DECLINED,
    ESCALATION_MESSAGE_UPSET,
)

CID = "9000000000000701"

# (câu bot gửi, nhóm phải bắt được, theo thứ tự TOPICS)
POSITIVE = [
    ("Casa có 3 cơ sở tại Hà Nội ạ.", ["school"]),
    ("Cơ sở Chùa Láng ở 185 Huỳnh Thúc Kháng ạ.", ["school"]),
    ("Cơ sở Mỹ Đình nằm trong tòa FLC, 36 Phạm Hùng ạ.", ["school"]),
    ("Cơ sở Kim Mã ở ngõ 294 Kim Mã ạ.", ["school"]),
    ("Cơ sở Kim Mã nằm trong Hongkong Tower ạ.", ["school"]),
    ("Cơ sở Chùa Láng ở tòa Hong Kong Tower ạ.", ["school"]),
    ("Các con 3–6 tuổi học Cambridge Early Years ạ.", ["program"]),
    ("Lớp học theo phương pháp Montessori ạ.", ["program"]),
    # Giáo cụ là chương trình, không phải cơ sở vật chất
    ("Lớp có đầy đủ giáo cụ Montessori ạ.", ["program"]),
    ("Hệ Quốc tế học trọn 3 môn: English, Mathematics và Let's Explore ạ.", ["program"]),
    ("Môn Lets Explore giúp con khám phá thế giới ạ.", ["program"]),
    ("Môn Let’s Explore giúp con khám phá thế giới ạ.", ["program"]),
    ("Con học Phonics từ lớp 3 tuổi ạ.", ["program"]),
    ("Ngoài giờ học chính, các con có hoạt động ngoại khóa phong phú ạ.", ["extracurricular"]),
    ("Con có nhiều hoạt động ngoại khoá ạ.", ["extracurricular"]),
    ("Casa tổ chức dã ngoại 6 chuyến/năm ạ.", ["extracurricular"]),
    # Dã ngoại tham quan không phải lời mời tham quan trường
    ("Các con đi dã ngoại tham quan nông trại ạ.", ["extracurricular"]),
    ("Các con có giờ Science, Cooking, Art & Craft và Music ạ.", ["extracurricular"]),
    ("Con được làm quen Robotics qua mTiny ạ.", ["extracurricular"]),
    ("Trẻ được vẽ, tạo hình, thủ công, cắt dán ạ.", ["extracurricular"]),
    ("Trong năm có Family Day để ba mẹ tham gia cùng con ạ.", ["extracurricular"]),
    ("Thực đơn thay đổi theo tuần ạ.", ["menu"]),
    ("Chế độ dinh dưỡng do chuyên gia xây dựng, đủ nhóm chất ạ.", ["menu"]),
    ("Con có bữa nhẹ sáng, bữa trưa và bữa phụ chiều ạ.", ["menu"]),
    ("Trường có nhà bếp riêng tại mỗi cơ sở ạ.", ["menu"]),
    ("Casa tặng bé 1 tuần học thử miễn phí ạ.", ["trial"]),
    ("Mẹ cho bé học thử miễn phí trong một tuần nhé ạ.", ["trial"]),
    ("Mình tiện tuần này hay tuần sau ạ? [QUICK:trial_week]", ["trial"]),
    # Lời mời mềm (người vận hành 2026-10-22): nút Đăng ký học thử / Tìm hiểu thêm là lời mời học thử 1 tuần
    ("Ba/Mẹ có muốn cho bé thử không ạ? [QUICK:trial_invite]", ["trial"]),
    (
        "Ba/Mẹ cho bé học thử 1 tuần miễn phí để cảm nhận trực tiếp nhé, không biết Ba/Mẹ có muốn đăng ký luôn "
        "không ạ? [QUICK:trial_invite]",
        ["trial"],
    ),
    ("Ba/Mẹ cho bé học thử 1 tuần miễn phí để cảm nhận trực tiếp nhé, không biết Ba/Mẹ có muốn đăng ký luôn không ạ?",
     ["trial"]),
    ("Cơ sở vật chất của Casa được đầu tư bài bản ạ.", ["facilities"]),
    ("Mỗi lớp rộng khoảng 80–90 m² ạ.", ["facilities"]),
    ("Lớp rộng 80 m2 ạ.", ["facilities"]),
    ("Lớp rộng 80-90m2 ạ.", ["facilities"]),
    # Câu nói một khoản phí dùng vào việc gì không tính, câu sau vẫn tính
    ("Phí phát triển trường dùng để nâng cấp cơ sở vật chất. Trường có phòng gym và thư viện ạ.", ["facilities"]),
    ("Trường có phòng gym, thư viện và sân chơi ạ.", ["facilities"]),
    ("Không gian lớp học thoáng, có điều hòa ạ.", ["facilities"]),
    ("Phòng nào cũng có điều hoà ạ.", ["facilities"]),
    ("Ba/Mẹ muốn đến tham quan trường không ạ?", ["visit_invite"]),
    ("Em mời Ba/Mẹ đưa bé đến tham quan ạ.", ["visit_invite"]),
    ("Em sắp xếp lịch tham quan cho mình nhé ạ.", ["visit_invite"]),
    # Ví dụ trong prompt dạy "ghé tham quan"
    ("Ba/Mẹ có muốn ghé tham quan lớp không ạ?", ["visit_invite"]),
    ("Ba/Mẹ có muốn ghé tham quan không ạ?", ["visit_invite"]),
    ("Cuối tuần Ba/Mẹ ghé qua tham quan nhé ạ.", ["visit_invite"]),
    # Thứ được mời đến xem là đối tượng của lời mời, không phải thông tin cơ sở vật chất
    ("Em xin mời Ba/Mẹ ghé trường để tham quan cơ sở vật chất ạ.", ["visit_invite"]),
    ("Mời Ba/Mẹ đến tham quan không gian lớp học ạ.", ["visit_invite"]),
    ("Ba/Mẹ có thể tham quan lớp thực tế ạ.", ["visit_invite"]),
    ("Mình tiện buổi sáng hay buổi chiều ạ? [QUICK:visit_time]", ["visit_invite"]),
    # Nút Đặt lịch tham quan / Tìm hiểu thêm là lời mời tham quan, kể cả khi câu không nói chữ "tham quan"
    ("Nếu tiện, Ba/Mẹ đưa bé qua trường xem lớp một buổi nhé? [QUICK:visit_invite]", ["visit_invite"]),
    ("Không biết Ba/Mẹ có muốn ghé tham quan trường không ạ? [QUICK:visit_invite]", ["visit_invite"]),
    ("Không biết Ba/Mẹ có muốn ghé tham quan trường không ạ?", ["visit_invite"]),
    (
        "Dạ có ạ. Bé Bông 3 tuổi đúng độ tuổi học tiếng Anh theo Cambridge Early Years. "
        "Ba/Mẹ muốn đưa bé đến tham quan lớp thực tế vào buổi sáng hay buổi chiều ạ? [QUICK:visit_time]",
        ["program", "visit_invite"],
    ),
    (
        "Dạ Casa có cơ sở Mỹ Đình tại FLC 36 Phạm Hùng, lớp rộng 80–90 m², học Cambridge. "
        "Thực đơn đủ nhóm chất, có ngoại khóa Science, Cooking. Casa tặng 1 tuần học thử, "
        "mời Ba/Mẹ đặt lịch tham quan ạ [QUICK:visit_time]",
        list(TOPICS),
    ),
]

NEGATIVE = [
    ("chào hỏi tin đầu", "Dạ Casa chào Ba/Mẹ ạ 🌿 Cảm ơn Ba/Mẹ đã quan tâm đến Casa dei Bambini. Casa có chương "
     "trình cho các con từ khoảng 15 tháng đến 6 tuổi, lộ trình khác nhau theo từng độ tuổi. Bé nhà mình được "
     "bao nhiêu tháng tuổi ạ? [QUICK:age]"),
    ("chỉ liệt kê tên cơ sở", "Casa có cơ sở Chùa Láng, Mỹ Đình và Kim Mã ạ. Nhà mình ở gần cơ sở nào ạ?"),
    ("3 cơ sở rồi hỏi cơ sở nào", "Casa có 3 cơ sở: Chùa Láng, Mỹ Đình và Kim Mã. Nhà mình gần cơ sở nào ạ?"),
    ("tên khoản phí có ngoại khóa", "Ngoài học phí còn có tiền ăn, phí phát triển trường, phí học liệu và hoạt động "
     "ngoại khóa và đồng phục ạ."),
    ("khoản phí dùng cho cơ sở vật chất", "Phí phát triển trường dùng để đầu tư, bảo trì và nâng cấp định kỳ cơ sở "
     "vật chất, trang thiết bị ạ."),
    ("học thử không nói 1 tuần", "Ba/Mẹ có muốn cho bé học thử không ạ?"),
    ("Smart không phải Art", "Lớp có màn hình Smart TV ạ."),
    ("xin SĐT", "Ba/Mẹ cho em xin SĐT hoặc Zalo để tư vấn viên gửi chi tiết nhé ạ? [QUICK:phone]"),
    ("rỗng", ""),
]


@pytest.mark.parametrize(("reply", "topics"), POSITIVE, ids=[r[:40] for r, _ in POSITIVE])
def test_reply_signals_its_topics(reply, topics):
    assert topics_in_reply(reply) == topics


@pytest.mark.parametrize(("reply", "topics"), POSITIVE[:5], ids=[r[:40] for r, _ in POSITIVE[:5]])
def test_signals_ignore_case(reply, topics):
    assert topics_in_reply(reply.upper()) == topics


@pytest.mark.parametrize("reply", [r for _, r in NEGATIVE], ids=[name for name, _ in NEGATIVE])
def test_reply_without_topic_signal_gives_nothing(reply):
    assert topics_in_reply(reply) == []


def test_greeting_with_topic_buttons_gives_nothing_even_if_it_names_topics():
    greeting = (
        "Dạ Casa chào Ba/Mẹ ạ 🌿 Ba/Mẹ đang quan tâm Cambridge, thực đơn, cơ sở vật chất hay đặt lịch tham quan "
        "ạ? [QUICK:topics]"
    )

    assert topics_in_reply(greeting) == []


@pytest.mark.parametrize(
    "message",
    [
        ESCALATION_MESSAGE_ASK_PHONE,
        ESCALATION_MESSAGE_HAS_PHONE,
        ESCALATION_MESSAGE_PHONE_DECLINED,
        ESCALATION_MESSAGE_UPSET,
    ],
    ids=["chưa có SĐT", "có SĐT", "từ chối SĐT", "phụ huynh khó chịu"],
)
def test_handover_messages_give_nothing(message):
    assert topics_in_reply(message) == []


@pytest.mark.parametrize("key", ["ask_age", "ask_phone"])
def test_followup_templates_that_ask_for_age_or_phone_give_nothing(key):
    assert topics_in_reply(followup.TEMPLATES[key]) == []


ALL = list(TOPICS)
FULL = {"kid_age": "3 tuổi", "interested_campus": "Mỹ Đình", "topics_covered": ALL}


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (FULL, True),
        ({**FULL, "topics_covered": [*reversed(ALL), "fees"]}, True),
        ({"kid_age": "3 tuổi", "interested_campus": "Mỹ Đình", "message_count": 5}, False),
        ({**FULL, "interested_campus": ""}, False),
        ({k: v for k, v in FULL.items() if k != "kid_age"}, False),
        ({"kid_age": "3 tuổi", "area": "Cầu Giấy", "address": "Trung Kính", "topics_covered": ALL}, False),
        ({**FULL, "topics_covered": ALL[:-1]}, False),
        ({**FULL, "topics_covered": ALL[1:]}, False),
        ({**FULL, "topics_covered": " ".join(ALL)}, False),
        ({}, False),
    ],
    ids=[
        "đủ",
        "đủ, thêm khoá lạ",
        "hồ sơ cũ chưa có topics_covered",
        "thiếu cơ sở",
        "thiếu tuổi",
        "chỉ có khu vực/địa chỉ",
        "thiếu mời tham quan",
        "thiếu thông tin trường",
        "topics_covered là chuỗi",
        "rỗng",
    ],
)
def test_fully_consulted(profile, expected):
    assert fully_consulted(profile) is expected


def test_fully_consulted_survives_restart(monkeypatch):
    customer_memory.set_fields(CID, FULL)
    monkeypatch.setattr(customer_memory, "_customers", {})
    monkeypatch.setattr(customer_memory, "_loaded", False)

    assert fully_consulted(customer_memory.get_profile(CID)) is True

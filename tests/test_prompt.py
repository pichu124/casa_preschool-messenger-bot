"""Prompt tư vấn và lọc khối suy luận <think>: chỉ dùng provider giả, không mạng, không API key."""
import asyncio
import json
import re

import pytest

from app import ai_engine
from app.ai_engine import SYSTEM_PROMPT, AIEngine, AIProvider, strip_reasoning
from app.config import settings


class FakeProvider(AIProvider):
    def __init__(self, reply: str | None):
        self.reply = reply
        self.calls = 0

    async def generate(self, system_prompt: str, user_message: str, conversation_history: list[dict]) -> str:
        self.calls += 1
        return self.reply


def make_engine(monkeypatch, **providers: FakeProvider) -> AIEngine:
    monkeypatch.setattr(settings, "AI_MODEL_ORDER", list(providers))
    # AIEngine() tự đăng ký làm instance toàn cục; khôi phục sau test để không rò engine giả.
    monkeypatch.setattr(ai_engine, "ai_engine_instance", ai_engine.ai_engine_instance)
    engine = AIEngine(qa_context="Q&A giả")
    engine._providers = dict(providers)
    return engine


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<think>Phụ huynh hỏi địa chỉ.</think>\n\nDạ Casa có 3 cơ sở ạ.", "Dạ Casa có 3 cơ sở ạ."),
        ("<THINK>\nmulti\nline\n</Think>Dạ vâng ạ.", "Dạ vâng ạ."),
        ("<think>Bị cắt vì max_tokens, chưa kịp đóng thẻ", ""),
        ("Dạ Casa chào Ba/Mẹ ạ 🌿", "Dạ Casa chào Ba/Mẹ ạ 🌿"),
        (None, ""),
    ],
    ids=["closed", "case-insensitive-multiline", "truncated", "no-block", "none"],
)
def test_strip_reasoning(raw, expected):
    assert strip_reasoning(raw) == expected


def test_escalate_inside_reasoning_does_not_escalate(monkeypatch):
    engine = make_engine(
        monkeypatch,
        r1=FakeProvider("<think>Câu này khó, có lẽ nên trả [ESCALATE]</think>\n\nDạ Casa có 3 cơ sở tại Hà Nội ạ."),
    )

    resp = asyncio.run(engine.get_response("trường ở đâu"))

    assert resp.should_escalate is False
    assert resp.text == "Dạ Casa có 3 cơ sở tại Hà Nội ạ."
    assert resp.model_used == "r1"


def test_escalate_after_reasoning_still_escalates(monkeypatch):
    engine = make_engine(monkeypatch, r1=FakeProvider("<think>Hỏi bitcoin, ngoài lề.</think>[ESCALATE]"))

    resp = asyncio.run(engine.get_response("giá bitcoin hôm nay"))

    assert resp.should_escalate is True
    assert resp.model_used == "r1"


def test_reply_with_only_truncated_reasoning_falls_through_to_next_model(monkeypatch):
    truncated = FakeProvider("<think>Phụ huynh hỏi học phí, mình cần hỏi tuổi bé trước rồi")
    fallback = FakeProvider("Dạ Ba/Mẹ cho em xin tuổi bé nhà mình ạ?")
    engine = make_engine(monkeypatch, r1=truncated, llama=fallback)

    resp = asyncio.run(engine.get_response("học phí bao nhiêu"))

    assert resp.model_used == "llama"
    assert resp.text == "Dạ Ba/Mẹ cho em xin tuổi bé nhà mình ạ?"
    assert resp.should_escalate is False
    assert truncated.calls == 1


def test_extract_customer_info_parses_json_after_reasoning(monkeypatch):
    engine = make_engine(
        monkeypatch,
        r1=FakeProvider('<think>Có số Zalo.</think>\n{"phone": "0900000000", "kid_age": "3 tuổi"}'),
    )

    info = asyncio.run(engine.extract_customer_info("zalo của mình 0900000000, bé 3 tuổi"))

    assert info == {"phone": "0900000000", "kid_age": "3 tuổi"}


def test_extract_prompt_asks_for_lead_fields_and_sends_only_profile_fields(monkeypatch):
    recorder = RecordingProvider('{"phone_declined": true, "area": "Cầu Giấy"}')
    engine = make_engine(monkeypatch, fake=recorder)
    profile = {
        "kid_age": "3 tuổi",
        "interested_campus": "Mỹ Đình",
        "conversation_history": [{"role": "user", "content": "LICH-SU-BI-MAT", "timestamp": "2026-10-01T08:00:00"}],
        "session_summaries": [{"date": "2026-10-01", "summary": "TOM-TAT-CU"}],
        "first_seen": "2026-10-01T08:00:00",
        "message_count": 7,
    }

    info = asyncio.run(engine.extract_customer_info("nhà mình ở Cầu Giấy, chưa muốn để số đâu", profile))

    assert info == {"phone_declined": True, "area": "Cầu Giấy"}
    for field in ("area", "expected_start", "visit_request", "phone_declined"):
        assert f'"{field}"' in recorder.system_prompt
    assert "3 tuổi" in recorder.user_message and "Mỹ Đình" in recorder.user_message
    for leaked in ("LICH-SU-BI-MAT", "TOM-TAT-CU", "conversation_history", "session_summaries", "message_count"):
        assert leaked not in recorder.user_message


def test_classify_qa_parses_json_after_reasoning(monkeypatch):
    payload = {"category": "Xe đưa đón", "keywords": ["xe bus"], "similar_questions": ["Có xe đón không?"]}
    engine = make_engine(monkeypatch, r1=FakeProvider(f"<think>Phân loại.</think>{json.dumps(payload, ensure_ascii=False)}"))

    assert asyncio.run(engine.classify_qa("Có xe bus không?", "Dạ có ạ")) == payload


def test_summarize_conversation_drops_reasoning(monkeypatch):
    engine = make_engine(monkeypatch, r1=FakeProvider("<think>Tóm tắt thế nào nhỉ</think>Phụ huynh hỏi học phí cho bé 3 tuổi."))

    summary = asyncio.run(engine.summarize_conversation([{"role": "user", "content": "học phí bao nhiêu"}]))

    assert summary == "Phụ huynh hỏi học phí cho bé 3 tuổi."


def test_format_admin_reply_never_sends_reasoning_to_parent(monkeypatch):
    engine = make_engine(
        monkeypatch,
        r1=FakeProvider("<think>Viết lại cho lịch sự đã, rồi"),
        llama=FakeProvider("<think>ok</think>Dạ lớp mở vào tháng 9 ạ."),
    )

    reply = asyncio.run(engine.format_admin_reply("thang 9 mo lop", "khi nào mở lớp"))

    assert reply == "Dạ lớp mở vào tháng 9 ạ."


class RecordingProvider(FakeProvider):
    """Ghi lại đúng những gì AIEngine gửi cho model."""

    async def generate(self, system_prompt: str, user_message: str, conversation_history: list[dict]) -> str:
        self.system_prompt, self.user_message = system_prompt, user_message
        return await super().generate(system_prompt, user_message, conversation_history)


def model_input(monkeypatch, user_message: str, **kwargs) -> tuple[str, str]:
    recorder = RecordingProvider("Dạ Ba/Mẹ cho em xin tuổi bé ạ?")
    engine = make_engine(monkeypatch, fake=recorder)
    asyncio.run(engine.get_response(user_message, **kwargs))
    return recorder.system_prompt, recorder.user_message


def test_system_prompt_renders_qa_context():
    rendered = SYSTEM_PROMPT.format(qa_context="XYZ-QA-CONTEXT")

    assert "XYZ-QA-CONTEXT" in rendered
    assert AIEngine(qa_context="XYZ-QA-CONTEXT").system_prompt == rendered


OUTDATED_INSTRUCTIONS = [
    "giá cả chính xác",
    "1.5 đến 5 tuổi",
    "mỗi tuần em chỉ nhận 1 bé",
    "chuẩn Montessori quốc tế",
    "AMS",
    "Oxford",
    "KHÔNG thêm CTA",
    "trừ khi phụ huynh đang bày tỏ lo lắng",
]


@pytest.mark.parametrize("phrase", OUTDATED_INSTRUCTIONS)
def test_model_never_receives_outdated_instruction(monkeypatch, phrase):
    for kwargs in ({}, {"conversation_history": [{"role": "user", "content": "chào"}]}):
        system_prompt, user_message = model_input(monkeypatch, "học phí bao nhiêu", **kwargs)
        assert phrase not in system_prompt
        assert phrase not in user_message


# Trường bỏ workshop (phản hồi đợt 2); xe bus không nêu tuyến cụ thể (đợt 2 và 3).
REMOVED_TOPICS = ["workshop", "phan thúy", "kiểm tra tuyến", "tuyến gần nhất"]


@pytest.mark.parametrize("phrase", REMOVED_TOPICS)
def test_model_never_receives_removed_topic(monkeypatch, phrase):
    for kwargs in ({}, {"conversation_history": [{"role": "user", "content": "chào"}]}):
        system_prompt, user_message = model_input(monkeypatch, "có xe bus không", **kwargs)
        assert phrase not in system_prompt.lower()
        assert phrase not in user_message.lower()


def _escalate_rules(system_prompt: str, user_message: str) -> str:
    """Mục "KHI NÀO TRẢ LỜI [ESCALATE]" của prompt cộng dòng nhắc [ESCALATE] bắt buộc trong tin gửi model."""
    section = system_prompt.split('KHI NÀO TRẢ LỜI ĐÚNG CHUỖI "[ESCALATE]"', 1)[1].split("KÈM HÌNH ẢNH", 1)[0]
    reminders = [line for line in user_message.splitlines() if "BẮT BUỘC trả lời chính xác chuỗi [ESCALATE]" in line]
    assert reminders
    return section + "\n".join(reminders)


# Phản hồi đợt 3: chưa có tuyến xe bus, đủ phụ huynh đăng ký thì mở tuyến; không escalate chỉ vì xe bus.
@pytest.mark.parametrize("history", [[], [{"role": "user", "content": "bé 3 tuổi"}, {"role": "assistant", "content": "Dạ vâng ạ"}]])
def test_bus_answer_is_no_route_yet_and_never_escalates(monkeypatch, history):
    system_prompt, user_message = model_input(monkeypatch, "có xe bus không", conversation_history=history)

    for text in (system_prompt, user_message):
        assert "chưa có tuyến xe bus" in text
        assert "đủ phụ huynh đăng ký" in text
        assert "khu vực nhà" in text
        assert "chỉ vì xe bus" in text
    assert "xe bus" not in _escalate_rules(system_prompt, user_message)


def _care_text(system_prompt: str) -> str:
    """Quy tắc CARE cộng câu trả lời mẫu cho phụ huynh chê đắt."""
    lines = system_prompt.splitlines()
    rule = [line for line in lines if "→ CARE:" in line]
    example = [lines[i + 1] for i, line in enumerate(lines) if line.endswith("(CARE)")]
    assert rule and example
    return "\n".join(rule + example)


def test_care_resolves_with_value_and_trial_not_a_cheaper_campus(monkeypatch):
    system_prompt, _ = model_input(monkeypatch, "học phí đắt quá")
    care = _care_text(system_prompt)

    assert "Kim Mã" not in care and "Song ngữ" not in care
    assert "tối ưu chi phí" not in system_prompt
    assert "học thử" in care and "tham quan" in care


REQUIRED_KNOWLEDGE = [
    "15 tháng",
    "185 Huỳnh Thúc Kháng",
    "36 Phạm Hùng",
    "294 Kim Mã",
    "05/09",
    "17h30",
    "Connect",
    "Acknowledge",
    "Resolve",
    "Evaluate",
    "Zalo",
    "[ESCALATE]",
    "[IMAGES:",
    "[TRẠNG THÁI TƯ VẤN]",
    "Phụ huynh đã từ chối để lại SĐT: có",
    "Nguồn: quảng cáo",
    "Đã hẹn:",
]

QUICK_KEYS = {"topics", "age", "campus", "phone", "visit_time", "trial_week"}


@pytest.mark.parametrize("phrase", REQUIRED_KNOWLEDGE + [f"[QUICK:{key}]" for key in sorted(QUICK_KEYS)])
def test_system_prompt_carries_required_knowledge(monkeypatch, phrase):
    system_prompt, _ = model_input(monkeypatch, "trường ở đâu")

    assert phrase in system_prompt


def test_system_prompt_only_teaches_known_quick_reply_keys():
    assert set(re.findall(r"\[QUICK:([^\]]*)\]", SYSTEM_PROMPT)) == QUICK_KEYS


def test_cambridge_subjects_are_taught_per_system():
    # Phản hồi đợt 4 (G2): hệ Quốc tế học đủ 3 môn English, Mathematics, Let's Explore; Kim Mã chỉ môn English.
    assert "Understanding the World" not in SYSTEM_PROMPT
    assert re.search(r"Quốc tế[^.;\n]{0,80}English[^.;\n]{0,10}Mathematics[^.;\n]{0,10}Let's Explore", SYSTEM_PROMPT)
    assert re.search(r"Kim Mã[^.;\n]{0,40}English", SYSTEM_PROMPT)
    for clause in re.split(r"[.;\n]", SYSTEM_PROMPT):
        if "Kim Mã" in clause or "Song ngữ" in clause:
            assert "Mathematics" not in clause and "Let's Explore" not in clause, clause


def test_system_prompt_instructions_stay_compact():
    instructions = SYSTEM_PROMPT.replace("{qa_context}", "")
    assert len(instructions) <= 10_000, len(instructions)
    assert "{" not in instructions and "}" not in instructions


def test_first_message_asks_for_standard_greeting(monkeypatch):
    _, user_message = model_input(monkeypatch, "cho hoi hoc phi")

    assert "[FIRST_MESSAGE] cho hoi hoc phi" in user_message
    assert "Dạ Casa chào Ba/Mẹ ạ" in user_message


def test_new_parent_with_known_context_still_gets_greeting(monkeypatch):
    # Khách mới bấm quảng cáo: chưa có lịch sử nhưng đã có hồ sơ (nguồn, trạng thái tư vấn).
    context = '[THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT]:\n[TRẠNG THÁI TƯ VẤN]:\n- Giai đoạn: Mới\n- Nguồn: quảng cáo "Học thử 1 tuần"'

    _, user_message = model_input(monkeypatch, "cho hoi hoc phi", customer_context=context)

    assert "[FIRST_MESSAGE] cho hoi hoc phi" in user_message
    assert "Dạ Casa chào Ba/Mẹ ạ" in user_message
    assert 'Nguồn: quảng cáo "Học thử 1 tuần"' in user_message


def test_reminder_defers_next_step_to_consultation_state(monkeypatch):
    context = "[THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT]:\n[TRẠNG THÁI TƯ VẤN]:\n- Giai đoạn: Đã hẹn tham quan/học thử\n- Đã hẹn: tham quan buổi sáng"

    _, user_message = model_input(
        monkeypatch,
        "cảm ơn em",
        customer_context=context,
        conversation_history=[{"role": "user", "content": "buổi sáng nhé"}, {"role": "assistant", "content": "Dạ vâng ạ"}],
    )

    reminder = user_message.split("[NHẮC NHỞ QUAN TRỌNG]:", 1)[1]
    assert "[TRẠNG THÁI TƯ VẤN]" in reminder
    assert "không hẹn lại" in reminder


def test_follow_up_message_is_not_marked_first(monkeypatch):
    _, user_message = model_input(
        monkeypatch,
        "có xe bus không",
        conversation_history=[{"role": "user", "content": "bé 3 tuổi"}, {"role": "assistant", "content": "Dạ vâng ạ"}],
    )

    assert "[FIRST_MESSAGE]" not in user_message
    assert "Dạ Casa chào Ba/Mẹ ạ" not in user_message

"""Prompt tư vấn và lọc khối suy luận <think>: chỉ dùng provider giả, không mạng, không API key."""
import asyncio
import importlib.util
import json
import re
from pathlib import Path

import pytest

from app import ai_engine
from app.ai_engine import SYSTEM_PROMPT, AIEngine, AIProvider, strip_reasoning
from app.config import settings


class FakeProvider(AIProvider):
    def __init__(self, reply: str | None):
        self.reply = reply
        self.calls = 0

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024) -> str:
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

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024) -> str:
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


def test_kim_ma_is_not_taught_as_english_only():
    # Phản hồi đợt 5 (D2) và 6: ngoài Cambridge môn English, Kim Mã học theo 5 lĩnh vực Montessori. Không liệt kê
    # dở ("còn toán… theo Montessori"): model sẽ tự đoán phần còn thiếu.
    assert "Kim Mã chỉ học" not in SYSTEM_PROMPT
    assert re.search(r"Kim Mã[^.;\n]{0,40}English[^.;\n]{0,10}còn lại theo 5 lĩnh vực Montessori", SYSTEM_PROMPT)
    assert "toán…" not in SYSTEM_PROMPT
    kim_ma = [c for c in re.split(r"[.;\n]", SYSTEM_PROMPT) if "Kim Mã học" in c]
    assert kim_ma and all("…" not in c for c in kim_ma), kim_ma


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


# Phản hồi người dùng 2026-10-22: bot dài dòng, nhắc lại thông tin phụ huynh vừa gửi (SĐT, cơ sở, buổi hẹn) và
# đoán "anh" từ tên Facebook. Quyết định: 1–3 câu ngắn; xưng "em" – "Ba/Mẹ", chỉ đổi khi phụ huynh tự xưng;
# không đọc lại thông tin đã biết.
_spec = importlib.util.spec_from_file_location("eval_chat", Path(__file__).resolve().parent.parent / "scripts" / "eval_chat.py")
eval_chat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_chat)

FOLLOW_UP = [{"role": "user", "content": "bé 3 tuổi"}, {"role": "assistant", "content": "Vâng ạ"}]
# "mẹ" đứng riêng (gọi phụ huynh là mẹ), không tính "Ba/Mẹ", "ba mẹ".
LONE_ME = re.compile(r"(?<!Ba/)(?<!ba )(?<!Ba )\b[Mm]ẹ\b")
ANH_CHI = re.compile(r"(?<!tiếng )\b(?:anh|chị)\b")


def _reminder(user_message: str) -> str:
    return user_message.split("[NHẮC NHỞ QUAN TRỌNG]:", 1)[1]


def _reminders(monkeypatch) -> list[str]:
    """Khối nhắc nhở cho tin đầu tiên, tin tiếp theo và khách cũ quay lại."""
    context = "[THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT]:\n- Bé: tên Bông, 3 tuổi"
    cases = (
        {},
        {"conversation_history": FOLLOW_UP},
        {"conversation_history": FOLLOW_UP, "customer_context": context, "gap_hours": 72},
    )
    return [_reminder(model_input(monkeypatch, "học phí bao nhiêu", **kwargs)[1]) for kwargs in cases]


def _examples() -> list[tuple[str, str]]:
    """(dòng phụ huynh, câu "Em: …" ngay sau) trong mục VÍ DỤ của prompt."""
    lines = SYSTEM_PROMPT.split("\nVÍ DỤ", 1)[1].split("CƠ SỞ DỮ LIỆU Q&A", 1)[0].splitlines()
    return [(lines[i - 1], m.group(1)) for i, line in enumerate(lines) if (m := re.fullmatch(r'Em: "(.*)"', line))]


def test_replies_are_one_to_three_short_sentences(monkeypatch):
    assert "1–3 câu" in SYSTEM_PROMPT
    assert "2–5 câu" not in SYSTEM_PROMPT
    for reminder in _reminders(monkeypatch):
        assert "1–3 câu" in reminder
        assert "2-5 câu" not in reminder


def test_parent_is_ba_me_unless_they_name_themselves_never_from_facebook_name(monkeypatch):
    for text in [SYSTEM_PROMPT] + _reminders(monkeypatch):
        lowered = text.lower()
        assert "ba/mẹ" in lowered
        assert "tự xưng" in lowered
        assert re.search(r"không (?:được )?đoán giới tính[^\n]*tên facebook", lowered), text
        assert "(hoặc 'anh/chị')" not in text
    # Câu mẫu trong khối nhắc nhở (vd chào khách cũ) không tự gọi "mẹ Bông".
    samples = [s for r in _reminders(monkeypatch) for s in re.findall(r"VD: '([^']*)'", r)]
    assert samples
    for sample in samples:
        assert not LONE_ME.search(sample) and not ANH_CHI.search(sample), sample


def test_known_info_is_used_not_read_back(monkeypatch):
    for text in [SYSTEM_PROMPT] + _reminders(monkeypatch)[1:]:
        lowered = text.lower()
        assert re.search(r"không nhắc lại[^\n]*(?:đã biết|vừa gửi)", lowered), text
        assert re.search(r"không (?:bao giờ )?đọc lại (?:số điện thoại|sđt)", lowered), text
    assert "nhắc tên/tuổi bé đã biết" not in SYSTEM_PROMPT
    assert all("Tham chiếu thông tin bé đã biết" not in r for r in _reminders(monkeypatch))


def test_known_info_steers_the_advice(monkeypatch):
    # "Chỉ để không hỏi lại" làm model bỏ qua cơ sở đã biết: PH Kim Mã hỏi GV nước ngoài được trả lời theo hệ Quốc tế.
    for text in [SYSTEM_PROMPT] + _reminders(monkeypatch):
        assert "chỉ để không hỏi lại" not in text
        assert re.search(r"tư vấn đúng hệ/cơ sở/nhóm tuổi[^\n]*không hỏi lại[^\n]*không kể lại", text), text


def test_prompt_examples_are_short_varied_and_never_guess_how_to_address_parent():
    examples = [reply for _, reply in _examples()]
    assert len(examples) >= 8

    for reply in examples:
        assert eval_chat.sentence_count(reply) <= 3, reply
        assert not ANH_CHI.search(reply), reply
        assert not LONE_ME.search(reply), reply
        assert "ghi nhận" not in reply, reply
        assert not re.search(r"\d{8,}", reply), reply
    assert sum(reply.startswith("Dạ") for reply in examples) <= len(examples) // 2
    assert sum(bool(re.search(r"[\U0001F300-\U0001FAFF]", reply)) for reply in examples) <= 2


@pytest.mark.parametrize(
    ("parent_says", "topics"),
    [
        ("tieng anh", {"program", "visit_invite"}),
        ("nhat nhung", {"trial"}),
        ("Dưới 2 tuổi", {"program"}),
    ],
)
def test_short_examples_still_name_their_topics(parent_says, topics):
    from app.coverage import topics_in_reply

    replies = [reply for parent, reply in _examples() if parent_says in parent]
    assert len(replies) == 1
    assert topics <= set(topics_in_reply(replies[0])), replies[0]


def test_booked_visit_is_the_one_exception_to_ending_with_a_next_step(monkeypatch):
    # Ví dụ chốt hẹn không có bước tiếp theo: prompt và eval phải cùng nói vậy.
    rule6 = next(line for line in SYSTEM_PROMPT.splitlines() if line.startswith("6. "))
    booked = next(line for line in SYSTEM_PROMPT.splitlines() if '"Đã hẹn: …"' in line)
    assert "'Đã hẹn'" in rule6.split("kết thúc bằng", 1)[0], rule6
    assert "không cần bước tiếp theo" in booked, booked
    assert all("không cần bước tiếp theo" in r for r in _reminders(monkeypatch))

    parent, reply = _examples()[-1]
    assert "sang mai duoc khong" in parent
    turns = eval_chat.SCENARIOS["hen_tham_quan"]
    i = next(i for i, t in enumerate(turns) if t.message == "sáng mai được không")
    assert "tham quan buổi sáng" in turns[i - 1].message
    problems = eval_chat.check_turn(turns[i], False, False, reply, [turns[i].message])
    # Câu ví dụ đương nhiên bị bắt là chép; ở đây chỉ kiểm lượt chốt hẹn không cần bước tiếp theo.
    assert [p for p in problems if "chép câu ví dụ" not in p] == [], problems
    # Lượt bình thường vẫn bị bắt khi thiếu bước tiếp theo.
    problems = eval_chat.check_turn(eval_chat.Turn("trường ở đâu"), False, False, reply, ["trường ở đâu"])
    assert any("bước tiếp theo" in p for p in problems), problems


# Thử DeepSeek thật 2026-10-22: vừa xác nhận tham quan buổi sáng, phụ huynh hỏi "sáng mai được không" thì bot gửi lại
# gần nguyên câu xác nhận và chép nguyên câu ví dụ chốt hẹn trong prompt; câu chê đắt gần như chép ví dụ CARE.
REPEATED_CONFIRMATION = (
    "Vâng ạ, tư vấn viên sẽ liên hệ Ba/Mẹ để chốt giờ tham quan buổi sáng tại cơ sở Chùa Láng. Hẹn gặp Ba/Mẹ và bé ở trường nhé!",
    "Vâng ạ, tư vấn viên sẽ liên hệ Ba/Mẹ để chốt giờ tham quan sáng mai. Hẹn gặp Ba/Mẹ và bé ở trường nhé!",
)


def test_prompt_forbids_repeating_the_last_reply_and_copying_examples(monkeypatch):
    reminders = _reminders(monkeypatch)
    for text in [SYSTEM_PROMPT] + reminders:
        lowered = text.lower()
        assert re.search(r"không lặp lại[^\n]*vừa gửi", lowered), text
        assert re.search(r"không chép[^\n]*câu ví dụ", lowered), text
    # Phụ huynh đổi/chốt cụ thể hơn sau khi em đã xác nhận: trả lời thẳng ý mới, không gửi lại câu xác nhận.
    booked = [line for line in SYSTEM_PROMPT.splitlines() if '"Đã hẹn: …"' in line]
    booked += [line for r in reminders for line in r.splitlines() if "'Đã hẹn'" in line]
    assert len(booked) == 1 + len(reminders)
    for line in booked:
        assert "không lặp lại câu xác nhận" in line, line


def test_care_and_booking_examples_are_short_sentences():
    examples = _examples()
    care = [reply for parent, reply in examples if parent.endswith("(CARE)")]
    booking = [reply for parent, reply in examples if "sang mai" in parent]
    assert len(care) == 1 and len(booking) == 1
    for reply in care + booking:
        for sentence in re.split(r"(?<=[.?!])\s+", re.sub(r"\[QUICK:[^\]]*\]", "", reply).strip()):
            assert len(re.findall(r"\w+", sentence)) <= 20, sentence


def test_eval_flags_reply_that_repeats_the_previous_one():
    previous, repeated = REPEATED_CONFIRMATION
    turn = eval_chat.Turn("sáng mai được không", next_step=False)

    problems = eval_chat.check_turn(turn, False, False, repeated, [turn.message], previous_reply=previous)

    assert len(problems) == 1 and "lặp lại tin trước" in problems[0], problems
    fresh = "Được ạ, sáng mai Ba/Mẹ cứ đưa bé qua nhé."
    assert eval_chat.check_turn(turn, False, False, fresh, [turn.message], previous_reply=previous) == []


def test_eval_flags_reply_copied_from_prompt_examples():
    turn = eval_chat.Turn("học phí đắt quá", next_step=False)
    care = next(reply for parent, reply in _examples() if parent.endswith("(CARE)"))
    booking = _examples()[-1][1]
    for reply in (care, booking):
        problems = eval_chat.check_turn(turn, False, False, reply, [turn.message])
        assert any("chép câu ví dụ" in p for p in problems), (reply, problems)

    fresh_care = (
        "Dạ em hiểu ạ, đây là khoản lớn với gia đình. Bù lại con được cô nước ngoài kèm cả ngày. "
        "Ba/Mẹ đưa bé qua tham quan lớp một buổi nhé, sáng hay chiều ạ?"
    )
    assert eval_chat.check_turn(turn, False, False, fresh_care, [turn.message]) == []
    # Câu chào bắt buộc ở tin đầu tiên giống hệt ví dụ nhưng không phải chép.
    greeting = "Dạ Casa chào Ba/Mẹ ạ 🌿 Cảm ơn Ba/Mẹ đã quan tâm đến Casa dei Bambini. Bé được mấy tháng rồi ạ? [QUICK:age]"
    assert eval_chat.check_turn(eval_chat.Turn("cho hỏi học phí"), True, False, greeting, ["cho hỏi học phí"]) == []


def test_facebook_name_never_reaches_the_model(monkeypatch):
    from app.customer_memory import format_profile_for_prompt

    context = format_profile_for_prompt({"parent_name": "Minh Thử", "kid_age": "20 tháng", "phone": "0900000999"})

    assert "Minh Thử" not in context
    _, user_message = model_input(monkeypatch, "sáng mai nhé", customer_context=context, conversation_history=FOLLOW_UP)
    assert "Minh Thử" not in user_message
    assert "20 tháng" in user_message


def test_admin_reply_is_rewritten_in_the_same_short_voice(monkeypatch):
    recorder = RecordingProvider("Dạ lớp mở vào tháng 9 ạ.")
    engine = make_engine(monkeypatch, fake=recorder)

    asyncio.run(engine.format_admin_reply("thang 9 mo lop", "khi nào mở lớp"))

    # Harness của skill verify-casa-bot nhận diện lời gọi này qua câu mở đầu.
    assert recorder.system_prompt.startswith("Bạn là nhân viên tư vấn trường mầm non Casa")
    assert "ngắn gọn" in recorder.system_prompt
    assert "Ba/Mẹ" in recorder.system_prompt
    assert "tự xưng" in recorder.system_prompt
    assert "khi phù hợp" not in recorder.system_prompt
    assert "không thêm thông tin" in recorder.system_prompt


def test_admin_reply_keeps_every_fact_admin_gave(monkeypatch):
    # Câu admin viết lại được gửi thẳng cho phụ huynh: giới hạn "1–3 câu" từng cho phép model bỏ bớt lịch, giờ, số.
    admin_answer = "T2 8h30 Montessori, T4 9h Science (cô Lan), T6 15h Cooking; mang 2 bộ quần áo, đóng 500k phí học liệu"
    recorder = RecordingProvider("Dạ lịch tuần của lớp như sau ạ.")
    engine = make_engine(monkeypatch, fake=recorder)

    asyncio.run(engine.format_admin_reply(admin_answer, "lịch học tuần này thế nào"))

    prompt = recorder.system_prompt
    assert recorder.system_prompt.startswith("Bạn là nhân viên tư vấn trường mầm non Casa")
    assert "1–3 câu" not in prompt
    assert re.search(r"giữ đủ mọi dữ kiện[^.]*ngày, giờ, con số, tên[^.]*danh sách", prompt, re.I), prompt
    assert "dài hơn 3 câu" in prompt
    assert admin_answer in recorder.user_message


PHONE = "0900000999"
PRODUCTION_LIKE = {
    "doc-lai-sdt-doan-anh": (
        f"Dạ em cảm ơn anh Minh đã để lại số ạ 🌿 Em đã ghi nhận SĐT {PHONE} và tư vấn viên sẽ liên hệ anh sớm ạ. "
        "Anh cho em biết bé được bao nhiêu tháng tuổi nhé ạ?",
        ["đọc lại SĐT", "gọi 'anh'"],
    ),
    "khuon-em-ghi-nhan-sdt-tach-so": (
        "Dạ, em đã ghi nhận Ba/Mẹ muốn tham quan cơ sở Chùa Láng vào sáng mai ạ. "
        f"Tư vấn viên sẽ liên hệ qua số {PHONE[:4]} {PHONE[4:7]} {PHONE[7:]} để xác nhận ạ.",
        ["đọc lại SĐT", "em ghi nhận"],
    ),
    "nam-cau": (
        "Dạ nhóm 15 tháng–3 tuổi học theo Montessori ạ. Con được chăm sóc sát sao. Con làm quen tiếng Anh. "
        "Con tự lập hơn. Ba/Mẹ quan tâm cơ sở nào ạ?",
        ["dài 5 câu"],
    ),
}


@pytest.mark.parametrize(("reply", "expected"), PRODUCTION_LIKE.values(), ids=PRODUCTION_LIKE.keys())
def test_eval_flags_bot_like_replies(reply, expected):
    problems = eval_chat.style_problems(reply, parent_messages=[PHONE], known_phones={PHONE})

    assert len(problems) == len(expected), problems
    for problem, phrase in zip(problems, expected):
        assert phrase in problem


def test_eval_passes_short_human_replies():
    good = (
        "Cảm ơn Ba/Mẹ, tư vấn viên sẽ liên hệ sớm ạ. Bé học tiếng Anh cả ngày với cô nước ngoài. "
        "Bé dự kiến nhập học khi nào ạ? [QUICK:age]"
    )
    assert eval_chat.style_problems(good, parent_messages=[PHONE], known_phones={PHONE}) == []
    # Phụ huynh tự xưng "chị" thì bot gọi "chị" là đúng.
    assert eval_chat.style_problems("Dạ chị cho em xin tuổi bé ạ?", parent_messages=["chị muốn hỏi học phí"], known_phones=set()) == []
    assert eval_chat.sentence_count("Dạ Casa chào Ba/Mẹ ạ 🌿 Cảm ơn Ba/Mẹ. Bé mấy tháng rồi ạ? [QUICK:age]") == 2


@pytest.mark.parametrize(
    ("reply", "sentences"),
    [
        ("Con có Science, Art, v.v. và nhiều hoạt động khác ạ. Ba/Mẹ muốn ghé tham quan không ạ?", 2),
        ("Con có Science, Art, v.v. Ba/Mẹ muốn ghé tham quan không ạ?", 2),
        ("Lớp có Montessori, tiếng Anh... và ngoại khóa ạ. Ba/Mẹ quan tâm cơ sở nào ạ?", 2),
        ("Lớp có Montessori, tiếng Anh… và ngoại khóa ạ. Ba/Mẹ quan tâm cơ sở nào ạ?", 2),
        ("Dạ vâng... Bé nhà mình mấy tuổi rồi ạ?", 2),
        ("Lớp 0–3 tuổi học với cô nước ngoài khoảng 1.5 giờ mỗi ngày ạ. Ba/Mẹ quan tâm cơ sở nào ạ?", 2),
        ("Ba/Mẹ xem thêm ở casa.edu.vn hoặc mail info@casa.edu.vn nhé. Bé mấy tuổi rồi ạ?", 2),
        ("Dạ Casa chào Ba/Mẹ ạ 🌿. Cảm ơn Ba/Mẹ đã quan tâm đến Casa dei Bambini. Bé mấy tháng rồi ạ? [QUICK:age]", 2),
        ("Dạ Casa chào Ba/Mẹ ạ 🌿! Cảm ơn Ba/Mẹ đã quan tâm đến Casa dei Bambini. Bé mấy tháng rồi ạ? [QUICK:age]", 2),
        ("Dạ có ạ. Con học Cambridge. 3 cơ sở đều có cô nước ngoài. Ba/Mẹ quan tâm cơ sở nào ạ?", 4),
    ],
    ids=["vv-giua-cau", "vv-cuoi-cau", "ba-cham", "dau-ba-cham", "ba-cham-het-cau", "so-thap-phan", "domain-email",
         "emoji-cham", "emoji-cham-than", "bon-cau-that"],
)
def test_eval_sentence_count_ignores_dots_that_do_not_end_a_sentence(reply, sentences):
    assert eval_chat.sentence_count(reply) == sentences


ASK_TRIAL = " Ba/Mẹ cho bé học thử tuần này hay tuần sau ạ?"


@pytest.mark.parametrize(
    ("reply", "flagged"),
    [
        ("Mẹ yên tâm nhé, các cô đồng hành cùng bé ạ." + ASK_TRIAL, "'Mẹ'"),
        ("Dạ ba cho em xin tuổi bé ạ?", "'ba'"),
        ("Em gửi mẹ bé lịch tham quan nhé ạ." + ASK_TRIAL, "'mẹ'"),
    ],
)
def test_eval_flags_lone_me_or_ba_when_parent_never_named_themselves(reply, flagged):
    problems = eval_chat.style_problems(reply, parent_messages=["con mình nhút nhát lắm"], known_phones=set())

    assert len(problems) == 1 and flagged in problems[0], problems


@pytest.mark.parametrize(
    "reply",
    [
        "Family Day để ba mẹ tham gia cùng con ạ." + ASK_TRIAL,
        "Bé ba tuổi học lớp Mầm, có buổi học thứ Ba ạ." + ASK_TRIAL,
        "Ngày đầu bé hay khóc vì nhớ mẹ, các cô dỗ con từ từ ạ." + ASK_TRIAL,
        "Bé có anh trai học ở Casa thì được ưu đãi anh chị em ạ." + ASK_TRIAL,
        "Cô giáo người Anh dạy tiếng Anh cả ngày ạ." + ASK_TRIAL,
        "Bé có chị gái đang học ở Kim Mã thì con sẽ quen nhanh ạ." + ASK_TRIAL,
    ],
    ids=["ba-me", "so-ba-thu-ba", "nho-me", "anh-trai", "nguoi-anh", "chi-gai"],
)
def test_eval_does_not_mistake_family_words_for_addressing_the_parent(reply):
    assert eval_chat.style_problems(reply, parent_messages=["con mình nhút nhát lắm"], known_phones=set()) == []


def test_eval_allows_me_once_parent_names_themselves():
    reply = "Dạ mẹ Na cho em xin tuổi bé ạ?"
    assert eval_chat.style_problems(reply, parent_messages=["mình là mẹ bé Na"], known_phones=set()) == []


def test_eval_catches_phone_read_back_in_brackets_format():
    reply = "Tư vấn viên sẽ gọi số (090) 000-0999 ạ."
    for parent_messages, known_phones in (([PHONE], set()), (["số mình (090) 000-0999"], set()), ([], {PHONE})):
        problems = eval_chat.style_problems(reply, parent_messages=parent_messages, known_phones=known_phones)
        assert any("đọc lại SĐT" in p for p in problems), (parent_messages, problems)

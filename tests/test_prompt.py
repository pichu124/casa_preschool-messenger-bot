"""Prompt tư vấn và lọc khối suy luận <think>: chỉ dùng provider giả, không mạng, không API key."""
import asyncio
import json

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
]


@pytest.mark.parametrize("phrase", REQUIRED_KNOWLEDGE)
def test_system_prompt_carries_required_knowledge(monkeypatch, phrase):
    system_prompt, _ = model_input(monkeypatch, "trường ở đâu")

    assert phrase in system_prompt


def test_first_message_asks_for_standard_greeting(monkeypatch):
    _, user_message = model_input(monkeypatch, "cho hoi hoc phi")

    assert "[FIRST_MESSAGE] cho hoi hoc phi" in user_message
    assert "Dạ Casa chào Ba/Mẹ ạ" in user_message


def test_follow_up_message_is_not_marked_first(monkeypatch):
    _, user_message = model_input(
        monkeypatch,
        "có xe bus không",
        conversation_history=[{"role": "user", "content": "bé 3 tuổi"}, {"role": "assistant", "content": "Dạ vâng ạ"}],
    )

    assert "[FIRST_MESSAGE]" not in user_message
    assert "Dạ Casa chào Ba/Mẹ ạ" not in user_message

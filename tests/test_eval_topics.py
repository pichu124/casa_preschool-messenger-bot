"""Bộ chấm chủ đề của scripts/eval_chat.py: model trích xuất gắn đúng bao nhiêu phần trăm chủ đề (app/topics.py).
Chỉ dùng provider giả, không mạng, không API key."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from app import ai_engine
from app.ai_engine import AIProvider
from app.config import settings
from app.topics import TOPICS

_spec = importlib.util.spec_from_file_location("eval_chat", Path(__file__).resolve().parent.parent / "scripts" / "eval_chat.py")
eval_chat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_chat)
TopicCase = eval_chat.TopicCase

EXTRACT_PROMPT_START = "Bạn là hệ thống trích xuất"


class FakeExtractor(AIProvider):
    """Trả "topics" theo tin phụ huynh có trong lời gọi; tin lạ (lời gọi chat) thì trả một câu tư vấn."""

    def __init__(self, answers: dict[str, list] | None = None, fail: bool = False):
        self.answers = answers or {}
        self.fail = fail
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024) -> str:
        self.calls.append((system_prompt, user_message))
        if self.fail:
            raise RuntimeError("401 sai key")
        if not system_prompt.startswith(EXTRACT_PROMPT_START):
            return "Dạ Casa chào Ba/Mẹ ạ. Ba/Mẹ cho em xin tuổi bé nhé?"
        (topics,) = [t for message, t in self.answers.items() if f"Tin nhắn phụ huynh: {message}" in user_message]
        return json.dumps({"topics": topics}, ensure_ascii=False) if topics else "{}"


@pytest.fixture
def fake(monkeypatch) -> FakeExtractor:
    provider = FakeExtractor()
    monkeypatch.setattr(settings, "AI_MODEL_ORDER", ["fake"])
    monkeypatch.setitem(ai_engine.PROVIDER_MAP, "fake", lambda: provider)
    monkeypatch.setitem(ai_engine.API_KEY_MAP, "fake", "key-gia")
    # AIEngine() tự đăng ký làm instance toàn cục; khôi phục sau test để không rò engine giả.
    monkeypatch.setattr(ai_engine, "ai_engine_instance", ai_engine.ai_engine_instance)
    return provider


FIVE = [
    TopicCase("hp bn ạ", ("Học phí",)),
    TopicCase("có camera không, ăn uống thế nào", ("An toàn/sức khoẻ/camera", "Ăn uống/thực đơn")),
    TopicCase("Dưới 2 tuổi", (), last_bot_message="Ba/Mẹ cho em xin tuổi bé ạ?"),
    TopicCase("có xe bus không", ("Xe đưa đón",)),
    TopicCase("Cảm ơn ạ", ()),
]
ALL_RIGHT = {
    "hp bn ạ": ["Học phí"],
    # Model viết khác chính tả trong TOPICS: clean_topics vẫn nhận như bot.
    "có camera không, ăn uống thế nào": ["ăn uống/thực đơn", "An toàn/sức khỏe/camera"],
    "Dưới 2 tuổi": [],
    "có xe bus không": ["Xe đưa đón", "Giá vé máy bay"],
    "Cảm ơn ạ": [],
}


def run(selected: list[str]) -> int:
    return asyncio.run(eval_chat.main(selected))


@pytest.mark.parametrize(
    ("expected", "got", "grade"),
    [
        ((), [], eval_chat.FULL),
        (("Học phí",), ["Học phí"], eval_chat.FULL),
        (("Học phí", "Ưu đãi"), ["Ưu đãi", "Học phí"], eval_chat.FULL),
        (("Học phí", "Ưu đãi"), ["Học phí"], eval_chat.PARTIAL),
        (("Học phí",), ["Học phí", "Ưu đãi"], eval_chat.PARTIAL),
        (("Học phí",), [], eval_chat.WRONG),
        ((), ["Khác"], eval_chat.WRONG),
        (("Học phí",), ["Ưu đãi"], eval_chat.WRONG),
    ],
    ids=["rỗng-rỗng", "một", "thứ tự khác", "thiếu một", "thừa một", "bỏ sót", "gắn khi không có", "lệch hẳn"],
)
def test_grade_topics(expected, got, grade):
    assert eval_chat.grade_topics(expected, got) == grade


def test_topics_alone_runs_only_the_topic_set_and_grades_each_message(monkeypatch, fake, capsys):
    monkeypatch.setattr(eval_chat, "TOPIC_CASES", FIVE)
    fake.answers = {
        **ALL_RIGHT,
        "có camera không, ăn uống thế nào": ["Ăn uống/thực đơn"],
        "Cảm ơn ạ": ["Khác"],
    }

    code = run(["topics"])

    out = capsys.readouterr().out
    # Mỗi câu là đúng 1 lượt gọi extract; không có lời gọi chat nào của kịch bản hội thoại.
    assert len(fake.calls) == len(FIVE)
    assert all(system.startswith(EXTRACT_PROMPT_START) for system, _ in fake.calls)
    # Cùng tham số như process_message: câu bot hỏi trước đó và hồ sơ đã biết.
    age_call = next(user for _, user in fake.calls if "Dưới 2 tuổi" in user)
    assert "Câu bot vừa hỏi: Ba/Mẹ cho em xin tuổi bé ạ?" in age_call
    assert "Thông tin đã biết" in age_call
    lines = {line for line in out.splitlines() if " | " in line}
    assert f"{eval_chat.FULL} | 'hp bn ạ' | kỳ vọng ['Học phí'] | ra ['Học phí']" in lines
    assert (
        f"{eval_chat.PARTIAL} | 'có camera không, ăn uống thế nào' "
        "| kỳ vọng ['An toàn/sức khoẻ/camera', 'Ăn uống/thực đơn'] | ra ['Ăn uống/thực đơn']"
    ) in lines
    assert f"{eval_chat.WRONG} | 'Cảm ơn ạ' | kỳ vọng [] | ra ['Khác']" in lines
    assert len(lines) == len(FIVE)
    assert "đúng hoàn toàn 3/5 (60%)" in out
    assert "đúng một phần 1/5 (20%)" in out
    assert code == 1


@pytest.mark.parametrize(("wrong", "code"), [(0, 0), (1, 0), (2, 1)])
def test_topic_set_passes_at_the_threshold(monkeypatch, fake, capsys, wrong, code):
    assert eval_chat.TOPIC_PASS_RATIO == 0.8
    monkeypatch.setattr(eval_chat, "TOPIC_CASES", FIVE)
    fake.answers = dict(ALL_RIGHT)
    for case in FIVE[:wrong]:
        fake.answers[case.message] = ["So sánh trường khác"]

    assert run(["topics"]) == code
    full = len(FIVE) - wrong
    assert f"đúng hoàn toàn {full}/5 ({full / 5:.0%})" in capsys.readouterr().out


def test_every_model_failing_is_inconclusive_not_wrong(monkeypatch, fake, capsys):
    monkeypatch.setattr(eval_chat, "TOPIC_CASES", FIVE)
    fake.fail = True

    assert run(["topics"]) == 2

    out = capsys.readouterr().out
    assert "INCONCLUSIVE" in out
    assert not [line for line in out.splitlines() if " | kỳ vọng " in line]
    assert "đúng hoàn toàn" not in out
    assert len(fake.calls) == 1  # dừng ở câu đầu tiên, không chấm tiếp


def test_no_argument_runs_scenarios_and_topic_set(monkeypatch, fake, capsys):
    monkeypatch.setattr(eval_chat, "TOPIC_CASES", FIVE)
    monkeypatch.setattr(eval_chat, "SCENARIOS", {"hoc_phi_tin_dau": eval_chat.SCENARIOS["hoc_phi_tin_dau"]})
    fake.answers = dict(ALL_RIGHT)

    code = run([])

    out = capsys.readouterr().out
    assert "===== hoc_phi_tin_dau =====" in out and "===== topics =====" in out
    assert "đúng hoàn toàn 5/5 (100%)" in out
    assert code == 0, out


def test_unknown_name_is_still_exit_2_and_topics_is_not_a_scenario(fake, capsys):
    assert eval_chat.TOPIC_SUITE == "topics" and eval_chat.TOPIC_SUITE not in eval_chat.SCENARIOS

    assert run(["topics", "khong_co"]) == 2

    assert "khong_co" in capsys.readouterr().out
    assert fake.calls == []


def test_topic_set_without_api_key_is_inconclusive(monkeypatch, capsys):
    monkeypatch.setattr(settings, "AI_MODEL_ORDER", ["openai"])
    monkeypatch.setitem(ai_engine.API_KEY_MAP, "openai", "")

    assert run(["topics"]) == 2
    assert "INCONCLUSIVE" in capsys.readouterr().out


def test_topic_set_covers_every_topic_and_the_hard_cases():
    cases = eval_chat.TOPIC_CASES
    assert 15 <= len(cases) <= 20
    assert all(set(c.expected) <= set(TOPICS) for c in cases), [c for c in cases if not set(c.expected) <= set(TOPICS)]
    # Thêm chủ đề vào TOPICS mà quên câu mẫu thì đỏ ở đây.
    assert set(TOPICS) - {t for c in cases for t in c.expected} == set()
    assert len({c.message for c in cases}) == len(cases)
    assert any(len(c.expected) >= 2 for c in cases)
    by_message = {c.message: c for c in cases}
    for message in ("hp bn ạ", "Chào trường ạ", "Cảm ơn ạ", "Dưới 2 tuổi"):
        assert message in by_message, message
    assert by_message["hp bn ạ"].expected == ("Học phí",)
    assert any("tiền học" in c.message and c.expected == ("Học phí",) for c in cases)
    empty = [c for c in cases if not c.expected]
    assert any(eval_chat.TEST_PHONE in c.message for c in empty)
    assert any("tuổi" in c.last_bot_message for c in empty if c.message == "Dưới 2 tuổi")
    assert any("buổi chiều" in c.message.lower() and c.last_bot_message for c in empty)
    assert {"Chào trường ạ", "Cảm ơn ạ"} <= {c.message for c in empty}
    assert sum(c.expected == ("Khác",) for c in cases) == 1

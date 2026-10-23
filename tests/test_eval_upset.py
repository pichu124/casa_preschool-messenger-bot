"""Bộ chấm cờ "upset" của scripts/eval_chat.py: model trích xuất chỉ bật cờ khi phụ huynh bực vì bị đòi số và muốn
nhận thông tin qua chat (mục 2g.2), không bật cho chê đắt, so sánh trường, lo lắng về bé. Chỉ dùng provider giả,
không mạng, không API key."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from app import ai_engine
from app.ai_engine import AIProvider
from app.config import settings

_spec = importlib.util.spec_from_file_location("eval_chat", Path(__file__).resolve().parent.parent / "scripts" / "eval_chat.py")
eval_chat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_chat)

EXTRACT_PROMPT_START = "Bạn là hệ thống trích xuất"
POSITIVES = [
    "sao cứ đòi số thế",
    "không cho số thì không tư vấn à, gửi qua đây đi",
    "hỏi mãi, gửi bảng giá qua đây luôn",
]


class FakeExtractor(AIProvider):
    """Trả {"upset": true} cho tin phụ huynh có trong `flagged`, {} cho tin khác."""

    def __init__(self):
        self.flagged: set[str] = set()
        self.fail = False
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024) -> str:
        self.calls.append((system_prompt, user_message))
        if self.fail:
            raise RuntimeError("401 sai key")
        message = user_message.split("Tin nhắn phụ huynh: ", 1)[1].split("\n", 1)[0]
        return json.dumps({"upset": True, "phone_declined": True}) if message in self.flagged else "{}"


@pytest.fixture
def fake(monkeypatch) -> FakeExtractor:
    provider = FakeExtractor()
    monkeypatch.setattr(settings, "AI_MODEL_ORDER", ["fake"])
    monkeypatch.setitem(ai_engine.PROVIDER_MAP, "fake", lambda: provider)
    monkeypatch.setitem(ai_engine.API_KEY_MAP, "fake", "key-gia")
    # AIEngine() tự đăng ký làm instance toàn cục; khôi phục sau test để không rò engine giả.
    monkeypatch.setattr(ai_engine, "ai_engine_instance", ai_engine.ai_engine_instance)
    return provider


def run(selected: list[str]) -> int:
    return asyncio.run(eval_chat.main(selected))


def result_lines(out: str) -> set[str]:
    return {line for line in out.splitlines() if " | kỳ vọng " in line}


def test_upset_set_is_the_three_angry_parents_and_five_that_need_advice():
    cases = eval_chat.UPSET_CASES
    assert [c.message for c in cases if c.upset] == POSITIVES
    negatives = [c.message for c in cases if not c.upset]
    assert len(negatives) == 5 and len(set(negatives)) == 5
    assert "học phí đắt quá, trường gần nhà rẻ hơn" in negatives  # ca CARE từng nhận câu xin lỗi
    assert "em chưa muốn để số ạ" in negatives
    assert any("khóc" in m for m in negatives)
    assert any("vinschool" in m.lower() for m in negatives)
    assert any("học phí" in m and "đắt" not in m for m in negatives)
    # Từ chối lịch sự ngay sau câu bot xin số, như process_message truyền last_bot_message
    polite = next(c for c in cases if c.message == "em chưa muốn để số ạ")
    assert "SĐT" in polite.last_bot_message


def test_upset_alone_runs_only_the_upset_set_and_grades_each_message(fake, capsys):
    fake.flagged = set(POSITIVES)

    code = run(["upset"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "===== upset =====" in out and "===== topics =====" not in out
    # Mỗi câu đúng 1 lượt gọi extract, cùng tham số như process_message (hồ sơ đã biết, câu bot hỏi trước đó).
    assert len(fake.calls) == len(eval_chat.UPSET_CASES)
    assert all(system.startswith(EXTRACT_PROMPT_START) for system, _ in fake.calls)
    polite_call = next(user for _, user in fake.calls if "em chưa muốn để số ạ" in user)
    assert "Câu bot vừa hỏi:" in polite_call and "Thông tin đã biết" in polite_call
    lines = result_lines(out)
    assert len(lines) == 8
    assert f"{eval_chat.FULL} | 'sao cứ đòi số thế' | kỳ vọng upset | ra upset" in lines
    assert f"{eval_chat.FULL} | 'học phí đắt quá, trường gần nhà rẻ hơn' | kỳ vọng không | ra không" in lines
    assert "câu dương bắt được 3/3 (cần ≥ 2/3), câu âm báo nhầm 0/5 (cần 0)" in out


def test_one_false_positive_fails_the_set(fake, capsys):
    fake.flagged = {*POSITIVES, "học phí đắt quá, trường gần nhà rẻ hơn"}

    assert run(["upset"]) == 1

    out = capsys.readouterr().out
    assert f"{eval_chat.WRONG} | 'học phí đắt quá, trường gần nhà rẻ hơn' | kỳ vọng không | ra upset" in result_lines(out)
    assert "câu âm báo nhầm 1/5" in out


@pytest.mark.parametrize(("missed", "code"), [(0, 0), (1, 0), (2, 1), (3, 1)])
def test_positives_pass_at_two_thirds(fake, capsys, missed, code):
    fake.flagged = set(POSITIVES[missed:])

    assert run(["upset"]) == code
    assert f"câu dương bắt được {3 - missed}/3" in capsys.readouterr().out


def test_flag_counts_only_as_json_true_like_the_bot(fake, monkeypatch, capsys):
    async def string_true(system_prompt, user_message, conversation_history, max_tokens=1024):
        return '{"upset": "true"}'

    monkeypatch.setattr(fake, "generate", string_true)

    assert run(["upset"]) == 1
    assert "câu dương bắt được 0/3" in capsys.readouterr().out


def test_every_model_failing_is_inconclusive_not_wrong(fake, capsys):
    fake.fail = True

    assert run(["upset"]) == 2

    out = capsys.readouterr().out
    assert "INCONCLUSIVE" in out
    assert result_lines(out) == set()
    assert len(fake.calls) == 1  # dừng ở câu đầu tiên


def test_unknown_name_is_still_exit_2_and_upset_is_not_a_scenario(fake, capsys):
    assert eval_chat.UPSET_SUITE == "upset" and eval_chat.UPSET_SUITE not in eval_chat.SCENARIOS

    assert run(["upset", "khong_co"]) == 2

    assert "khong_co" in capsys.readouterr().out
    assert fake.calls == []

"""Ma trận gửi ảnh (scripts/eval_media_cases.py, docs/ma-tran-gui-anh.md) và bộ eval `media` của scripts/eval_chat.py.

Mọi dòng ma trận phải có bộ kiểm: ca eval cùng mã, test pytest có thật, hoặc mã trong features/media.md của harness.
Các ca eval phải gặp đủ loại ảnh và đủ trạng thái dòng [HỆ THỐNG]. Bộ media chạy luồng thật của bot (process_message)
với model giả: model làm đúng luật thì đạt, model hứa suông, nêu số tiền, đẩy việc gửi ảnh cho tư vấn viên… thì vi
phạm. Không mạng, không API key, không đụng data/customers.json.
"""
import ast
import asyncio
import functools
import importlib.util
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

import app.main as main
from app import ai_engine, media
from app.ai_engine import IMAGE_TOPICS, AIProvider
from app.config import settings
from app.messenger import QUICK_REPLY_PREFIX, quick_reply_meaning

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("eval_chat", ROOT / "scripts" / "eval_chat.py")
eval_chat = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(eval_chat)
cases = eval_chat.media_cases

HARNESS_DOC = ROOT / ".claude" / "skills" / "verify-casa-bot" / "features" / "media.md"
MATRIX_DOC = ROOT / "docs" / "ma-tran-gui-anh.md"
CHECKERS = ("eval", "pytest", "harness")
EXTRACT_PROMPT_START = "Bạn là hệ thống trích xuất"
CODE = re.compile(r"`([A-Z]+(?:-[A-Z0-9]+)+)`")


@functools.cache
def collected_tests(path: str) -> frozenset[str]:
    """Tên các hàm test_* ở mức module của một file test: những gì pytest thu thập được từ file đó."""
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return frozenset(
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    )


def has_test(node_id: str) -> bool:
    path, _, name = node_id.partition("::")
    return path.startswith("tests/") and (ROOT / path).is_file() and name in collected_tests(path)


def uncovered(matrix: list, media_cases: dict, harness_doc: str) -> list[str]:
    """Dòng ma trận không có bộ kiểm, và ca eval không thuộc dòng eval nào."""
    problems = []
    for row in matrix:
        if row.checker not in CHECKERS:
            problems.append(f"{row.code}: bộ kiểm lạ {row.checker!r}")
        elif row.checker == "eval" and row.code not in media_cases:
            problems.append(f"{row.code}: không có ca eval cùng mã trong MEDIA_CASES")
        elif row.checker == "pytest" and not has_test(row.test):
            problems.append(f"{row.code}: không có test {row.test!r}")
        elif row.checker == "harness" and f"`{row.code}`" not in harness_doc:
            problems.append(f"{row.code}: không có trong features/media.md")
    eval_rows = {row.code for row in matrix if row.checker == "eval"}
    problems += [f"{code}: ca eval không có dòng ma trận eval" for code in media_cases if code not in eval_rows]
    return problems


# --- ma trận ---


def test_every_matrix_row_has_its_checker():
    assert uncovered(cases.MATRIX, cases.MEDIA_CASES, HARNESS_DOC.read_text(encoding="utf-8")) == []


def test_a_row_whose_checker_is_gone_is_reported():
    without_case = {code: case for code, case in cases.MEDIA_CASES.items() if code != "FEE-STALE"}
    pytest_row = next(row for row in cases.MATRIX if row.checker == "pytest")
    matrix = [replace(row, test=row.test + "_renamed") if row is pytest_row else row for row in cases.MATRIX]
    harness = HARNESS_DOC.read_text(encoding="utf-8").replace("`GEN-FAIL-HARNESS`", "")

    assert uncovered(matrix, without_case, harness) == [
        "FEE-STALE: không có ca eval cùng mã trong MEDIA_CASES",
        f"{pytest_row.code}: không có test {pytest_row.test + '_renamed'!r}",
        "GEN-FAIL-HARNESS: không có trong features/media.md",
    ]
    extra = {**cases.MEDIA_CASES, "FEE-NEW": cases.MEDIA_CASES["FEE-STALE"]}
    assert uncovered(cases.MATRIX, extra, HARNESS_DOC.read_text(encoding="utf-8")) == [
        "FEE-NEW: ca eval không có dòng ma trận eval"
    ]


def test_matrix_codes_are_unique_and_every_checker_is_used():
    codes = [row.code for row in cases.MATRIX]
    assert len(codes) == len(set(codes))
    assert {row.checker for row in cases.MATRIX} == set(CHECKERS)
    assert all(bool(row.test) == (row.checker == "pytest") for row in cases.MATRIX)


def test_the_doc_lists_every_matrix_row_with_its_checker():
    lines = MATRIX_DOC.read_text(encoding="utf-8").splitlines()
    for row in cases.MATRIX:
        line = next((line for line in lines if line.startswith(f"| `{row.code}` |")), "")
        checker = line.rstrip(" |").rsplit("|", 1)[-1].strip()
        assert checker == (f"pytest `{row.test.partition('::')[2]}`" if row.test else row.checker), (row.code, line)
    documented = {code for line in lines for code in CODE.findall(line)}
    assert documented == {row.code for row in cases.MATRIX}


def test_eval_cases_send_every_kind_of_image_and_tap_real_buttons():
    steps = [step for case in cases.MEDIA_CASES.values() for step in case.steps]
    assert {cases.image_kind(i) for step in steps for i in step.images} == set(media.KINDS)
    for step in steps:
        assert bool(step.say) != bool(step.tap), step
        assert not step.tap or quick_reply_meaning(f"{QUICK_REPLY_PREFIX}{step.tap}"), step.tap
        assert set(step.asks) | set(step.not_asks) <= set(eval_chat.ASKS_FOR), step


# --- bộ media với model giả ---


class FakeModel(AIProvider):
    """Trích xuất trả `step.extract` của lượt đang chạy; chat trả `chat(step, note)` (note: dòng [HỆ THỐNG])."""

    def __init__(self):
        self.step = None
        self.chat = lambda step, note: "Dạ vâng ạ."
        self.fail = False

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024) -> str:
        if self.fail:
            raise RuntimeError("401 sai key")
        if system_prompt.startswith(EXTRACT_PROMPT_START):
            return json.dumps(self.step.extract if self.step else {}, ensure_ascii=False)
        note = "\n".join(line for line in user_message.splitlines() if line.startswith("- [HỆ THỐNG]"))
        return self.chat(self.step, note)


@pytest.fixture
def fake(monkeypatch) -> FakeModel:
    model = FakeModel()
    monkeypatch.setattr(settings, "AI_MODEL_ORDER", ["fake"])
    monkeypatch.setitem(ai_engine.PROVIDER_MAP, "fake", lambda: model)
    monkeypatch.setitem(ai_engine.API_KEY_MAP, "fake", "key-gia")
    monkeypatch.setattr(main.ai_engine, "_providers", {})
    # eval_chat.main() dựng EvalEngine, tự đăng ký làm instance toàn cục: khôi phục sau test.
    monkeypatch.setattr(ai_engine, "ai_engine_instance", ai_engine.ai_engine_instance)
    return model


ASK = {"age": "Ba/Mẹ cho em xin tuổi bé ạ?", "campus": "Ba/Mẹ quan tâm cơ sở nào ạ?"}


def follows_the_rules(step, note: str) -> str:
    """Model làm đúng luật: [ESCALATE] khi phải chuyển; báo em gửi khi có ảnh, gắn [SEND:<loại>] đúng dòng "Nếu phụ
    huynh hỏi …" của ảnh đó, [IMAGES:] cho ảnh Q&A; hỏi đúng cái còn thiếu; nói các cụm ca đòi."""
    if step.escalate:
        return "[ESCALATE]"
    said = ["Dạ em gửi Ba/Mẹ ảnh để gia đình tham khảo ạ."] if step.images else []
    said += [f"Dạ {group[0]} ạ." for group in step.any_of]
    said += [ASK[what] for what in step.asks] or ["Không biết Ba/Mẹ có muốn ghé tham quan không ạ?"]
    kinds = sorted({cases.image_kind(i) for i in step.images})
    said += [f"[SEND:{k}]" for k in kinds if f"Nếu phụ huynh hỏi {IMAGE_TOPICS[k]}: sau câu trả lời" in note]
    if cases.QA_MENU_IMAGE in step.images:
        said.append(f"[IMAGES:{cases.QA_MENU_IMAGE}]")
    return " ".join(said)


def run(selected: list[str]) -> int:
    return asyncio.run(eval_chat.main(selected))


def test_media_suite_passes_a_model_that_follows_the_rules_and_meets_every_status_line(fake, monkeypatch, capsys):
    fake.chat = follows_the_rules
    real, seen = eval_chat.run_media_cases, []

    async def recorded():
        seen.append(await real(on_step=lambda code, step: setattr(fake, "step", step)))
        return seen[-1]

    monkeypatch.setattr(eval_chat, "run_media_cases", recorded)

    code = run(["media"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "✘" not in out
    media_run = seen[0]
    assert media_run.steps == sum(len(case.steps) for case in cases.MEDIA_CASES.values())
    # Mọi trạng thái dòng nhắc: chắc chắn gửi, "Nếu phụ huynh hỏi …", thiếu thông tin, đã gửi, hỏi cơ sở cho ảnh trường
    assert media_run.states == set(eval_chat.NOTE_STATES)
    assert "--- FEE-ASKED-READY ---" in out and "ảnh: qt-fee-10;" in out


@pytest.mark.parametrize(
    ("reply", "problem"),
    [
        ("Dạ em gửi Ba/Mẹ thời khoá biểu ngay bên dưới ạ.", "hứa gửi ảnh mà không có ảnh đi"),
        ("Dạ tư vấn viên sẽ gửi Ba/Mẹ thời khoá biểu qua Zalo ạ.", "nói tư vấn viên sẽ gửi ảnh"),
        ("Dạ học phí bên em là 4.500.000đ một tháng ạ.", "nêu số tiền"),
        ("Dạ vâng ạ.", "không hỏi campus"),
        ("Dạ em gửi ảnh ạ. [SEND:fee] [SEND:timetable] [SEND:facilities] [SEND:menu]", "ảnh đi ra"),
        ("[ESCALATE]", "mong đợi chuyển tư vấn viên=False"),
        ("Dạ bé nhà mình năm nay mấy tuổi ạ?", "hỏi lại age đã biết"),
        ("Dạ Ba/Mẹ cho em xin độ tuổi của bé ạ?", "hỏi lại age đã biết"),
        ("Dạ học phí tuỳ độ tuổi, Ba/Mẹ cho em xin tuổi bé ạ?", "hỏi lại age đã biết"),
        ("Dạ em gửi Ba/Mẹ ảnh trường ạ.", "hứa gửi ảnh mà không có ảnh đi"),
        ("Dạ em gửi Ba/Mẹ thông tin học phí ạ.", "hứa gửi ảnh mà không có ảnh đi"),
        # Review 2026-10-24: câu hứa không nêu ảnh ("tham khảo", "ngay", "gửi lại … khi hệ thống ổn") vẫn là hứa ảnh
        ("Dạ em gửi Ba/Mẹ tham khảo ạ.", "hứa gửi ảnh mà không có ảnh đi"),
        ("Dạ em gửi Ba/Mẹ ngay ạ.", "hứa gửi ảnh mà không có ảnh đi"),
        ("Em sẽ gửi lại Ba/Mẹ ngay khi hệ thống ổn ạ.", "hứa gửi ảnh mà không có ảnh đi"),
    ],
    ids=["promise", "consultant-sends", "money", "no-question", "every-token", "escalate", "asks-age", "asks-age-range",
         "asks-age-after-telling", "promises-photos", "promises-fee", "promises-for-reference", "promises-now",
         "promises-again-later"],
)
def test_media_suite_grades_a_model_breaking_a_rule_as_a_violation(fake, capsys, reply, problem):
    fake.chat = lambda step, note: reply

    code = run(["media"])

    out = capsys.readouterr().out
    assert code == 1, out
    assert f"✘ {problem}" in out, out


def with_steps(fake, monkeypatch) -> None:
    """The fake model knows the step being run (follows_the_rules needs it)."""
    real = eval_chat.run_media_cases
    monkeypatch.setattr(eval_chat, "run_media_cases", lambda: real(on_step=lambda code, step: setattr(fake, "step", step)))


TELLS_INFORMATION = "Dạ em gửi Ba/Mẹ thông tin về chương trình học ạ."


# Review 2026-10-24: bộ chấm báo sai câu đúng. "Học phí tuỳ độ tuổi và cơ sở, Ba/Mẹ quan tâm cơ sở nào ạ?" bị chấm hỏi
# lại tuổi đã biết (chỉ nhắc tới độ tuổi trong câu kể); "em gửi Ba/Mẹ thông tin …" ở lượt không ảnh bị chấm hứa gửi ảnh.
@pytest.mark.parametrize("right", ["campus-question-naming-the-age", "information-without-an-image"])
def test_media_suite_does_not_flag_right_sentences_that_only_look_like_a_broken_rule(fake, monkeypatch, capsys, right):
    with_steps(fake, monkeypatch)
    if right == "campus-question-naming-the-age":
        monkeypatch.setitem(ASK, "campus", "Học phí tuỳ độ tuổi và cơ sở, Ba/Mẹ quan tâm cơ sở nào ạ?")
        fake.chat = follows_the_rules
    else:
        def tells_information(step, note):
            told = "" if step.images or step.escalate else TELLS_INFORMATION + " "
            return told + follows_the_rules(step, note)

        fake.chat = tells_information

    code = run(["media"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "✘" not in out


def test_media_suite_without_an_api_key_is_inconclusive(capsys):
    assert run(["media"]) == 2
    assert "INCONCLUSIVE: chưa có API key AI" in capsys.readouterr().out


def test_media_suite_is_inconclusive_when_every_model_fails(fake, capsys):
    fake.fail = True

    assert run(["media"]) == 2
    assert eval_chat.ALL_MODELS_FAILED in capsys.readouterr().out


def test_media_suite_leaves_the_app_as_it_found_it(fake):
    send_message, catalog, profiles = main.send_message, media._catalog, main.customer_memory._customers
    # Another test's monkeypatch may leave a bound get_response on the instance: compare with before, not with none
    get_response = vars(main.ai_engine).get("get_response")

    run(["media"])

    assert main.send_message is send_message and media._catalog is catalog
    assert main.customer_memory._customers is profiles and profiles == {}
    assert settings.MEDIA_SYNC_ENABLED is False
    assert vars(main.ai_engine).get("get_response") is get_response

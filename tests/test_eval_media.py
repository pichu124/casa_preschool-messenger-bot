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
        assert set(step.expect) <= set(eval_chat.JUDGE_KEYS), step
        assert all(isinstance(want, bool) for want in step.expect.values()), step


# --- bộ media với model giả ---


ASK = {"age": "Ba/Mẹ cho em xin tuổi bé ạ?", "campus": "Ba/Mẹ quan tâm cơ sở nào ạ?"}
SENDS = "Dạ em gửi Ba/Mẹ ảnh để gia đình tham khảo ạ."
# Giám khảo giả: khoá nào true với câu nào của bot; câu bot không chứa câu nào của bảng thì mọi khoá false.
JUDGE_TABLE = {SENDS: {"promises_image"}, ASK["age"]: {"asks_age"}, ASK["campus"]: {"asks_campus"}}


def asked_of(message: str) -> tuple[str, list[str]]:
    """(câu trả lời của bot, các khoá được hỏi) trong tin gửi giám khảo."""
    reply = message.split("Câu trả lời của bot:\n", 1)[1].split("\n\nCâu hỏi: ", 1)[0]
    return reply, message.rsplit("Câu hỏi: ", 1)[1].splitlines()[0].split(", ")


def judge_by(table: dict[str, set[str]]):
    def judge(message: str) -> str:
        reply, keys = asked_of(message)
        true = {key for sentence, said in table.items() if sentence in reply for key in said}
        return json.dumps({**{key: key in true for key in keys}, "ly_do": "theo bảng của test"}, ensure_ascii=False)

    return judge


class FakeModel(AIProvider):
    """Trích xuất trả `step.extract` của lượt đang chạy; chat trả `chat(step, note)` (note: dòng [HỆ THỐNG]); giám khảo
    trả `judge(tin gửi giám khảo)`, mỗi tin ghi vào `judged`."""

    def __init__(self):
        self.step = None
        self.chat = lambda step, note: "Dạ vâng ạ."
        self.judge = judge_by(JUDGE_TABLE)
        self.judged: list[str] = []
        self.fail = False

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024) -> str:
        if self.fail:
            raise RuntimeError("401 sai key")
        if system_prompt.startswith(EXTRACT_PROMPT_START):
            return json.dumps(self.step.extract if self.step else {}, ensure_ascii=False)
        if system_prompt == eval_chat.JUDGE_PROMPT:
            self.judged.append(user_message)
            return self.judge(user_message)
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


def follows_the_rules(step, note: str) -> str:
    """Model làm đúng luật: [ESCALATE] khi phải chuyển; báo em gửi khi có ảnh, gắn [SEND:<loại>] đúng dòng "Nếu phụ
    huynh hỏi …" của ảnh đó, [IMAGES:] cho ảnh Q&A; hỏi đúng cái còn thiếu; nói các cụm ca đòi."""
    if step.escalate:
        return "[ESCALATE]"
    said = [SENDS] if step.images else []
    said += [f"Dạ {group[0]} ạ." for group in step.any_of]
    asks = [ASK[what] for what in ("age", "campus") if step.expect.get(f"asks_{what}")]
    said += asks or ["Không biết Ba/Mẹ có muốn ghé tham quan không ạ?"]
    kinds = sorted({cases.image_kind(i) for i in step.images})
    said += [f"[SEND:{k}]" for k in kinds if f"Nếu phụ huynh hỏi {IMAGE_TOPICS[k]}: sau câu trả lời" in note]
    if cases.QA_MENU_IMAGE in step.images:
        said.append(f"[IMAGES:{cases.QA_MENU_IMAGE}]")
    return " ".join(said)


def run(selected: list[str]) -> int:
    return asyncio.run(eval_chat.main(selected))


def with_steps(fake, monkeypatch) -> None:
    """The fake model knows the step being run (follows_the_rules needs it)."""
    real = eval_chat.run_media_cases
    monkeypatch.setattr(
        eval_chat, "run_media_cases", lambda engine: real(engine, on_step=lambda code, step: setattr(fake, "step", step))
    )


ESCALATED_STEPS = sum(step.escalate for case in cases.MEDIA_CASES.values() for step in case.steps)


def test_media_suite_passes_a_model_that_follows_the_rules_and_meets_every_status_line(fake, monkeypatch, capsys):
    fake.chat = follows_the_rules
    real, seen = eval_chat.run_media_cases, []

    async def recorded(engine):
        seen.append(await real(engine, on_step=lambda code, step: setattr(fake, "step", step)))
        return seen[-1]

    monkeypatch.setattr(eval_chat, "run_media_cases", recorded)

    code = run(["media"])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "✘" not in out and "  ? giám khảo" not in out
    media_run = seen[0]
    assert media_run.steps == sum(len(case.steps) for case in cases.MEDIA_CASES.values())
    # Mọi trạng thái dòng nhắc: chắc chắn gửi, "Nếu phụ huynh hỏi …", thiếu thông tin, đã gửi, hỏi cơ sở cho ảnh trường
    assert media_run.states == set(eval_chat.NOTE_STATES)
    assert "--- FEE-ASKED-READY ---" in out and "ảnh: qt-fee-10;" in out
    # Một lời gọi giám khảo mỗi lượt không chuyển tư vấn viên; mỗi lượt in phán quyết và lý do.
    assert len(fake.judged) == media_run.steps - ESCALATED_STEPS == 45
    assert out.count("  giám khảo (fake): ") == 45 and "lý do: theo bảng của test" in out


def test_the_judge_reads_the_parent_message_the_images_that_went_and_the_reply_with_the_keys_of_the_turn(
    fake, monkeypatch
):
    with_steps(fake, monkeypatch)
    fake.chat = follows_the_rules

    assert run(["media"]) == 0

    fee_asked = "Tin phụ huynh: học phí bên mình thế nào em\nẢnh đi kèm: học phí (qt-fee-10)\n"
    fee = [m for m in fake.judged if m.startswith(fee_asked)]
    assert len(fee) == 1  # FEE-ASKED-READY (FEE-STALE cùng câu nhưng ảnh qt-fee-9)
    assert asked_of(fee[0]) == (
        f"{SENDS} Dạ gửi ạ. Không biết Ba/Mẹ có muốn ghé tham quan không ạ?",
        ["consultant_sends_image", "says_cannot_send"],
    )
    wait_age = [m for m in fake.judged if m.startswith("Tin phụ huynh: cho em hỏi học phí ạ\nẢnh đi kèm: không có\n")]
    assert [asked_of(m)[1] for m in wait_age] == [["consultant_sends_image", "promises_image", "asks_age", "asks_campus"]]
    assert not any("lịch học hè" in m for m in fake.judged)  # lượt chuyển tư vấn viên: câu cố định của code


# Review 2026-10-24: các câu đúng theo prompt bị regex chấm "hứa gửi ảnh" ở lượt không ảnh, vòng trước câu hứa suông
# "Dạ em gửi Ba/Mẹ tham khảo ạ." thì lọt. Giờ phán quyết giám khảo quyết định.
@pytest.mark.parametrize(
    ("sentence", "judged", "code"),
    [
        ("Dạ em gửi Ba/Mẹ tham khảo ạ.", {"promises_image"}, 1),
        ("Dạ em gửi Ba/Mẹ một số thông tin về xe đưa đón ạ.", set(), 0),
        ("Dạ em gửi Ba/Mẹ lịch tham quan ạ.", set(), 0),
    ],
    ids=["empty-promise", "information", "visit-schedule"],
)
def test_a_sentence_at_turns_without_images_is_graded_by_the_judges_verdict(
    fake, monkeypatch, capsys, sentence, judged, code
):
    with_steps(fake, monkeypatch)
    fake.chat = lambda step, note: ("" if step.images or step.escalate else f"{sentence} ") + follows_the_rules(step, note)
    fake.judge = judge_by({**JUDGE_TABLE, sentence: judged})

    assert run(["media"]) == code

    out = capsys.readouterr().out
    assert ("✘ hứa gửi ảnh mà không có ảnh đi" in out) == bool(code), out
    assert out.count("✘") == (out.count("✘ hứa gửi ảnh mà không có ảnh đi") if code else 0)


@pytest.mark.parametrize(
    ("reply", "judged", "problem"),
    [
        # luật câu chữ: giám khảo
        ("Dạ em gửi Ba/Mẹ thời khoá biểu ngay bên dưới ạ.", {"promises_image"}, "hứa gửi ảnh mà không có ảnh đi"),
        ("Dạ tư vấn viên sẽ gửi Ba/Mẹ thời khoá biểu qua Zalo ạ.", {"consultant_sends_image"}, "nói tư vấn viên sẽ gửi ảnh"),
        ("Dạ em không gửi được bảng phí qua chat ạ.", {"says_cannot_send"}, "nói không gửi được ảnh trong chat"),
        ("Dạ bé nhà mình năm nay mấy tuổi ạ?", {"asks_age"}, "hỏi lại tuổi bé đã biết"),
        ("Dạ vâng ạ.", set(), "không hỏi cơ sở"),
        # luật code
        ("Dạ học phí bên em là 4.500.000đ một tháng ạ.", set(), "nêu số tiền"),
        ("Dạ em gửi ảnh ạ. [SEND:fee] [SEND:timetable] [SEND:facilities] [SEND:menu]", set(), "ảnh đi ra"),
        ("[ESCALATE]", set(), "mong đợi chuyển tư vấn viên=False"),
        ("Dạ em gửi Ba/Mẹ ảnh ạ. [SEND fee]", set(), "token lộ ra tin phụ huynh"),
    ],
    ids=["promise", "consultant-sends", "cannot-send", "asks-age", "no-question", "money", "every-token", "escalate",
         "leaked-token"],
)
def test_media_suite_grades_a_model_breaking_a_rule_as_a_violation(fake, capsys, reply, judged, problem):
    fake.chat = lambda step, note: reply
    fake.judge = judge_by({reply: judged})

    code = run(["media"])

    out = capsys.readouterr().out
    assert code == 1, out
    assert f"✘ {problem}" in out, out
    assert not any(eval_chat.LEAKED_TOKEN.search(m) for m in fake.judged)


@pytest.mark.parametrize(
    "answer",
    ["Dạ câu này không hứa gửi ảnh ạ.", '{"promises_image": "không", "ly_do": "x"}', '{"ly_do": "thiếu khoá"}', "[]",
     "raise"],
    ids=["prose", "not-a-bool", "missing-keys", "not-an-object", "judge-fails"],
)
def test_a_judge_without_a_proper_verdict_leaves_the_turns_inconclusive(fake, monkeypatch, capsys, answer):
    with_steps(fake, monkeypatch)
    fake.chat = follows_the_rules

    def judge(message):
        if answer == "raise":
            raise RuntimeError("giám khảo hết quota")
        return answer

    fake.judge = judge

    assert run(["media"]) == 2

    out = capsys.readouterr().out
    assert "✘" not in out
    assert out.count("  ? giám khảo (") == 45
    assert "INCONCLUSIVE: giám khảo không ra phán quyết ở 45 lượt của bộ media" in out
    assert "Ảnh: 3/48 lượt đạt, 45 lượt chưa kết luận" in out


def test_a_violation_found_by_code_counts_even_when_the_judge_has_no_verdict(fake, capsys):
    fake.chat = lambda step, note: "Dạ học phí bên em là 4.500.000đ một tháng ạ."
    fake.judge = lambda message: "không phải JSON"

    assert run(["media"]) == 1
    assert "✘ nêu số tiền" in capsys.readouterr().out


def test_a_verdict_is_a_json_object_of_exactly_the_keys_asked():
    keys = ["promises_image", "asks_age"]
    verdict = {"promises_image": False, "asks_age": True, "ly_do": "hỏi năm sinh của bé"}
    said = json.dumps(verdict, ensure_ascii=False)

    assert eval_chat.parse_verdict(said, keys) == verdict
    assert eval_chat.parse_verdict(f"```json\n{said}\n```", keys) == verdict
    for wrong in [
        f"Phán quyết: {said}",
        json.dumps({**verdict, "asks_campus": False}),
        json.dumps({"promises_image": False, "ly_do": "x"}),
        json.dumps({**verdict, "asks_age": "true"}),
        json.dumps({**verdict, "ly_do": None}),
    ]:
        assert eval_chat.parse_verdict(wrong, keys) is None, wrong


# Câu đúng theo prompt mà regex từng chấm "hứa gửi ảnh" ở lượt không ảnh (review 2026-10-24).
RIGHT_WITHOUT_IMAGES = (
    "Nếu tiện, Ba/Mẹ để lại SĐT/Zalo để tư vấn viên gửi Ba/Mẹ bảng phí xe đưa đón ạ.",
    "Dạ em gửi Ba/Mẹ một số thông tin về xe đưa đón ạ.",
    "Dạ em gửi Ba/Mẹ lịch tham quan ạ.",
)


def test_the_judge_prompt_describes_every_key_and_shows_the_edge_cases_of_the_reviews():
    prompt = eval_chat.JUDGE_PROMPT
    keys = eval_chat.JUDGE_KEYS
    assert set(keys) == {"promises_image", "asks_age", "asks_campus", "consultant_sends_image", "says_cannot_send"}
    for key, judge_key in keys.items():
        assert f"- {key}: {judge_key.question}\n" in prompt
    assert all(w in keys["promises_image"].question for w in ("ẢNH", "ngay trong chat", "Zalo", '"thông tin" bằng chữ'))
    assert all("HỎI" in keys[key].question and "câu kể" in keys[key].question for key in ("asks_age", "asks_campus"))
    assert "năm sinh" in keys["asks_age"].question
    assert "tư vấn viên sẽ gửi" in keys["consultant_sends_image"].question
    assert "không gửi được" in keys["says_cannot_send"].question
    assert '"ly_do"' in prompt and "true/false" in prompt

    examples = {reply: verdict for _, reply, verdict in eval_chat.JUDGE_EXAMPLES}
    assert 6 <= len(eval_chat.JUDGE_EXAMPLES) <= 8
    assert examples["Dạ em gửi Ba/Mẹ tham khảo ạ."] == {"promises_image": True}
    assert all(examples[right]["promises_image"] is False for right in RIGHT_WITHOUT_IMAGES)
    assert examples["Học phí tuỳ độ tuổi và cơ sở, Ba/Mẹ quan tâm cơ sở nào ạ?"] == {"asks_campus": True, "asks_age": False}
    assert examples["Bé nhà mình sinh năm bao nhiêu ạ"] == {"asks_age": True}
    for images, reply, verdict in eval_chat.JUDGE_EXAMPLES:
        assert set(verdict) <= set(keys)
        said = ", ".join(f"{key}: {str(want).lower()}" for key, want in verdict.items())
        assert f'- Ảnh đi kèm: {images}. Bot: "{reply}" → {said}\n' in prompt


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


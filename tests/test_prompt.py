"""Prompt tư vấn và lọc khối suy luận <think>: chỉ dùng provider giả, không mạng, không API key."""
import asyncio
import importlib.util
import json
import re
from pathlib import Path

import pytest

from app import ai_engine
from app.ai_engine import SYSTEM_PROMPT, AIEngine, AIProvider, ImageNote, media_note, strip_reasoning
from app.config import settings
from app.messenger import QUICK_REPLIES


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


# Phụ huynh quan tâm "Chùa Láng và Kim Mã": hồ sơ giữ đủ cả hai để bot gửi thời khoá biểu từng cơ sở.
def test_extract_prompt_keeps_every_campus_the_parent_names(monkeypatch):
    recorder = RecordingProvider("{}")
    engine = make_engine(monkeypatch, fake=recorder)

    asyncio.run(engine.extract_customer_info("Chùa Láng và Kim Mã"))

    line = next(line for line in recorder.system_prompt.splitlines() if line.startswith('- "interested_campus"'))
    assert "nhiều cơ sở" in line and '"Chùa Láng, Kim Mã"' in line, line


# Lead khi phụ huynh đồng ý chỉ có nếu extract ghi visit_request. Prompt cũ chỉ cho ghi lịch "ĐÃ CHỐT" nên bấm
# "Đăng ký học thử" rồi rời đi (chưa chọn tuần) thì Telegram/Sheet không nhận gì.
AGREE_TO_BOOK = [
    (QUICK_REPLIES["trial_invite"][0][1], "học thử 1 tuần"),
    (QUICK_REPLIES["visit_invite"][0][1], "tham quan trường"),
    (QUICK_REPLIES["topics"][2][1], "tham quan trường"),
]


@pytest.mark.parametrize(("agree", "value"), AGREE_TO_BOOK, ids=["trial_invite", "visit_invite", "topics"])
def test_extract_prompt_records_agreement_before_a_time_is_chosen(monkeypatch, agree, value):
    recorder = RecordingProvider("{}")
    engine = make_engine(monkeypatch, fake=recorder)

    asyncio.run(engine.extract_customer_info(agree, {}, last_bot_message="Không biết Ba/Mẹ có muốn cho bé thử không ạ?"))

    assert agree in recorder.user_message
    rule = next(line for line in recorder.system_prompt.splitlines() if '"visit_request"' in line)
    assert "ĐÃ CHỐT" not in rule
    assert re.search(r"ĐỒNG Ý[^\n]*chưa chọn buổi/tuần", rule), rule
    assert value in agree and f'"{value}"' in rule
    assert re.search(r"chọn buổi/tuần[^\n]*cụ thể hơn", rule), rule
    # Chỉ hỏi, còn cân nhắc hay bấm "Tìm hiểu thêm" thì vẫn chưa phải lead.
    refuse = rule.split("KHÔNG ghi", 1)[1]
    assert "hỏi" in refuse and "cân nhắc" in refuse
    assert "tìm hiểu thêm" in refuse.lower()


# Phụ huynh đã hẹn "tham quan buổi sáng" bấm lại "Đặt lịch tham quan": ghi "tham quan trường" thì hồ sơ/Sheet lùi
# về bản chung chung và Telegram nhận một lead thừa.
def test_extract_prompt_keeps_a_specific_booking_over_a_vaguer_one(monkeypatch):
    recorder = RecordingProvider("{}")
    engine = make_engine(monkeypatch, fake=recorder)
    agree = QUICK_REPLIES["visit_invite"][0][1]

    asyncio.run(engine.extract_customer_info(agree, {"visit_request": "tham quan buổi sáng"}))

    assert "tham quan buổi sáng" in recorder.user_message
    rule = next(line for line in recorder.system_prompt.splitlines() if '"visit_request"' in line)
    assert re.search(r"Thông tin đã biết[^\n]*cụ thể hơn \(buổi/tuần\)[^\n]*KHÔNG ghi lại bản chung chung hơn", rule), rule


def test_extract_prompt_asks_for_topics_of_this_message_from_the_fixed_list(monkeypatch):
    from app.topics import TOPICS

    recorder = RecordingProvider('{"topics": ["Học phí", "Xe đưa đón"], "kid_age": "3 tuổi"}')
    engine = make_engine(monkeypatch, fake=recorder)

    info = asyncio.run(engine.extract_customer_info("Bé 3 tuổi, học phí và xe đưa đón thế nào ạ?"))

    assert info == {"topics": ["Học phí", "Xe đưa đón"], "kid_age": "3 tuổi"}
    rule = next(line for line in recorder.system_prompt.splitlines() if '"topics"' in line)
    for topic in TOPICS:
        assert f'"{topic}"' in rule, topic
    assert "TIN NÀY" in rule
    # Tin chỉ trả lời hồ sơ (SĐT, tuổi bé, bấm chọn buổi/cơ sở) không phải câu hỏi về chủ đề nào
    assert re.search(r"SĐT[^\n]*tuổi bé[^\n]*buổi[^\n]*cơ sở[^\n]*\"topics\": \[\]", rule), rule


# Phản hồi của trường (đợt 7): phụ huynh khó chịu, gay gắt đòi thông tin qua chat thì chuyển tư vấn viên kèm lời xin
# lỗi. Model chat có trần ký tự; model trích xuất nhận diện việc này và trả cờ "upset" (không phải trường hồ sơ).
def test_extract_prompt_flags_an_upset_parent(monkeypatch):
    recorder = RecordingProvider('{"upset": true, "phone_declined": true}')
    engine = make_engine(monkeypatch, fake=recorder)

    info = asyncio.run(engine.extract_customer_info("sao cứ đòi số thế, gửi qua đây luôn đi"))

    assert info == {"upset": True, "phone_declined": True}
    (rule,) = [line for line in recorder.system_prompt.splitlines() if '"upset"' in line]
    # Cả ba điều kiện cùng lúc, đúng ý trường (mục 2g.2): khi cờ bật, main gửi câu xin lỗi thay mọi câu của model.
    assert re.search(r'"upset": true CHỈ khi[^\n]*không muốn để[^\n]*qua chat[^\n]*VÀ[^\n]*khó chịu', rule), rule
    # Ca CARE (chê đắt, so sánh trường) và lo lắng thường thì bot phải tự tư vấn, không xin lỗi rồi chuyển.
    not_upset = rule.split("KHÔNG tính", 1)[1]
    for case in ("chê đắt", "so sánh", "khóc", "ăn", "an toàn", "hỏi lại", "lịch sự"):
        assert case in not_upset, case
    assert "phàn nàn" not in rule
    assert "upset" not in ai_engine.PROFILE_FIELDS


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
    # Người vận hành 2026-10-23: bot gửi ảnh học phí từ Drive của trường (dòng [HỆ THỐNG]).
    "gửi bảng phí trên chat",
    "gửi bảng học phí trên chat",
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


# Production 2026-10-22: máy chủ khởi động lại nạp hồ sơ cũ (GapHours 4609.8, lịch sử 3 tin), phụ huynh hỏi "tôi muốn
# tìm hiểu thông tin về trường" và DeepSeek trả [ESCALATE] vì dòng "Không chắc → [ESCALATE]" không kèm điều kiện.
# Quyết định: câu hỏi chung về trường luôn tự trả lời; "không chắc" chỉ áp cho một dữ kiện cụ thể không có trong Q&A.
GENERAL_QUESTION = "tôi muốn tìm hiểu thông tin về trường"
OLD_HISTORY = [
    {"role": "user", "content": "chào em"},
    {"role": "user", "content": "cho mình hỏi học phí"},
    {"role": "assistant", "content": "Dạ Casa chào Ba/Mẹ ạ. Bé nhà mình được bao nhiêu tháng rồi ạ?"},
]
RETURNING_LONG_AGO = {
    "conversation_history": OLD_HISTORY,
    "customer_context": "[THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT]:\n[TRẠNG THÁI TƯ VẤN]:\n- Giai đoạn: Mới\n- Còn thiếu: tuổi bé, cơ sở/khu vực, SĐT/Zalo",
    "gap_hours": 4609.8,
}
ANSWER_GENERAL = re.compile(r"câu hỏi chung về trường[^\n]*LUÔN tự trả lời[^\n]*kể cả khách cũ[^\n]*tuổi bé/cơ sở", re.I)


@pytest.mark.parametrize(
    "kwargs", [RETURNING_LONG_AGO, {}, {"conversation_history": OLD_HISTORY}], ids=["khach-cu-6-thang", "tin-dau", "tin-tiep"]
)
def test_general_question_about_the_school_is_answered_not_escalated(monkeypatch, kwargs):
    system_prompt, user_message = model_input(monkeypatch, GENERAL_QUESTION, **kwargs)
    if kwargs is RETURNING_LONG_AGO:
        assert "phụ huynh CŨ quay lại sau khoảng 6 tháng" in user_message
    section = system_prompt.split('KHI NÀO TRẢ LỜI ĐÚNG CHUỖI "[ESCALATE]"', 1)[1].split("KÈM HÌNH ẢNH", 1)[0]
    reminder = [line for line in user_message.splitlines() if "BẮT BUỘC trả lời chính xác chuỗi [ESCALATE]" in line]

    assert len(reminder) == 1
    for text in [section] + reminder:
        assert ANSWER_GENERAL.search(text), text
    uncertain = [line for line in section.splitlines() if "không chắc" in line.lower()]
    assert uncertain and all("dữ kiện cụ thể" in line for line in uncertain), uncertain
    # Các ca chuyển người khác giữ nguyên (ca từ chối số mà đòi học phí bỏ từ 2026-10-23, xem test bên dưới).
    assert "ngoài lề" in section
    assert re.search(r"dữ kiện cụ thể[^\n]*không có trong Q&A", section, re.I), section


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

QUICK_KEYS = {"topics", "age", "campus", "phone", "trial_invite", "visit_invite", "visit_time", "trial_week"}


@pytest.mark.parametrize("phrase", REQUIRED_KNOWLEDGE + [f"[QUICK:{key}]" for key in sorted(QUICK_KEYS)])
def test_system_prompt_carries_required_knowledge(monkeypatch, phrase):
    system_prompt, _ = model_input(monkeypatch, "trường ở đâu")

    assert phrase in system_prompt


def test_system_prompt_only_teaches_known_quick_reply_keys():
    assert set(re.findall(r"\[QUICK:([^\]]*)\]", SYSTEM_PROMPT)) == QUICK_KEYS


# Người vận hành 2026-10-23 (docs/kiem-ke-du-kien.md): dữ kiện chi tiết chỉ nằm ở Q&A, để trường sửa thông tin một
# chỗ; prompt chỉ giữ tóm tắt những điều không được sai, và tóm tắt đó phải khớp Q&A.
QA_DB = Path(__file__).resolve().parent.parent / "data" / "qa_database.json"
QA_PAIRS = json.loads(QA_DB.read_text(encoding="utf-8"))["qa_pairs"]
QA_ANSWERS = "\n".join(p["answer"] for p in QA_PAIRS)
CORE = SYSTEM_PROMPT.split("THÔNG TIN CỐT LÕI", 1)[1].split("\nCÁCH TƯ VẤN", 1)[0]
MOVED_TO_QA = ["185 Huỳnh Thúc Kháng", "36 Phạm Hùng", "294 Kim Mã", "Hongkong Tower", "05/09", "17h30", "8h30–17h00"]


def _qa_answer(question: str) -> str:
    return next(p["answer"] for p in QA_PAIRS if question in p["questions"])


@pytest.mark.parametrize("fact", MOVED_TO_QA)
def test_detailed_facts_reach_the_model_from_qa_only(fact):
    from app.qa_database import QADatabase

    assert fact not in SYSTEM_PROMPT
    assert fact in SYSTEM_PROMPT.format(qa_context=QADatabase(str(QA_DB)).build_context())


def _campus_systems(text: str) -> dict[str, str]:
    return {campus: system.lower() for system, campus in re.findall(r"[Hh]ệ (Quốc tế|Song ngữ) (Chùa Láng|Mỹ Đình|Kim Mã)", text)}


def test_campuses_and_systems_in_the_prompt_match_qa():
    qa = _campus_systems(_qa_answer("Địa chỉ trường ở đâu?"))
    assert len(qa) == 3, qa
    assert "3 cơ sở" in CORE and _campus_systems(CORE) == qa, CORE
    assert {title for title, _ in QUICK_REPLIES["campus"]} == set(qa)


def test_admission_age_in_the_prompt_matches_qa():
    youngest = re.search(r"nhận bé từ (\d+) tháng", _qa_answer("Trường nhận bé từ bao nhiêu tháng tuổi?")).group(1)
    oldest = re.search(r"từ \d+ tháng \(đã đi vững\) đến (\d+) tuổi", _qa_answer("Trường mình dạy những độ tuổi nào?")).group(1)
    assert re.search(rf"Nhận bé từ {youngest} tháng \(đã đi vững\) đến {oldest} tuổi", CORE), CORE
    assert f"có con {youngest} tháng–{oldest} tuổi" in SYSTEM_PROMPT.split("\n", 1)[0]
    # Mọi chỗ prompt nói tuổi nhận (luật bé dưới 15 tháng, câu ví dụ) dùng cùng một con số.
    assert set(re.findall(r"(?:nhận|dưới) (?:bé )?(?:từ )?(\d+) tháng", SYSTEM_PROMPT, re.I)) == {youngest}


def test_free_trial_length_in_prompt_and_buttons_matches_qa(monkeypatch):
    weeks = re.search(r"(\d+) tuần học thử hoàn toàn miễn phí", _qa_answer("Có cho con học thử được không ạ?")).group(1)
    assert f"{weeks} tuần học thử miễn phí" in CORE, CORE
    buttons = [meaning for _, meaning in QUICK_REPLIES["trial_invite"]]
    for text in [SYSTEM_PROMPT, *_reminders(monkeypatch), *buttons]:
        assert set(re.findall(r"(\d+) tuần học thử|học thử (\d+) tuần", text)) <= {(weeks, ""), ("", weeks)}, text


def test_working_days_in_the_prompt_match_qa(monkeypatch):
    weekend = _qa_answer("Thứ 7, Chủ nhật có tham quan trường được không?")
    for text in [SYSTEM_PROMPT] + _reminders(monkeypatch):
        days = re.findall(r"thứ (\d)–(\d)", text)
        assert days and all(f"từ thứ {first} đến thứ {last}" in weekend for first, last in days), (days, weekend)


# Giờ hay ngày còn trong prompt (hoặc ai đó thêm lại) phải đúng con số của Q&A.
CLOCK_OR_DATE = re.compile(r"\b\d{1,2}h\d{0,2}\b|\b\d{1,2}:\d{2}\b|\b\d{1,2}/\d{1,2}\b")


def test_times_and_dates_left_in_the_prompt_are_the_qa_ones(monkeypatch):
    for text in [SYSTEM_PROMPT] + _reminders(monkeypatch):
        for token in CLOCK_OR_DATE.findall(text):
            assert token in QA_ANSWERS, token


def test_prompt_never_puts_kim_ma_with_the_full_cambridge_programme():
    # Phản hồi đợt 4 (G2), 5 (D2), 6: hệ Quốc tế học đủ English, Mathematics, Let's Explore; Kim Mã học môn English,
    # còn lại theo 5 lĩnh vực Montessori. Từ đợt 7 chi tiết theo hệ nằm ở Q&A (tests/test_knowledge.py); prompt vẫn
    # không được ghép Kim Mã với môn của hệ Quốc tế hay nói Kim Mã chỉ học English.
    assert "Understanding the World" not in SYSTEM_PROMPT
    assert "Kim Mã chỉ học" not in SYSTEM_PROMPT and "toán…" not in SYSTEM_PROMPT
    for clause in re.split(r"[.;\n]", SYSTEM_PROMPT):
        if "Kim Mã" in clause or "Song ngữ" in clause:
            assert "Mathematics" not in clause and "Let's Explore" not in clause, clause


# Phản hồi của trường (đợt 7): câu nhóm 3–6 tuổi từng kể chi tiết từng hệ ("hệ Quốc tế học trọn English –
# Mathematics – Let's Explore, còn Kim Mã học môn English") khi phụ huynh chưa nói cơ sở. Trường muốn câu chung, rồi
# hỏi cơ sở; chi tiết theo hệ chỉ khi đã biết cơ sở.
def test_3_to_6_programme_is_told_in_general_until_the_campus_is_known(monkeypatch):
    (line,) = [line for line in SYSTEM_PROMPT.splitlines() if line.strip().startswith("- 3–6 tuổi")]
    assert "Cambridge Early Years kết hợp Montessori" in line, line
    assert "thời lượng Cambridge theo từng chương trình/cơ sở" in line, line
    assert re.search(r"Chưa biết cơ sở[^\n]*nói chung[^\n]*hỏi cơ sở[^\n]*biết rồi mới nói chi tiết", line), line
    for detail in ("Mathematics", "Let's Explore", "Kim Mã", "Quốc tế", "Song ngữ"):
        assert detail not in line, line
    for reminder in _reminders(monkeypatch):
        (rule,) = [r for r in reminder.splitlines() if "khác biệt giữa các hệ/cơ sở" in r]
        assert re.search(r"Chưa biết cơ sở[^\n]*không tự kể khác biệt[^\n]*nói chung rồi hỏi cơ sở", rule), rule
    # Ví dụ trả lời theo hệ thì đã biết cơ sở.
    (english,) = [(parent, reply) for parent, reply in _examples() if "tieng anh" in parent]
    assert "Mỹ Đình" in english[0] and "Kim Mã" not in english[1], english


# Phản hồi của trường (đợt 7): trường làm việc thứ 2–6, cuối tuần phải sắp xếp riêng một cô. Bot từng trả lời "Em báo
# tư vấn viên xếp mẹ ghé thứ 7 ạ…". Khéo mời qua giờ hành chính thứ 2–6, không bao giờ hứa cuối tuần; phụ huynh không
# sắp xếp được thì báo tư vấn viên sắp xếp và liên hệ xác nhận, xin SĐT nếu chưa có.
WEEKEND = re.compile(
    r"thứ 2–6[^\n]*thứ 7/Chủ nhật[^\n]*KHÔNG hứa[^\n]*giờ hành chính thứ 2–6[^\n]*tư vấn viên[^\n]*sắp xếp[^\n]*xác nhận"
)


def test_weekend_visit_is_never_promised_and_weekdays_are_offered(monkeypatch):
    assert WEEKEND.search(SYSTEM_PROMPT)
    for reminder in _reminders(monkeypatch):
        (line,) = [line for line in reminder.splitlines() if "thứ 7/Chủ nhật" in line]
        assert WEEKEND.search(line), line
        assert re.search(r"chưa có SĐT[^\n]*xin SĐT/Zalo", line), line


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


def test_reminder_lets_booked_visit_without_phone_ask_for_phone_once(monkeypatch):
    # "Đã hẹn" không cần bước tiếp theo, trừ chỉ dẫn xin SĐT mềm 1 lần mà dòng trạng thái thêm khi chưa có số.
    for reminder in _reminders(monkeypatch):
        booked = next(line for line in reminder.splitlines() if "'Đã hẹn'" in line)
        assert "không cần bước tiếp theo" in booked, booked
        assert re.search(r"chưa có SĐT[^\n]*xin SĐT/Zalo mềm 1 lần[^\n]*không xin lại", booked), booked


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


def test_bot_never_calls_itself_or_the_parent_by_banned_pronouns(monkeypatch):
    # 1a087ea rút gọn prompt và rơi mất "chúng tôi": model trả "Hiện chúng tôi có 3 cơ sở…".
    for text in [SYSTEM_PROMPT] + _reminders(monkeypatch):
        clause = re.search(r"Không dùng (.*?)\.\s", text)
        assert clause, text
        banned = {word.strip() for word in re.split(r"[\"'/,]", clause.group(1)) if word.strip()}
        assert {"bạn", "quý khách", "tôi", "chúng tôi"} <= banned, clause.group(0)


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


# Thử DeepSeek thật 2026-10-22 (lần 2): phụ huynh hỏi "sáng mai được không", bot chép giọng ví dụ "Dạ được ạ…" và hứa luôn
# là được, dù chỉ tư vấn viên biết lịch trống; nhận yêu cầu, tư vấn viên gọi xác nhận giờ.
def test_bot_never_promises_a_visit_slot_only_the_consultant_confirms(monkeypatch):
    booked = next(line for line in SYSTEM_PROMPT.splitlines() if '"Đã hẹn: …"' in line)
    assert "không tự hứa" in booked, booked
    assert all("không tự hứa" in r for r in _reminders(monkeypatch))
    parent, reply = _examples()[-1]
    assert "sang mai duoc khong" in parent
    assert "được ạ" not in reply, reply
    assert "xác nhận" in reply, reply


# Người vận hành 2026-10-22: "…học thử 1 tuần miễn phí…, tuần này hay tuần sau ạ?" cụt và ép buộc. Lời mời học
# thử/tham quan là câu hỏi ý mềm kèm nút Đăng ký học thử / Đặt lịch tham quan – Tìm hiểu thêm; phụ huynh đồng ý rồi
# bot mới hỏi tuần (Tuần này/Tuần sau) hay buổi (Buổi sáng/Buổi chiều).
FORCED_CHOICE = re.compile(r"tuần này hay tuần sau|sáng hay (?:buổi )?chiều", re.I)
AGREES = tuple(QUICK_REPLIES[key][0][1] for key in ("trial_invite", "visit_invite"))
ASKS_TIME = ("[QUICK:trial_week]", "[QUICK:visit_time]")


def _next_step_rules(monkeypatch) -> list[str]:
    """Nguyên tắc 6 của prompt cộng dòng bước tiếp theo trong mỗi khối nhắc nhở."""
    rule6 = next(line for line in SYSTEM_PROMPT.splitlines() if line.startswith("6. "))
    reminders = [line for r in _reminders(monkeypatch) for line in r.splitlines() if "bước tiếp theo cụ thể" in line]
    assert len(reminders) == 3
    return [rule6] + reminders


def test_invitation_is_a_soft_question_and_the_time_is_asked_only_after_the_parent_agrees(monkeypatch):
    for rule in _next_step_rules(monkeypatch):
        assert "không biết Ba/Mẹ có muốn" in rule, rule
        assert "không thúc ép" in rule, rule
        assert re.search(r"\[QUICK:trial_invite\][^\n]*\[QUICK:visit_invite\]", rule), rule
        assert re.search(r"đồng ý[^\n]*mới hỏi[^\n]*\[QUICK:trial_week\][^\n]*\[QUICK:visit_time\]", rule), rule
        assert re.search(r"tìm hiểu thêm[^\n]*chưa mời lại", rule, re.I), rule
    instructions = SYSTEM_PROMPT.split("\nVÍ DỤ", 1)[0]
    for text in [instructions] + _reminders(monkeypatch):
        assert not FORCED_CHOICE.search(text), FORCED_CHOICE.search(text)


def test_quick_reply_section_teaches_invite_buttons_before_time_buttons():
    section = SYSTEM_PROMPT.split("NÚT TRẢ LỜI NHANH", 1)[1].split("\nVÍ DỤ", 1)[0]
    lines = {key: line for key in QUICK_KEYS for line in section.splitlines() if f"[QUICK:{key}]" in line}
    for key in ("trial_invite", "visit_invite"):
        assert "mời" in lines[key] and "Tìm hiểu thêm" in lines[key], lines[key]
    for key in ("trial_week", "visit_time"):
        assert "đã đồng ý" in lines[key], lines[key]


def test_examples_invite_softly_and_ask_the_time_only_after_the_parent_agrees():
    examples = _examples()
    for parent, reply in examples:
        if FORCED_CHOICE.search(reply) or any(token in reply for token in ASKS_TIME):
            assert any(agree in parent for agree in AGREES), (parent, reply)
    for token in ("[QUICK:trial_invite]", "[QUICK:visit_invite]", "[QUICK:trial_week]"):
        assert any(token in reply for _, reply in examples), token
    invites = [reply for _, reply in examples if "_invite]" in reply]
    # Mỗi lời mời diễn đạt khác nhau, để model không chép một câu mẫu
    assert len({eval_chat.sentences(reply)[-1] for reply in invites}) == len(invites) >= 3


FORCED_TRIAL = "Các cô đồng hành sát sao ạ. Ba/Mẹ cho bé học thử 1 tuần miễn phí nhé, tuần này hay tuần sau ạ?"
SOFT_TRIAL = (
    "Các cô đồng hành sát sao ạ. Ba/Mẹ cho bé học thử 1 tuần miễn phí để cảm nhận trực tiếp nhé, không biết Ba/Mẹ "
    "có muốn đăng ký luôn không ạ? [QUICK:trial_invite]"
)


@pytest.mark.parametrize(
    "reply",
    [
        FORCED_TRIAL,
        FORCED_TRIAL + " [QUICK:trial_week]",
        "Các cô đồng hành sát sao ạ. Ba/Mẹ muốn đưa bé qua tham quan sáng hay chiều ạ? [QUICK:visit_time]",
        "Các cô đồng hành sát sao ạ. Ba/Mẹ ghé tham quan lớp nhé? [QUICK:visit_time]",
    ],
    ids=["tuan-nay-hay-tuan-sau", "kem-nut-tuan", "sang-hay-chieu", "nut-buoi"],
)
def test_eval_flags_asking_the_time_before_the_parent_agrees(reply):
    turn = eval_chat.Turn("con mình nhút nhát lắm")

    problems = eval_chat.check_turn(turn, False, False, reply, [turn.message])

    assert len(problems) == 1 and "chưa đồng ý" in problems[0], problems


def test_eval_accepts_soft_invitation_and_time_question_once_the_parent_agrees():
    assert eval_chat.check_turn(eval_chat.Turn("con mình nhút nhát lắm"), False, False, SOFT_TRIAL, ["nhút nhát"]) == []
    agreed = eval_chat.Turn("có, đăng ký luôn", agreed=True)
    ask_week = "Vâng ạ. Ba/Mẹ tiện cho con bắt đầu tuần này hay tuần sau ạ? [QUICK:trial_week]"
    assert eval_chat.check_turn(agreed, False, False, ask_week, [agreed.message]) == []


def test_eval_scenario_invites_first_and_asks_the_week_after_the_parent_agrees():
    turns = eval_chat.SCENARIOS["moi_hoc_thu"]
    i = next(i for i, t in enumerate(turns) if t.agreed)
    assert i > 0 and not turns[i - 1].agreed
    assert ("học thử",) in turns[i - 1].any_of
    assert "đăng ký" in turns[i].message
    assert ("tuần này", "tuần sau") in turns[i].any_of


# DeepSeek thật qua /test-chat 2026-10-22: bấm "Đăng ký học thử" → bot xin SĐT thay vì hỏi tuần ("…để lại SĐ", cụt);
# bấm "Tuần này" → "Tuần này sắp xếp được ạ…" (tự hứa lịch) rồi xin SĐT lần thứ hai. Quyết định: lượt đồng ý chỉ hỏi
# tuần/buổi; lượt chọn thời gian không khẳng định lịch trống, chỉ báo tư vấn viên xếp và gọi xác nhận, rồi mới xin số
# mềm 1 lần (dòng "Đã hẹn… chưa có SĐT" của trạng thái tư vấn).
AGREEMENTS = {QUICK_REPLIES["trial_invite"][0][1], QUICK_REPLIES["visit_invite"][0][1], QUICK_REPLIES["topics"][2][1]}
PROMISES = ("được ạ", "sắp xếp được", "còn chỗ")
AGREED_ASKS_PHONE = (
    "Vâng ạ, em báo tư vấn viên sắp xếp cho bé một tuần học thử. Nếu tiện, Ba/Mẹ để lại SĐT/Zalo để tư vấn viên "
    "gọi nhé? [QUICK:phone]"
)
WEEK_PROMISED = (
    "Tuần này sắp xếp được ạ, tư vấn viên sẽ gọi xác nhận giờ cụ thể với Ba/Mẹ. Nếu tiện, Ba/Mẹ để lại SĐT/Zalo "
    "để tư vấn viên liên hệ nhé? [QUICK:phone]"
)


def test_reminder_asks_the_time_before_the_phone_right_after_the_parent_agrees(monkeypatch):
    for reminder in _reminders(monkeypatch):
        (line,) = [line for line in reminder.splitlines() if "vừa đồng ý" in line]
        for meaning in AGREEMENTS:
            assert meaning in line, (meaning, line)
        assert re.search(r"\[QUICK:trial_week\][^\n]*\[QUICK:visit_time\][^\n]*CHƯA xin SĐT", line), line
        # [TRẠNG THÁI TƯ VẤN] "Còn thiếu: SĐT/Zalo" từng kéo model xin số ngay ở lượt đồng ý.
        assert "Còn thiếu" in line and "lượt sau" in line, line


def test_reminder_never_asks_for_the_phone_twice_in_a_row(monkeypatch):
    for reminder in _reminders(monkeypatch):
        assert re.search(r"vừa xin SĐT[^\n]*tin trước[^\n]*không xin lại", reminder), reminder


def test_reminder_never_promises_a_slot_when_the_parent_picks_a_time(monkeypatch):
    for reminder in _reminders(monkeypatch):
        (line,) = [line for line in reminder.splitlines() if "chọn/đổi" in line]
        assert all(f"'{phrase}'" in line for phrase in PROMISES), line
        assert re.search(r"KHÔNG nói[^\n]*báo tư vấn viên[^\n]*gọi xác nhận", line), line


def test_eval_agreement_turn_asks_the_week_not_the_phone():
    turn = next(t for t in eval_chat.SCENARIOS["moi_hoc_thu"] if t.agreed)
    problems = eval_chat.check_turn(turn, False, False, AGREED_ASKS_PHONE, [turn.message])
    assert any("[QUICK:trial_week]" in p for p in problems), problems
    assert any("sđt" in p.lower() for p in problems), problems
    ask_week = "Dạ vâng, Casa rất vui được đón bé. Ba/Mẹ muốn con bắt đầu tuần này hay tuần sau ạ? [QUICK:trial_week]"
    assert eval_chat.check_turn(turn, False, False, ask_week, [turn.message]) == []


def test_eval_week_choice_turn_flags_promising_the_slot():
    week = QUICK_REPLIES["trial_week"][0][1]
    turn = next(t for t in eval_chat.SCENARIOS["moi_hoc_thu"] if t.message == week)
    assert turn.known.get("visit_request") and not turn.known.get("phone")
    assert set(PROMISES) <= set(turn.none_of)
    problems = eval_chat.check_turn(turn, False, False, WEEK_PROMISED, [turn.message])
    assert any("sắp xếp được" in p for p in problems), problems
    noted = (
        "Dạ em chuyển tư vấn viên xếp lịch tuần này cho bé, rồi gọi Ba/Mẹ xác nhận ạ. Nếu tiện, Ba/Mẹ để "
        "lại SĐT/Zalo để tư vấn viên gọi nhé? [QUICK:phone]"
    )
    assert eval_chat.check_turn(turn, False, False, noted, [turn.message]) == []


LEARN_MORE = QUICK_REPLIES["trial_invite"][1][1]


def _learn_more_turn():
    return next(t for t in eval_chat.SCENARIOS["tim_hieu_them"] if t.message == LEARN_MORE)


def test_eval_accepts_asking_what_the_parent_wants_to_know_after_learn_more():
    turn = _learn_more_turn()
    reply = "Dạ vâng ạ, Ba/Mẹ muốn biết thêm về điều gì của Casa ạ? [QUICK:topics]"
    assert eval_chat.check_turn(turn, False, False, reply, [turn.message]) == []


def test_eval_scenario_learn_more_asks_what_to_know_without_inviting_again():
    learn = _learn_more_turn()
    assert not learn.agreed
    for token in ("[QUICK:trial_invite]", "[QUICK:visit_invite]", "[QUICK:trial_week]", "[QUICK:visit_time]"):
        assert token in learn.none_of
    reinvite = "Dạ vâng ạ. Không biết Ba/Mẹ có muốn cho bé học thử 1 tuần không ạ? [QUICK:trial_invite]"
    assert eval_chat.check_turn(learn, False, False, reinvite, [learn.message])
    ask = "Dạ vâng ạ, Ba/Mẹ muốn biết thêm về điều gì của Casa ạ? [QUICK:topics]"
    assert eval_chat.check_turn(learn, False, False, ask, [learn.message]) == []


def test_eval_counts_registration_as_next_step_only_when_asked():
    turn = eval_chat.Turn("trường có xe bus không")
    statement = "Trường chưa có xe đưa đón ạ, khi nào đủ phụ huynh đăng ký thì Nhà trường sẽ mở tuyến."
    problems = eval_chat.check_turn(turn, False, False, statement, [turn.message])
    assert len(problems) == 1 and "bước tiếp theo" in problems[0], problems
    question = "Dạ Casa có ưu đãi cho bé thứ 2 ạ. Không biết Ba/Mẹ có muốn đăng ký cho con luôn không ạ?"
    assert eval_chat.check_turn(turn, False, False, question, [turn.message]) == []


@pytest.mark.parametrize(
    "closing", ["Ba/Mẹ còn muốn biết thêm gì không ạ?", "Ba/Mẹ còn quan tâm điều gì nữa không ạ?"]
)
def test_eval_flags_generic_closing_question_on_a_regular_turn(closing):
    turn = eval_chat.Turn("cho hỏi học phí bao nhiêu 1 tháng ạ")
    reply = f"Dạ học phí tùy hệ và nhóm tuổi của bé ạ. {closing}"
    problems = eval_chat.check_turn(turn, False, False, reply, [turn.message])
    assert len(problems) == 1 and "bước tiếp theo" in problems[0], problems


def test_phone_is_asked_softly():
    rule7 = next(line for line in SYSTEM_PROMPT.splitlines() if line.startswith("7. "))
    assert "Nếu tiện" in rule7, rule7
    asks_phone = [reply for _, reply in _examples() if reply.endswith("[QUICK:phone]")]
    assert asks_phone and all("nếu tiện" in reply.lower() for reply in asks_phone), asks_phone


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
        "Nếu tiện, Ba/Mẹ đưa bé qua tham quan lớp một buổi nhé?"
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


class HistoryRecorder(RecordingProvider):
    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024) -> str:
        self.history = list(conversation_history)
        return await super().generate(system_prompt, user_message, conversation_history)


SCHOOL_INTRO = (
    "Casa có 3 cơ sở tại Hà Nội, học Cambridge Early Years kết hợp Montessori cùng giáo viên nước ngoài ạ. "
    "Bé nhà mình năm nay mấy tuổi rồi ạ? [QUICK:age]"
)


@pytest.mark.parametrize(
    ("reply", "failures"),
    [(SCHOOL_INTRO, 0), ("[ESCALATE]", 1), ("Dạ vâng ạ, Ba/Mẹ cho em xin tuổi bé nhé? [QUICK:age]", 1)],
    ids=["gioi-thieu-roi-hoi-tuoi", "escalate", "khong-noi-ve-truong"],
)
def test_eval_replays_the_returning_parent_asking_about_the_school_like_production(monkeypatch, reply, failures):
    (turn,) = eval_chat.SCENARIOS["khach_cu_tim_hieu_truong"]
    assert turn.message == GENERAL_QUESTION and turn.expect_escalate is False
    recorder = HistoryRecorder(reply)
    engine = make_engine(monkeypatch, fake=recorder)

    result = asyncio.run(eval_chat.run_scenario(engine, "khach_cu_tim_hieu_truong", [turn]))

    assert result == (failures, True)
    assert len(recorder.history) == 3
    assert "phụ huynh CŨ quay lại sau khoảng 6 tháng" in recorder.user_message
    assert "[TRẠNG THÁI TƯ VẤN]" in recorder.user_message
    assert "[FIRST_MESSAGE]" not in recorder.user_message


# Production 2026-10-22: phụ huynh vừa gửi SĐT khi bot chưa biết tuổi bé, bot hỏi "dự kiến nhập học khoảng thời gian
# nào" rồi mới hỏi tuổi, vì mục 7 và câu ví dụ dạy hỏi thời điểm nhập học ngay sau SĐT. Học phí và chương trình theo
# tuổi nên tuổi bé hỏi trước; "Còn thiếu" của trạng thái tư vấn cũng bắt đầu bằng tuổi bé.
def test_age_is_asked_before_the_expected_start():
    from app.customer_memory import missing_fields

    rule = next(line for line in SYSTEM_PROMPT.splitlines() if "vừa gửi số" in line)
    assert re.search(r"tuổi bé nếu chưa biết[^\n]*nhập học", rule), rule
    for parent, reply in _examples():
        if re.search(r"dự kiến|nhập học|đi học từ", reply):
            assert "tuổi" in parent, (parent, reply)
    after_phone = [reply for parent, reply in _examples() if "vừa gửi SĐT" in parent and "chưa biết tuổi" in parent]
    assert len(after_phone) == 1 and after_phone[0].endswith("[QUICK:age]"), after_phone
    assert missing_fields({})[0] == "tuổi bé"


def test_eval_flags_asking_the_start_date_before_the_age_right_after_the_phone():
    turn = eval_chat.SCENARIOS["gui_sdt_chon_tuoi"][1]
    assert turn.message == eval_chat.TEST_PHONE and not turn.known.get("kid_age")
    production = "Dạ tư vấn viên sẽ liên hệ Ba/Mẹ trong hôm nay ạ. Bé nhà mình dự kiến nhập học khoảng thời gian nào ạ?"
    problems = eval_chat.check_turn(turn, False, False, production, [turn.message])
    assert any("nhập học" in p for p in problems), problems
    asks_age = "Em chuyển số cho tư vấn viên liên hệ Ba/Mẹ sớm ạ. Bé nhà mình được mấy tháng rồi ạ? [QUICK:age]"
    assert eval_chat.check_turn(turn, False, False, asks_age, [turn.message]) == []


# Production 2026-10-22: "Với lứa nhỏ như bé nhà mình…"; nguồn là câu ví dụ "Lứa này con học…" trong prompt.
def test_prompt_never_teaches_lua_for_a_child():
    assert "lứa" not in SYSTEM_PROMPT.replace("{qa_context}", "").lower()


# Review 2026-10-22: phụ huynh hỏi học phí, gửi tuổi + cơ sở, bot xin số; phụ huynh không gửi, không từ chối rõ mà hỏi
# lại "em cứ báo con số luôn đi" thì từng phải [ESCALATE]. Người vận hành 2026-10-23: không chuyển tư vấn viên nữa;
# biết cơ sở thì bot gửi ảnh học phí của trường (dòng [HỆ THỐNG]), chưa biết thì hỏi cơ sở.
NO_PHONE_FEES = re.compile(
    r"không để lại số khi được xin hoặc từ chối cho số[^\n]*học phí[^\n]*KHÔNG \[ESCALATE\][^\n]*chưa biết cơ sở thì hỏi cơ sở",
    re.I,
)


def test_parent_without_a_phone_still_asking_the_fees_is_not_escalated(monkeypatch):
    section = SYSTEM_PROMPT.split('KHI NÀO TRẢ LỜI ĐÚNG CHUỖI "[ESCALATE]"', 1)[1].split("KÈM HÌNH ẢNH", 1)[0]
    assert "từ chối cho số" not in section and "học phí" not in section, section
    fees = SYSTEM_PROMPT.split("2. Học phí:", 1)[1].split("3. Ưu đãi:", 1)[0]
    assert NO_PHONE_FEES.search(fees), fees
    for reminder in _reminders(monkeypatch):
        lines = reminder.splitlines()
        escalate = next(line for line in lines if "BẮT BUỘC trả lời chính xác chuỗi [ESCALATE]" in line)
        assert "từ chối cho số" not in escalate and "học phí" not in escalate, escalate
        assert NO_PHONE_FEES.search(next(line for line in lines if line.startswith("- Học phí/ưu đãi"))), reminder


def test_fee_image_is_sent_only_by_the_system_line_and_never_as_a_figure():
    fees = SYSTEM_PROMPT.split("2. Học phí:", 1)[1].split("3. Ưu đãi:", 1)[0]
    assert "Không viết con số" in fees and "Ảnh học phí chỉ do hệ thống gửi (dòng [HỆ THỐNG])" in fees, fees
    images = SYSTEM_PROMPT.split("KÈM HÌNH ẢNH", 1)[1].split("NÚT TRẢ LỜI NHANH", 1)[0]
    assert "[HỆ THỐNG]" in images and "không thêm [IMAGES:]" in images, images


def test_media_note_ends_the_reminders_only_when_given(monkeypatch):
    note = media_note([ImageNote("fee", "học phí hệ Song ngữ (cơ sở Kim Mã)")])
    _, with_note = model_input(monkeypatch, "học phí bao nhiêu", conversation_history=FOLLOW_UP, media_note=note)
    _, without = model_input(monkeypatch, "học phí bao nhiêu", conversation_history=FOLLOW_UP)

    assert _reminder(with_note).endswith("\n" + note)
    assert not [line for line in _reminder(without).splitlines() if line.startswith("- [HỆ THỐNG]")]


def test_media_note_says_which_images_follow_and_what_to_ask():
    note = media_note(
        [
            ImageNote("fee", "học phí hệ Song ngữ (cơ sở Kim Mã)"),
            ImageNote("menu", "thực đơn hệ Quốc tế", if_asked=True),
            ImageNote("timetable", "thời khoá biểu", ("cơ sở Ba/Mẹ quan tâm", "tuổi bé"), if_asked=True, state="missing"),
        ],
        facilities_need_campus=True,
    )
    lines = note.splitlines()

    assert lines[0].startswith("- [HỆ THỐNG]") and "không nêu con số" in lines[0] and "không [ESCALATE]" in lines[0]
    assert "không nói không gửi được bảng phí" in lines[0]
    assert "chỉ nói em gửi ảnh có dòng dưới đây" in lines[0] and "không nói tư vấn viên sẽ gửi ảnh đó" in lines[0]
    assert lines[1] == "- [HỆ THỐNG] Sau câu trả lời này hệ thống gửi ảnh học phí hệ Song ngữ (cơ sở Kim Mã)."
    assert lines[2] == "- [HỆ THỐNG] Nếu phụ huynh hỏi thực đơn/ăn uống: sau câu trả lời hệ thống gửi ảnh thực đơn hệ Quốc tế."
    assert lines[3] == (
        "- [HỆ THỐNG] Nếu phụ huynh hỏi chương trình học/Cambridge/thời khoá biểu: chưa biết cơ sở Ba/Mẹ quan tâm và "
        "tuổi bé nên chưa gửi ảnh thời khoá biểu: hỏi cơ sở Ba/Mẹ quan tâm và tuổi bé để em gửi đúng thời khoá biểu; "
        "không nói đã/sẽ gửi ảnh đó, không nói tư vấn viên sẽ gửi."
    )
    assert "hỏi Ba/Mẹ quan tâm cơ sở nào" in lines[4] and "[QUICK:campus]" in lines[4]
    assert media_note([]) == ""


def test_media_note_of_images_already_sent_says_so_without_the_sending_header():
    note = media_note([ImageNote("timetable", "thời khoá biểu cơ sở Kim Mã", if_asked=True, state="sent")])

    assert note == (
        "- [HỆ THỐNG] Nếu phụ huynh hỏi chương trình học/Cambridge/thời khoá biểu: ảnh thời khoá biểu cơ sở Kim Mã đã "
        "gửi ở tin trước ([đã gửi ảnh …] trong lịch sử): nói ngắn ảnh ở phía trên, không gửi lại, không nói tư vấn "
        "viên sẽ gửi."
    )


# Người vận hành 2026-10-24: thiếu cơ sở/tuổi bé thì không có ảnh thời khoá biểu, nên dòng hỏi không mở bằng câu
# "Ảnh dưới đây hệ thống tự gửi" và không cho model nói đã/sẽ gửi.
def test_media_note_of_a_timetable_still_missing_the_age_only_asks_for_it():
    note = media_note([ImageNote("timetable", "thời khoá biểu", ("tuổi bé",), state="missing")])

    assert note == (
        "- [HỆ THỐNG] Chưa biết tuổi bé nên chưa gửi ảnh thời khoá biểu: hỏi tuổi bé để em gửi đúng thời khoá biểu; "
        "không nói đã/sẽ gửi ảnh đó, không nói tư vấn viên sẽ gửi."
    )


# Review 2026-10-23: "lịch chi tiết không có trong Q&A → [ESCALATE]" mâu thuẫn với luật gửi ảnh thời khoá biểu khi
# tin có "lịch học". Có ảnh thời khoá biểu chắc chắn gửi thì trả lời chung + báo gửi, không [ESCALATE], không bịa giờ;
# ảnh chỉ gửi nếu hỏi chương trình (dòng "Nếu…") thì câu hỏi giờ cụ thể vẫn theo luật cũ.
def test_timetable_being_sent_answers_a_schedule_question_without_escalating(monkeypatch):
    sure = media_note([ImageNote("timetable", "thời khoá biểu cơ sở Kim Mã")])
    maybe = media_note([ImageNote("timetable", "thời khoá biểu cơ sở Kim Mã", if_asked=True)])
    _, with_note = model_input(monkeypatch, "lịch học của bé thế nào ạ", conversation_history=FOLLOW_UP, media_note=sure)

    line = _reminder(with_note).splitlines()[-1]
    assert line.startswith("- [HỆ THỐNG] Sau câu trả lời này hệ thống gửi ảnh thời khoá biểu cơ sở Kim Mã."), line
    assert re.search(r"lịch học[^.]*giờ[^.]*trả lời chung[^.]*KHÔNG \[ESCALATE\][^.]*không tự nêu giờ", line), line
    # Chỉ lịch trong tuần: lịch hè, Tết, học bù không có trong thời khoá biểu nên vẫn chuyển tư vấn viên.
    assert re.search(r"Lịch hè/Tết/học bù[^.]*vẫn \[ESCALATE\]", line), line
    assert "ESCALATE" not in maybe.splitlines()[-1] and "lịch học" not in maybe.splitlines()[-1], maybe
    assert "ESCALATE" not in media_note([ImageNote("fee", "học phí hệ Song ngữ (cơ sở Kim Mã)")]).splitlines()[-1]
    escalate = next(l for l in _reminder(with_note).splitlines() if "BẮT BUỘC trả lời chính xác chuỗi [ESCALATE]" in l)
    assert "lịch chi tiết" in escalate, escalate


# Review 2026-10-22: "lịch học" trong danh sách câu hỏi chung mâu thuẫn với ca "lịch chi tiết không có trong Q&A →
# [ESCALATE]"; Q&A không có thời gian biểu trong ngày nên model có thể bịa giờ.
def test_general_school_questions_do_not_cover_schedules_or_specific_facts(monkeypatch):
    section = SYSTEM_PROMPT.split('KHI NÀO TRẢ LỜI ĐÚNG CHUỖI "[ESCALATE]"', 1)[1].split("KÈM HÌNH ẢNH", 1)[0]
    reminders = [
        line for r in _reminders(monkeypatch) for line in r.splitlines() if "BẮT BUỘC trả lời chính xác chuỗi [ESCALATE]" in line
    ]
    for text in [section] + reminders:
        general = text.split("âu hỏi chung về trường", 1)[1]
        assert "lịch học" not in general, general
        assert "dữ kiện cụ thể" in general, general
        specific = text.split("âu hỏi chung về trường", 1)[0]
        assert "lịch chi tiết" in specific and "không chắc dữ kiện đó" in specific, specific


def test_quick_reply_rule_says_the_token_is_hidden_from_the_parent():
    rule = next(line for line in SYSTEM_PROMPT.splitlines() if "thêm ĐÚNG MỘT token" in line)
    assert "ẩn token" in rule, rule


class ScriptedProvider(FakeProvider):
    """Trả lần lượt từng câu trong replies, như model thật qua các lượt."""

    def __init__(self, replies: list[str]):
        super().__init__(None)
        self.replies = list(replies)

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024) -> str:
        self.calls += 1
        return self.replies.pop(0)


FEES_FIRST = "Dạ Casa chào Ba/Mẹ ạ 🌿 Cảm ơn Ba/Mẹ đã quan tâm đến Casa dei Bambini. Bé nhà mình được mấy tuổi rồi ạ? [QUICK:age]"
FEES_IMAGE = (
    "Hệ Quốc tế Mỹ Đình có cô nước ngoài cả ngày, em gửi Ba/Mẹ chính sách học phí tại cơ sở Mỹ Đình để gia đình tham "
    "khảo nhé ạ. Ba/Mẹ có muốn đặt lịch qua xem lớp không ạ? [QUICK:visit_invite]"
)
FEES_NO_IMAGE = (
    "Hệ Quốc tế Mỹ Đình có cô nước ngoài cả ngày ạ. Em không gửi bảng phí trên chat được, nếu tiện Ba/Mẹ để lại "
    "SĐT/Zalo nhé? [QUICK:phone]"
)
FEES_AGAIN = (
    "Dạ mức phí chi tiết nằm trong ảnh em vừa gửi phía trên ạ. Ba/Mẹ có muốn cho bé học thử 1 tuần miễn phí trước "
    "không ạ? [QUICK:trial_invite]"
)


class RecordingScripted(ScriptedProvider):
    def __init__(self, replies: list[str]):
        super().__init__(replies)
        self.user_messages, self.histories = [], []

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024) -> str:
        self.user_messages.append(user_message)
        self.histories.append(list(conversation_history))
        return await super().generate(system_prompt, user_message, conversation_history, max_tokens)


@pytest.mark.parametrize(
    ("replies", "failures"),
    [
        ([FEES_FIRST, FEES_IMAGE, FEES_AGAIN], 0),
        ([FEES_FIRST, FEES_IMAGE, "[ESCALATE]"], 1),
        ([FEES_FIRST, FEES_NO_IMAGE, FEES_AGAIN], 1),
    ],
    ids=["anh-hoc-phi", "escalate", "noi-khong-gui"],
)
def test_eval_fee_image_follows_age_and_campus_and_asking_again_is_no_escalation(monkeypatch, replies, failures):
    turns = eval_chat.SCENARIOS["hoc_phi_chua_de_so"]
    assert "học phí" in turns[0].message
    assert re.search(r"\d+ tuổi", turns[1].message) and "Mỹ Đình" in turns[1].message
    assert all(t.expect_escalate is False for t in turns) and not turns[-1].known.get("phone")
    recorder = RecordingScripted(replies)
    engine = make_engine(monkeypatch, fake=recorder)

    assert asyncio.run(eval_chat.run_scenario(engine, "hoc_phi_chua_de_so", turns)) == (failures, True)
    assert "- [HỆ THỐNG] Sau câu trả lời này hệ thống gửi ảnh học phí hệ Quốc tế (cơ sở Mỹ Đình)." in recorder.user_messages[1]
    assert "- [HỆ THỐNG]" not in recorder.user_messages[2]
    assert recorder.histories[2][-1]["content"].endswith(" [đã gửi ảnh học phí hệ Quốc tế (cơ sở Mỹ Đình)]")


def test_eval_parent_refusing_the_phone_gets_the_fee_image_or_is_asked_the_campus():
    (with_campus,) = eval_chat.SCENARIOS["tu_choi_so_doi_gia"]
    (without_campus,) = eval_chat.SCENARIOS["tu_choi_so_chua_biet_co_so"]
    assert with_campus.known["phone_declined"] and with_campus.known["interested_campus"]
    assert without_campus.known["phone_declined"] and not without_campus.known.get("interested_campus")
    assert [i.if_asked for i in with_campus.images] == [True] and not without_campus.images

    image = "Dạ em gửi Ba/Mẹ chính sách học phí cơ sở Mỹ Đình để gia đình tham khảo ạ. Ba/Mẹ có muốn ghé xem lớp và học thử không ạ?"
    assert eval_chat.check_turn(with_campus, False, False, image, [with_campus.message]) == []
    assert eval_chat.check_turn(with_campus, False, True, "", [with_campus.message])
    ask_phone = "Dạ em gửi Ba/Mẹ chính sách học phí ạ. Nếu tiện Ba/Mẹ để lại SĐT/Zalo để tư vấn viên gọi nhé?"
    assert eval_chat.check_turn(with_campus, False, False, ask_phone, [with_campus.message])
    campus = "Dạ học phí theo từng cơ sở ạ. Ba/Mẹ quan tâm cơ sở nào để em gửi đúng chính sách học phí ạ? [QUICK:campus]"
    assert eval_chat.check_turn(without_campus, False, False, campus, [without_campus.message]) == []
    assert eval_chat.check_turn(without_campus, False, True, "", [without_campus.message])


def test_eval_age_question_after_the_phone_is_specific():
    turn = eval_chat.SCENARIOS["gui_sdt_chon_tuoi"][1]
    any_time = "Dạ Casa nhận nhập học quanh năm, tư vấn viên sẽ liên hệ Ba/Mẹ sớm ạ. Bé nhà mình được mấy tháng rồi ạ? [QUICK:age]"
    assert eval_chat.check_turn(turn, False, False, any_time, [turn.message]) == []
    no_age = "Dạ học phí theo tuổi bé, tư vấn viên sẽ liên hệ Ba/Mẹ sớm ạ. Ba/Mẹ quan tâm cơ sở nào ạ? [QUICK:campus]"
    assert any("mấy tháng" in p for p in eval_chat.check_turn(turn, False, False, no_age, [turn.message]))
    starts = "Tư vấn viên sẽ liên hệ Ba/Mẹ sớm ạ. Bé nhà mình mấy tuổi và dự kiến đi học từ khi nào ạ?"
    assert any("đi học từ" in p for p in eval_chat.check_turn(turn, False, False, starts, [turn.message]))


# Kịch bản eval cho phản hồi đợt 7: tham quan cuối tuần.
WEEKEND_ASK = "Mẹ qua thứ 7 được k nhỉ"


def _turn(scenario: str, message: str):
    (turn,) = [t for t in eval_chat.SCENARIOS[scenario] if t.message == message]
    return turn


def test_eval_flags_promising_a_weekend_visit_and_accepts_inviting_on_weekdays():
    turn = _turn("tham_quan_cuoi_tuan", WEEKEND_ASK)
    production = "Dạ được ạ, em báo tư vấn viên xếp mẹ ghé thứ 7 rồi gọi xác nhận giờ ạ."
    problems = eval_chat.check_turn(turn, False, False, production, [turn.message])
    assert any("được ạ" in p for p in problems) and any("thứ 2" in p for p in problems), problems
    weekdays = (
        "Dạ cuối tuần trường phải sắp xếp riêng nên em chưa dám hẹn trước ạ. Mẹ có thể qua từ thứ 2 đến thứ 6 trong "
        "giờ hành chính không ạ?"
    )
    assert eval_chat.check_turn(turn, False, False, weekdays, [turn.message]) == []


def test_eval_parent_who_cannot_come_on_weekdays_is_passed_to_a_consultant():
    turns = eval_chat.SCENARIOS["tham_quan_cuoi_tuan"]
    turn = turns[-1]
    assert turns[-2].message == WEEKEND_ASK and not turn.known.get("phone")
    messages = [t.message for t in turns]
    promised = "Dạ được ạ, thứ 7 em xếp cho Mẹ ghé nhé."
    assert eval_chat.check_turn(turn, False, False, promised, messages)
    noted = (
        "Dạ vậy em báo tư vấn viên sắp xếp rồi liên hệ xác nhận với Mẹ ạ. Nếu tiện, Mẹ để lại SĐT/Zalo để tư vấn viên "
        "gọi nhé? [QUICK:phone]"
    )
    assert eval_chat.check_turn(turn, False, False, noted, messages) == []


# Phản hồi của trường (đợt 7): hỏi thời lượng Cambridge (hệ Quốc tế), bot trả lời giờ tiếng Anh chung mà không nhắc Cambridge.
def test_eval_cambridge_hours_must_name_cambridge_for_the_international_system():
    (turn,) = eval_chat.SCENARIOS["cambridge_thoi_luong"]
    assert turn.known.get("interested_campus") in ("Mỹ Đình", "Chùa Láng")
    english_only = (
        "Ở hệ Quốc tế, buổi sáng con có khoảng 2,5 giờ tiếng Anh, buổi chiều thêm 1–1,5 giờ ạ. Không biết Ba/Mẹ có "
        "muốn ghé tham quan lớp một buổi không ạ? [QUICK:visit_invite]"
    )
    problems = eval_chat.check_turn(turn, False, False, english_only, [turn.message])
    assert any("cambridge" in p for p in problems), problems
    cambridge = (
        "Dạ bé học Cambridge Early Years mỗi ngày khoảng 1,5–2 giờ: sáng English 30–40 phút, chiều Mathematics hoặc "
        "Let's Explore. Không biết Ba/Mẹ có muốn ghé tham quan lớp một buổi không ạ? [QUICK:visit_invite]"
    )
    assert eval_chat.check_turn(turn, False, False, cambridge, [turn.message]) == []


def test_fee_commitment_is_only_the_base_tuition():
    # Trường xác nhận 2026-10-23: cam kết không tăng chỉ áp cho học phí cơ bản; tiền ăn, phí khác vẫn điều chỉnh.
    import json as _json
    from pathlib import Path as _Path

    pairs = _json.loads((_Path(__file__).resolve().parent.parent / "data" / "qa_database.json").read_text("utf-8"))["qa_pairs"]
    texts = [SYSTEM_PROMPT] + [p["answer"] for p in pairs]
    for text in texts:
        for m in re.finditer(r"(?:không tăng học phí|học phí[^.]{0,20}không tăng)(?! cơ bản)", text):
            window = text[max(0, m.start() - 15) : m.end() + 10]
            assert "cơ bản" in window, window

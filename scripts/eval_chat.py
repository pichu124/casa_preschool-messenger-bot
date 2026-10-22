"""Chấm hội thoại tư vấn của bot với model AI thật, theo kịch bản bán hàng của trường.

Cách chạy (từ thư mục gốc repo, cần ít nhất một API key AI trong .env hoặc biến môi trường):
    .venv/bin/python scripts/eval_chat.py                 # chạy mọi kịch bản
    .venv/bin/python scripts/eval_chat.py che_dat xe_bus  # chỉ chạy các kịch bản được nêu tên

Mỗi kịch bản là vài lượt phụ huynh nhắn liên tiếp; lịch sử hội thoại chỉ giữ trong bộ nhớ. Script dùng
AIEngine + data/qa_database.json như bot thật, nhưng KHÔNG đi qua app.main hay lưu hồ sơ khách (chỉ mượn hàm
thuần customer_memory.format_profile_for_prompt để dựng khối thông tin khách như bot thật): không ghi file nào,
không đụng data/customers.json, không đẩy gì lên GitHub. Mỗi lượt gọi API thật (tốn phí).

Mỗi lượt in transcript và kiểm vài heuristic đơn giản: có dấu tiếng Việt; không gọi "bạn"/"quý khách",
không xưng "tôi"; không nêu số tiền (vd 1.000.000đ); câu cuối có bước tiếp theo (SĐT/Zalo, tham quan,
học thử, hỏi tuổi bé/cơ sở...; trừ lượt chốt hẹn và sau đó, như mục 10 "Đã hẹn" của prompt); tối đa một token [QUICK:] hợp lệ ở cuối; cộng kiểm riêng của từng lượt
(vd không có "%" ở lượt hỏi ưu đãi đầu tiên).
Giọng văn (phản hồi 2026-10-22, xem style_problems): tối đa 3 câu; không đọc lại SĐT phụ huynh đã gửi;
không gọi "anh"/"chị" hay "mẹ"/"ba" một mình khi phụ huynh chưa tự xưng như vậy; không mở đầu "Dạ em ghi nhận".
Heuristic chỉ để lọc nhanh: vẫn phải đọc transcript.

Exit: 0 = mọi heuristic đạt; 1 = có lượt vi phạm; 2 = INCONCLUSIVE (chưa có API key, mọi model đều lỗi)
hoặc sai tên kịch bản.
"""
import asyncio
import logging
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# Chạy thẳng file này thì sys.path[0] là scripts/, nên thêm gốc repo trước khi import app.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ai_engine import API_KEY_MAP, SYSTEM_PROMPT, AIEngine
from app.config import settings
from app.customer_memory import format_profile_for_prompt
from app.qa_database import QADatabase

ASKS_PHONE = ("sđt", "số điện thoại", "zalo")
# Câu cuối đạt nếu có hành động cụ thể, hoặc là câu hỏi lấy thông tin còn thiếu để tư vấn tiếp.
NEXT_ACTIONS = ASKS_PHONE + ("tham quan", "học thử", "liên hệ", "đặt lịch", "giữ lịch")
NEXT_QUESTIONS = (
    "tuổi", "tháng", "ngày sinh", "cơ sở", "khu vực", "địa chỉ", "nhập học",
    "buổi sáng", "buổi chiều", "tuần này", "tuần sau",
)
GREETING = ("casa chào", "casa xin chào", "chào ba/mẹ", "chào ba mẹ")

VIETNAMESE_MARKS = re.compile(r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
# "bạn" chỉ sai khi dùng để gọi phụ huynh; "các bạn", "bạn bè" là nói về trẻ khác.
WRONG_ADDRESS = re.compile(r"(?<!các )(?<!những )(?<!với )(?<!cùng )\bbạn\b(?! bè)|\btôi\b|quý khách", re.I)
MONEY = re.compile(r"\d{1,3}(?:[.,]\d{3})+\s*(?:đ|đồng|vnđ|vnd)|\d+(?:[.,]\d+)?\s*triệu", re.I)
SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
IMAGES_TOKEN = re.compile(r"\[IMAGES:[^\]]*\]")
QUICK_TOKEN = re.compile(r"\[QUICK:([^\]]*)\]")
QUICK_KEYS = set(QUICK_TOKEN.findall(SYSTEM_PROMPT))
MAX_SENTENCES = 3
SENTENCE_PUNCT = re.compile(r"[.?!…]+")
# Gọi phụ huynh là "anh"/"chị"; không tính "tiếng Anh", "người Anh", "anh chị em", "anh/em", "2 anh em", "anh trai", "chị gái".
ANH_CHI = re.compile(
    r"(?<!tiếng )(?<!người )(?<!anh )(?<!anh/)\b(?:anh|chị)\b(?! chị)(?! em)(?!/em)(?!/chị)(?! trai)(?! gái)", re.I
)
# Gọi phụ huynh là "mẹ"/"ba" một mình; không tính "Ba/Mẹ", "ba mẹ", "bố mẹ", "nhớ mẹ", "thứ Ba", "ba tuổi", "Ba Đình".
LONE_BA_ME = re.compile(
    r"(?<!/)(?<!ba )(?<!bố )(?<!cha )(?<!nhớ )(?<!xa )(?<!đòi )(?<!sữa )(?<!bám )\bmẹ\b(?!/)"
    r"|(?<!thứ )\bba\b(?!/)(?! mẹ)(?! (?:đình|tuổi|tháng|năm|ngày|tuần|giờ|buổi|bữa|lần|lớp|môn|cơ sở|bé|con)\b)",
    re.I,
)
PHONE_LIKE = re.compile(r"\+?\(?\d[\d ().-]{7,}\d")
ROBOTIC_OPENING = re.compile(r"^\W*(?:dạ\W*)?em (?:đã )?ghi nhận", re.I)


@dataclass
class Turn:
    message: str
    expect_escalate: bool | None = False  # None: escalate hay trả lời đều chấp nhận
    any_of: list[tuple[str, ...]] = field(default_factory=list)  # mỗi nhóm phải có ít nhất 1 cụm
    none_of: tuple[str, ...] = ()
    known: dict = field(default_factory=dict)  # hồ sơ bot đã có trước lượt này (khối [THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT])
    next_step: bool = True  # False: lượt chốt hẹn và sau đó ("Đã hẹn" là ngoại lệ của nguyên tắc 6)


# Tên Facebook giả trong hồ sơ: bot không được suy ra "anh"/"chị" từ tên.
FB_NAME = {"parent_name": "Phụ Huynh Thử"}
TEST_PHONE = "0912345678"
VISIT = {**FB_NAME, "kid_age": "20 tháng", "interested_campus": "Chùa Láng"}


SCENARIOS: dict[str, list[Turn]] = {
    "hoc_phi_tin_dau": [
        Turn("cho hỏi học phí bao nhiêu 1 tháng ạ", any_of=[("tuổi", "tháng")]),
    ],
    "truong_o_dau": [
        Turn("trường ở đâu vậy ạ", any_of=[("huỳnh thúc kháng", "phạm hùng", "kim mã")]),
    ],
    "che_dat": [
        Turn("bé nhà mình 4 tuổi, nhà ở Cầu Giấy"),
        Turn(
            "học phí đắt quá, trường X gần nhà mình rẻ hơn nhiều",
            any_of=[("cảm ơn", "hiểu", "chia sẻ"), ("giáo viên nước ngoài", "cambridge", "không tăng học phí", "học thử")],
            # CARE không đẩy phụ huynh sang hệ/cơ sở khác như phương án rẻ hơn.
            none_of=("kim mã", "tối ưu chi phí"),
        ),
    ],
    "uu_dai_tu_choi": [
        Turn("trường đang có ưu đãi gì không ạ", any_of=[ASKS_PHONE], none_of=("%",)),
        Turn("thôi mình chưa muốn để lại số đâu", any_of=[("ưu đãi",)], none_of=("%",) + ASKS_PHONE),
    ],
    "uu_dai_anh_em": [
        Turn("bé thứ 2 nhà mình học cùng thì có được giảm học phí không", any_of=[ASKS_PHONE], none_of=("%",)),
        Turn("mình chưa muốn cho số", any_of=[("cơ sở",)], none_of=ASKS_PHONE),
        Turn("mình quan tâm cơ sở Kim Mã", any_of=[("5%",)], none_of=("10%",) + ASKS_PHONE),
    ],
    "be_nhut_nhat": [
        Turn(
            "con mình 2 tuổi nhút nhát lắm, mình sợ con đi học khóc suốt",
            any_of=[("hiểu", "lo lắng", "nỗi lo", "yên tâm")],
        ),
    ],
    "xe_bus": [
        Turn(
            "trường có xe bus đưa đón không ạ",
            any_of=[("chưa có tuyến",), ("đủ phụ huynh", "đăng ký"), ("khu vực",), ASKS_PHONE],
            none_of=("bán kính", "phí xe", "phí đưa đón", "ưu đãi"),
        ),
        Turn("thôi mình chưa muốn để lại số", none_of=ASKS_PHONE),
    ],
    "ngoai_le": [
        Turn("giá bitcoin hôm nay bao nhiêu vậy", expect_escalate=True),
    ],
    "be_12_thang": [
        Turn("bé nhà mình mới 12 tháng thì có học được không", any_of=[("15 tháng",)]),
    ],
    # Hội thoại production 2026-10-22: gửi SĐT, rồi bấm nút tuổi; bot từng đọc lại số và gọi "anh" theo tên Facebook.
    "gui_sdt_chon_tuoi": [
        Turn("cho mình hỏi học phí ạ", known=FB_NAME),
        Turn(TEST_PHONE, known=FB_NAME, any_of=[("liên hệ", "gọi")]),
        Turn("Dưới 2 tuổi", known={**FB_NAME, "phone": TEST_PHONE}),
    ],
    # Chọn cơ sở, hẹn tham quan: không kể lại cơ sở/buổi/SĐT ở mỗi tin, chỉ xác nhận ngắn lúc chốt.
    "hen_tham_quan": [
        Turn("bé nhà mình 20 tháng, mình muốn đi xem trường", known=FB_NAME),
        Turn("cơ sở Chùa Láng", known={**FB_NAME, "kid_age": "20 tháng"}),
        Turn("buổi sáng", known=VISIT),
        Turn(f"sáng mai nhé, số mình {TEST_PHONE}", known=VISIT, any_of=[("liên hệ", "gọi")], next_step=False),
        Turn(
            "ok cảm ơn em",
            known={**VISIT, "phone": TEST_PHONE, "visit_request": "tham quan Chùa Láng sáng mai"},
            none_of=("sáng mai", "chùa láng"),
            next_step=False,
        ),
    ],
}


def sentence_count(text: str) -> int:
    """Số câu của câu bot gửi, bỏ token [QUICK:]/[IMAGES:] và mẩu chỉ có emoji.

    Câu kết ở . ? ! … khi sau đó hết tin hoặc là khoảng trắng rồi chữ không viết thường. Không tách ở "v.v. và",
    "tiếng Anh... và", "1.5", "casa.edu.vn", hay dấu câu ngay sau emoji ("ạ 🌿." đếm như câu chào chuẩn "ạ 🌿 Cảm ơn…").
    """
    text = QUICK_TOKEN.sub("", IMAGES_TOKEN.sub("", text))
    pieces, start = [], 0
    for match in SENTENCE_PUNCT.finditer(text):
        rest, before = text[match.end():], text[: match.start()].rstrip().rstrip("\ufe0f")
        if rest.strip() and (not rest[0].isspace() or rest.lstrip()[0].islower()):
            continue
        if before and unicodedata.category(before[-1]) == "So":
            continue
        pieces.append(text[start : match.end()])
        start = match.end()
    pieces.append(text[start:])
    return sum(any(ch.isalpha() for ch in piece) for piece in pieces)


def style_problems(text: str, parent_messages: list[str], known_phones: set[str]) -> list[str]:
    """Giọng văn: ngắn, không đọc lại SĐT, chỉ gọi anh/chị/mẹ/ba khi phụ huynh đã tự xưng, không khuôn 'em ghi nhận'."""
    problems = []
    if (n := sentence_count(text)) > MAX_SENTENCES:
        problems.append(f"dài {n} câu (tối đa {MAX_SENTENCES})")
    phones = {re.sub(r"\D", "", p)[-9:] for p in known_phones}
    phones |= {re.sub(r"\D", "", p)[-9:] for m in parent_messages for p in PHONE_LIKE.findall(m)}
    if any(re.sub(r"\D", "", p)[-9:] in phones for p in PHONE_LIKE.findall(text)):
        problems.append("đọc lại SĐT phụ huynh đã gửi")
    for address in (ANH_CHI, LONE_BA_ME):
        if (match := address.search(text)) and not any(address.search(m) for m in parent_messages):
            problems.append(f"gọi {match.group(0)!r} khi phụ huynh chưa tự xưng")
    if ROBOTIC_OPENING.search(text):
        problems.append("mở đầu khuôn 'Dạ em ghi nhận'")
    return problems


def last_sentence(text: str) -> str:
    # Bỏ "câu" chỉ gồm emoji/ký hiệu, vd "📅" đứng sau dấu chấm hỏi cuối.
    text = QUICK_TOKEN.sub("", IMAGES_TOKEN.sub("", text))
    sentences = [s for s in SENTENCE_END.split(text) if any(ch.isalpha() for ch in s)]
    return sentences[-1] if sentences else ""


def check_turn(turn: Turn, is_first: bool, escalated: bool, text: str, parent_messages: list[str]) -> list[str]:
    """parent_messages: mọi tin phụ huynh tới lượt này, kể cả turn.message."""
    if turn.expect_escalate is not None and escalated != turn.expect_escalate:
        return [f"mong đợi escalate={turn.expect_escalate}, nhận escalate={escalated}"]
    if escalated:
        return []

    text = unicodedata.normalize("NFC", text)
    known_phones = {turn.known["phone"]} if turn.known.get("phone") else set()
    problems = style_problems(text, parent_messages, known_phones)
    lowered = text.lower()
    last = last_sentence(text).lower()
    if len(VIETNAMESE_MARKS.findall(text)) < 5:
        problems.append("thiếu dấu tiếng Việt")
    if match := WRONG_ADDRESS.search(text):
        problems.append(f"xưng hô sai: {match.group(0)!r}")
    if match := MONEY.search(text):
        problems.append(f"nêu số tiền: {match.group(0)!r}")
    if turn.next_step and not (any(a in last for a in NEXT_ACTIONS) or ("?" in last and any(q in last for q in NEXT_QUESTIONS))):
        problems.append(f"câu cuối không có bước tiếp theo: {last_sentence(text)!r}")
    keys = QUICK_TOKEN.findall(text)
    if len(keys) > 1 or (keys and not text.rstrip().endswith(f"[QUICK:{keys[0]}]")):
        problems.append(f"token [QUICK:] phải có tối đa 1 và ở cuối: {keys}")
    if unknown := [k for k in keys if k not in QUICK_KEYS]:
        problems.append(f"key [QUICK:] lạ: {unknown}")
    if is_first and not any(g in lowered for g in GREETING):
        problems.append("tin đầu tiên thiếu lời chào chuẩn 'Dạ Casa chào Ba/Mẹ ạ'")
    for group in turn.any_of:
        if not any(phrase.lower() in lowered for phrase in group):
            problems.append(f"thiếu một trong {group}")
    for phrase in turn.none_of:
        if phrase.lower() in lowered:
            problems.append(f"không được có {phrase!r}")
    return problems


async def run_scenario(engine: AIEngine, name: str, turns: list[Turn]) -> tuple[int, bool]:
    """Trả về (số lượt vi phạm, có model trả lời không)."""
    print(f"\n===== {name} =====")
    history: list[dict] = []
    failures = 0
    for turn in turns:
        context = format_profile_for_prompt(turn.known)
        resp = await engine.get_response(turn.message, conversation_history=history, customer_context=context)
        if resp.model_used == "none":
            print(f"PH: {turn.message}\n  ! mọi model đều lỗi")
            return failures, False
        shown = "[ESCALATE]" if resp.should_escalate else resp.text
        print(f"PH: {turn.message}\nBOT ({resp.model_used}): {shown}")
        parent_messages = [m["content"] for m in history if m["role"] == "user"] + [turn.message]
        problems = check_turn(turn, not history, resp.should_escalate, resp.text, parent_messages)
        for problem in problems:
            print(f"  ✘ {problem}")
        failures += bool(problems)
        history += [{"role": "user", "content": turn.message}, {"role": "assistant", "content": resp.text}]
    return failures, True


async def main(selected: list[str]) -> int:
    unknown = [name for name in selected if name not in SCENARIOS]
    if unknown:
        print(f"Không có kịch bản: {', '.join(unknown)}. Có: {', '.join(SCENARIOS)}")
        return 2
    if not any(API_KEY_MAP.get(name.strip()) for name in settings.AI_MODEL_ORDER):
        print("INCONCLUSIVE: chưa có API key AI")
        print(f"Đặt key cho một model trong AI_MODEL_ORDER ({','.join(settings.AI_MODEL_ORDER)}) vào .env rồi chạy lại.")
        return 2

    engine = AIEngine(QADatabase(str(ROOT / "data" / "qa_database.json")).build_context())
    failed_turns = 0
    for name in selected or SCENARIOS:
        failures, answered = await run_scenario(engine, name, SCENARIOS[name])
        if not answered:
            print("\nINCONCLUSIVE: mọi model AI đều lỗi (key sai, hết quota hoặc mất mạng)")
            return 2
        failed_turns += failures

    total = sum(len(SCENARIOS[name]) for name in selected or SCENARIOS)
    print(f"\n{total - failed_turns}/{total} lượt đạt heuristic")
    return 1 if failed_turns else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(asyncio.run(main(sys.argv[1:])))

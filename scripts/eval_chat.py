"""Chấm hội thoại tư vấn của bot với model AI thật, theo kịch bản bán hàng của trường.

Cách chạy (từ thư mục gốc repo, cần ít nhất một API key AI trong .env hoặc biến môi trường):
    .venv/bin/python scripts/eval_chat.py                 # chạy mọi kịch bản
    .venv/bin/python scripts/eval_chat.py che_dat xe_bus  # chỉ chạy các kịch bản được nêu tên

Mỗi kịch bản là vài lượt phụ huynh nhắn liên tiếp; lịch sử hội thoại chỉ giữ trong bộ nhớ. Script dùng
AIEngine + data/qa_database.json như bot thật, nhưng KHÔNG đi qua app.main hay app.customer_memory:
không ghi file nào, không đụng data/customers.json, không đẩy gì lên GitHub. Mỗi lượt gọi API thật (tốn phí).

Mỗi lượt in transcript và kiểm vài heuristic đơn giản: có dấu tiếng Việt; không gọi "bạn"/"quý khách",
không xưng "tôi"; không nêu số tiền (vd 1.000.000đ); câu cuối có bước tiếp theo (SĐT/Zalo, tham quan,
học thử, hỏi tuổi bé/cơ sở...); cộng kiểm riêng của từng lượt (vd không có "%" ở lượt hỏi ưu đãi đầu tiên).
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

from app.ai_engine import API_KEY_MAP, AIEngine
from app.config import settings
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


@dataclass
class Turn:
    message: str
    expect_escalate: bool | None = False  # None: escalate hay trả lời đều chấp nhận
    any_of: list[tuple[str, ...]] = field(default_factory=list)  # mỗi nhóm phải có ít nhất 1 cụm
    none_of: tuple[str, ...] = ()


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
        Turn("trường có xe bus đưa đón không ạ", any_of=[("địa chỉ",), ASKS_PHONE]),
    ],
    "ngoai_le": [
        Turn("giá bitcoin hôm nay bao nhiêu vậy", expect_escalate=True),
    ],
    "be_12_thang": [
        Turn("bé nhà mình mới 12 tháng thì có học được không", any_of=[("15 tháng",)]),
    ],
    "workshop": [
        Turn("workshop của cô Phan Thúy có mất phí không, tổ chức ngày nào vậy", any_of=[("miễn phí",), ASKS_PHONE]),
    ],
}


def last_sentence(text: str) -> str:
    # Bỏ "câu" chỉ gồm emoji/ký hiệu, vd "📅" đứng sau dấu chấm hỏi cuối.
    sentences = [s for s in SENTENCE_END.split(IMAGES_TOKEN.sub("", text)) if any(ch.isalpha() for ch in s)]
    return sentences[-1] if sentences else ""


def check_turn(turn: Turn, is_first: bool, escalated: bool, text: str) -> list[str]:
    if turn.expect_escalate is not None and escalated != turn.expect_escalate:
        return [f"mong đợi escalate={turn.expect_escalate}, nhận escalate={escalated}"]
    if escalated:
        return []

    problems = []
    text = unicodedata.normalize("NFC", text)
    lowered = text.lower()
    last = last_sentence(text).lower()
    if len(VIETNAMESE_MARKS.findall(text)) < 5:
        problems.append("thiếu dấu tiếng Việt")
    if match := WRONG_ADDRESS.search(text):
        problems.append(f"xưng hô sai: {match.group(0)!r}")
    if match := MONEY.search(text):
        problems.append(f"nêu số tiền: {match.group(0)!r}")
    if not (any(a in last for a in NEXT_ACTIONS) or ("?" in last and any(q in last for q in NEXT_QUESTIONS))):
        problems.append(f"câu cuối không có bước tiếp theo: {last_sentence(text)!r}")
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
        resp = await engine.get_response(turn.message, conversation_history=history)
        if resp.model_used == "none":
            print(f"PH: {turn.message}\n  ! mọi model đều lỗi")
            return failures, False
        shown = "[ESCALATE]" if resp.should_escalate else resp.text
        print(f"PH: {turn.message}\nBOT ({resp.model_used}): {shown}")
        problems = check_turn(turn, not history, resp.should_escalate, resp.text)
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

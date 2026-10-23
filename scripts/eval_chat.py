"""Chấm hội thoại tư vấn của bot với model AI thật, theo kịch bản bán hàng của trường.

Cách chạy (từ thư mục gốc repo, cần ít nhất một API key AI trong .env hoặc biến môi trường):
    .venv/bin/python scripts/eval_chat.py                 # chạy mọi kịch bản hội thoại, bộ chủ đề và bộ upset
    .venv/bin/python scripts/eval_chat.py che_dat xe_bus  # chỉ chạy các kịch bản được nêu tên
    .venv/bin/python scripts/eval_chat.py topics          # chỉ chạy bộ chủ đề (tên TOPIC_SUITE)
    .venv/bin/python scripts/eval_chat.py upset           # chỉ chạy bộ upset (tên UPSET_SUITE)

Mỗi kịch bản là vài lượt phụ huynh nhắn liên tiếp; lịch sử hội thoại chỉ giữ trong bộ nhớ. Script dùng
AIEngine + data/qa_database.json như bot thật, nhưng KHÔNG đi qua app.main hay lưu hồ sơ khách (chỉ mượn hàm
thuần customer_memory.format_profile_for_prompt để dựng khối thông tin khách như bot thật): không ghi file nào,
không đụng data/customers.json, không đẩy gì lên GitHub. Mỗi lượt gọi API thật (tốn phí).

Mỗi lượt in transcript và kiểm vài heuristic đơn giản: có dấu tiếng Việt; không gọi "bạn"/"quý khách",
không xưng "tôi"; không nêu số tiền (vd 1.000.000đ); câu cuối có bước tiếp theo (SĐT/Zalo, tham quan,
học thử, hỏi tuổi bé/cơ sở...; trừ lượt chốt hẹn và sau đó, như mục 10 "Đã hẹn" của prompt); tối đa một token [QUICK:] hợp lệ ở cuối; cộng kiểm riêng của từng lượt
(vd không có "%" ở lượt hỏi ưu đãi đầu tiên).
Mời trước, hỏi thời gian sau (người vận hành 2026-10-22): khi phụ huynh chưa đồng ý học thử/tham quan
(Turn.agreed), câu cuối không ép chọn "tuần này hay tuần sau"/"sáng hay chiều" và không kèm nút tuần/buổi.
Giọng văn (phản hồi 2026-10-22, xem style_problems): tối đa 3 câu; không đọc lại SĐT phụ huynh đã gửi;
không gọi "anh"/"chị" hay "mẹ"/"ba" một mình khi phụ huynh chưa tự xưng như vậy; không mở đầu "Dạ em ghi nhận".
Không lặp lại câu của tin bot liền trước, không chép câu kể trong ví dụ "Em: …" của SYSTEM_PROMPT (thử DeepSeek
2026-10-22; xem near_copies): câu từ MIN_COPY_WORDS từ trở lên, giống ≥ COPY_RATIO theo SequenceMatcher trên từ.
Heuristic chỉ để lọc nhanh: vẫn phải đọc transcript.

Bộ chủ đề (TOPIC_CASES) đo model trích xuất gắn "topics" (app/topics.py) đúng bao nhiêu. Mỗi câu mẫu là một tin
phụ huynh (kèm câu bot hỏi ngay trước nếu cần) và tập chủ đề kỳ vọng; script gọi AIEngine.extract_customer_info
như process_message (hồ sơ FB_NAME, last_bot_message) rồi lọc bằng clean_topics như bot. Mỗi câu là 1 lượt gọi
extract (tốn phí: 20 câu là 20 lượt, cộng lượt dự phòng khi một model lỗi). Tập ra = tập kỳ vọng là "đúng", có
giao mà khác là "một phần", không giao là "sai" (kỳ vọng [] mà ra chủ đề nào cũng là sai). Chỉ gọi extract, không
gọi chat, nên không có ["Khác"] bot tự gán khi escalate: "Khác" phải do model gắn. Model trả lời mà không ra JSON
thì tính như []. Mỗi câu in một dòng; cuối in tỷ lệ đúng hoàn toàn và đúng một phần. Bộ đạt khi tỷ lệ đúng hoàn
toàn ≥ TOPIC_PASS_RATIO (80%).

Bộ upset (UPSET_CASES) đo cờ "upset" của model trích xuất (mục 2g.2 của docs/quyet-dinh-noi-dung.md): cờ bật thì bot
gửi câu xin lỗi thay mọi câu của model, nên chỉ được bật khi phụ huynh bực vì bị đòi số và muốn thông tin qua chat.
Gọi extract như bộ chủ đề, mỗi câu 1 lượt; cờ chỉ tính khi là JSON true, như app.main. Bộ đạt khi không câu âm nào
bị bật cờ (dương tính giả là ca CARE nhận câu xin lỗi) và bắt được ≥ UPSET_POSITIVE_RATIO (2/3) câu dương.

Exit: 0 = mọi heuristic đạt và các bộ (nếu chạy) đạt ngưỡng; 1 = có lượt vi phạm hoặc một bộ dưới ngưỡng;
2 = INCONCLUSIVE (chưa có API key, mọi model đều lỗi) hoặc sai tên kịch bản.
"""
import asyncio
import logging
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from fractions import Fraction
from pathlib import Path

# Chạy thẳng file này thì sys.path[0] là scripts/, nên thêm gốc repo trước khi import app.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# Chấm bản data/qa_database.json đang sửa: có GITHUB_TOKEN thì QADatabase kéo main về ghi đè nó.
# load_dotenv() không đè biến đã có.
os.environ["GITHUB_TOKEN"] = ""

from app.ai_engine import API_KEY_MAP, SYSTEM_PROMPT, AIEngine
from app.config import settings
from app.customer_memory import format_profile_for_prompt
from app.messenger import QUICK_REPLIES
from app.qa_database import QADatabase
from app.topics import clean_topics

ASKS_PHONE = ("sđt", "số điện thoại", "zalo")
# Câu cuối đạt nếu có hành động cụ thể, hoặc là câu hỏi lấy thông tin còn thiếu để tư vấn tiếp. "đăng ký" chỉ là bước
# tiếp theo khi hỏi ("…khi đủ phụ huynh đăng ký sẽ mở tuyến" thì không). "Còn muốn biết thêm gì không ạ?" là câu chốt
# chung chung, không tính; chỉ lượt "Tìm hiểu thêm" mới được hỏi vậy (next_step=False, any_of kiểm riêng).
NEXT_ACTIONS = ASKS_PHONE + ("tham quan", "học thử", "liên hệ", "đặt lịch", "giữ lịch")
NEXT_QUESTIONS = (
    "tuổi", "tháng", "ngày sinh", "cơ sở", "khu vực", "địa chỉ", "nhập học",
    "buổi sáng", "buổi chiều", "tuần này", "tuần sau", "đăng ký",
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
# Hỏi tuần/buổi là bước sau khi phụ huynh đã đồng ý học thử/tham quan; trước đó là ép chọn.
FORCED_CHOICE = re.compile(r"tuần này hay tuần sau|sáng hay (?:buổi )?chiều", re.I)
TIME_KEYS = {"trial_week", "visit_time"}
# Phụ huynh chọn/đổi thời gian: chỉ tư vấn viên biết lịch trống, bot không tự hứa (DeepSeek thật 2026-10-22).
PROMISES_SLOT = ("được ạ", "sắp xếp được", "còn chỗ")
ROBOTIC_OPENING = re.compile(r"^\W*(?:dạ\W*)?em (?:đã )?ghi nhận", re.I)
MIN_COPY_WORDS = 6
COPY_RATIO = 0.8


@dataclass
class Turn:
    message: str
    expect_escalate: bool | None = False  # None: escalate hay trả lời đều chấp nhận
    any_of: list[tuple[str, ...]] = field(default_factory=list)  # mỗi nhóm phải có ít nhất 1 cụm
    none_of: tuple[str, ...] = ()
    known: dict = field(default_factory=dict)  # hồ sơ bot đã có trước lượt này (khối [THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT])
    # False: lượt chốt hẹn và sau đó ("Đã hẹn" là ngoại lệ của nguyên tắc 6), lượt "Tìm hiểu thêm" (any_of kiểm riêng)
    next_step: bool = True
    agreed: bool = False  # phụ huynh đã đồng ý học thử/tham quan: bot mới được hỏi tuần/buổi
    prior_history: list[dict] = field(default_factory=list)  # lịch sử cũ nạp từ hồ sơ; chỉ đọc ở lượt đầu kịch bản
    gap_hours: float = 0.0  # số giờ từ lần nhắn trước (khách cũ quay lại)


# Tên Facebook giả trong hồ sơ: bot không được suy ra "anh"/"chị" từ tên.
FB_NAME = {"parent_name": "Phụ Huynh Thử"}
TEST_PHONE = "0912345678"
VISIT = {**FB_NAME, "kid_age": "20 tháng", "interested_campus": "Chùa Láng"}
BOOKED = {**VISIT, "phone": TEST_PHONE, "visit_request": "tham quan Chùa Láng buổi sáng"}
VISIT_MD = {**FB_NAME, "kid_age": "3 tuổi", "interested_campus": "Mỹ Đình"}
# Production 2026-10-22: máy chủ khởi động lại nạp hồ sơ cũ (GapHours 4609.8, lịch sử 3 tin); bot [ESCALATE] câu hỏi chung.
OLD_HISTORY = [
    {"role": "user", "content": "chào em"},
    {"role": "user", "content": "cho mình hỏi học phí"},
    {"role": "assistant", "content": "Học phí tùy độ tuổi của bé và cơ sở Ba/Mẹ chọn ạ. Ba/Mẹ cho em xin tuổi bé nhé?"},
]
SCHOOL_INFO = ("montessori", "cambridge", "giáo viên nước ngoài", "3 cơ sở", "huỳnh thúc kháng", "phạm hùng", "kim mã")
ASKS_AGE_OR_CAMPUS = (
    "tuổi bé", "mấy tuổi", "bao nhiêu tuổi", "mấy tháng", "bao nhiêu tháng", "cơ sở nào", "khu vực nào",
    "[quick:age]", "[quick:campus]",
)


SCENARIOS: dict[str, list[Turn]] = {
    "hoc_phi_tin_dau": [
        Turn("cho hỏi học phí bao nhiêu 1 tháng ạ", any_of=[("tuổi", "tháng")]),
    ],
    "truong_o_dau": [
        Turn("trường ở đâu vậy ạ", any_of=[("huỳnh thúc kháng", "phạm hùng", "ngõ 294")]),
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
    # Review 2026-10-22: chưa để số, chưa từ chối rõ (extract không đặt phone_declined) mà hỏi lại học phí: bot không
    # được nêu số, không xin lại ngay, nên [ESCALATE]; main gửi câu chuyển kèm hotline (ESCALATION_MESSAGE_ASK_PHONE).
    "hoc_phi_chua_de_so": [
        Turn("cho mình hỏi học phí ạ", known=FB_NAME),
        Turn("bé nhà mình 3 tuổi, mình quan tâm cơ sở Mỹ Đình", known=FB_NAME, any_of=[ASKS_PHONE]),
        Turn("em cứ báo con số luôn đi", known=VISIT_MD, expect_escalate=True),
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
    "khach_cu_tim_hieu_truong": [
        Turn(
            "tôi muốn tìm hiểu thông tin về trường",
            known=FB_NAME,
            prior_history=OLD_HISTORY,
            gap_hours=4609.8,
            any_of=[SCHOOL_INFO, ASKS_AGE_OR_CAMPUS],
        ),
    ],
    "be_12_thang": [
        Turn("bé nhà mình mới 12 tháng thì có học được không", any_of=[("15 tháng",)]),
    ],
    # Hội thoại production 2026-10-22: gửi SĐT, rồi bấm nút tuổi; bot từng đọc lại số và gọi "anh" theo tên Facebook.
    "gui_sdt_chon_tuoi": [
        Turn("cho mình hỏi học phí ạ", known=FB_NAME),
        # Chưa biết tuổi bé: hỏi tuổi trước thời điểm nhập học (học phí, chương trình theo tuổi).
        Turn(
            TEST_PHONE,
            known=FB_NAME,
            any_of=[("liên hệ", "gọi"), ("mấy tuổi", "bao nhiêu tuổi", "mấy tháng", "bao nhiêu tháng", "[quick:age]")],
            none_of=("dự kiến nhập học", "đi học từ"),
        ),
        Turn("Dưới 2 tuổi", known={**FB_NAME, "phone": TEST_PHONE}),
    ],
    # Chọn cơ sở, hẹn tham quan: không kể lại cơ sở/buổi/SĐT ở mỗi tin, chỉ xác nhận ngắn lúc chốt.
    "hen_tham_quan": [
        Turn("bé nhà mình 20 tháng, mình muốn đi xem trường", known=FB_NAME, agreed=True),
        Turn("cơ sở Chùa Láng", known={**FB_NAME, "kid_age": "20 tháng"}, agreed=True),
        Turn(f"mình muốn đi tham quan buổi sáng, số mình {TEST_PHONE}", known=VISIT, any_of=[("liên hệ", "gọi")], next_step=False),
        # Thử DeepSeek 2026-10-22: bot gửi lại gần nguyên câu xác nhận trước, chép cả câu ví dụ chốt hẹn của prompt.
        Turn("sáng mai được không", known=BOOKED, next_step=False),
        Turn(
            "ok cảm ơn em",
            known={**BOOKED, "visit_request": "tham quan Chùa Láng sáng mai"},
            none_of=("sáng mai", "chùa láng"),
            next_step=False,
        ),
    ],
    # Luồng mời mềm 2026-10-22: bấm "Đặt lịch tham quan" rồi "Buổi sáng" mà chưa để số → xác nhận ngắn và xin số mềm
    # 1 lần (đó không phải lời mời/hẹn lại), lượt sau không xin nữa.
    "hen_chua_co_so": [
        Turn("bé nhà mình 3 tuổi, mình quan tâm cơ sở Mỹ Đình", known=FB_NAME),
        Turn("Em muốn đặt lịch tham quan trường ạ", known=VISIT_MD, any_of=[("buổi sáng", "buổi chiều")], agreed=True),
        Turn(
            "Em muốn hẹn tham quan buổi sáng ạ",
            known={**VISIT_MD, "visit_request": "tham quan Mỹ Đình"},
            any_of=[("liên hệ", "gọi"), ("sđt", "zalo", "số điện thoại"), ("[quick:phone]",)],
            next_step=False,
        ),
        Turn(
            "ok cảm ơn em",
            known={**VISIT_MD, "visit_request": "tham quan Mỹ Đình buổi sáng"},
            none_of=("sđt", "zalo", "số điện thoại", "[quick:phone]"),
            next_step=False,
        ),
    ],
    # Người vận hành 2026-10-22: mời học thử bằng câu hỏi ý, phụ huynh đồng ý rồi bot mới hỏi tuần (chưa xin số);
    # chọn tuần thì không hứa lịch, xin số mềm 1 lần (DeepSeek thật 2026-10-22 xin số ngay lúc đồng ý và hứa "sắp xếp được").
    "moi_hoc_thu": [
        Turn("bé nhà mình 3 tuổi, mình quan tâm cơ sở Mỹ Đình", known=FB_NAME),
        Turn(
            "trường có cho học thử không, con mình nhút nhát sợ không theo được các bạn",
            known={**FB_NAME, "kid_age": "3 tuổi", "interested_campus": "Mỹ Đình"},
            any_of=[("hiểu", "lo lắng", "nỗi lo", "yên tâm"), ("học thử",)],
        ),
        Turn(
            "có, đăng ký luôn cho bé nhé",
            known={**FB_NAME, "kid_age": "3 tuổi", "interested_campus": "Mỹ Đình"},
            any_of=[("tuần này", "tuần sau"), ("[QUICK:trial_week]",)],
            none_of=ASKS_PHONE + ("[QUICK:phone]",),
            agreed=True,
        ),
        Turn(
            QUICK_REPLIES["trial_week"][0][1],
            known={**FB_NAME, "kid_age": "3 tuổi", "interested_campus": "Mỹ Đình", "visit_request": "học thử 1 tuần"},
            any_of=[("tư vấn viên",), ("xác nhận", "liên hệ", "gọi"), ASKS_PHONE],
            none_of=PROMISES_SLOT,
            next_step=False,
            agreed=True,
        ),
    ],
    # Phản hồi của trường (đợt 7): trường làm việc thứ 2–6, cuối tuần phải sắp xếp riêng. Bot từng hứa "Em báo tư vấn
    # viên xếp mẹ ghé thứ 7 ạ…": không hứa cuối tuần, mời qua thứ 2–6; không qua được thì tư vấn viên sắp xếp, xin số.
    "tham_quan_cuoi_tuan": [
        Turn("bé nhà mình 3 tuổi, mình quan tâm cơ sở Mỹ Đình", known=FB_NAME),
        Turn(
            "Mẹ qua thứ 7 được k nhỉ",
            known=VISIT_MD,
            any_of=[("thứ 2", "thứ hai", "trong tuần")],
            none_of=PROMISES_SLOT + ("xếp mẹ ghé thứ 7",),
            next_step=False,
            agreed=True,
        ),
        Turn(
            "trong tuần mẹ bận lắm, không qua được",
            known={**VISIT_MD, "visit_request": "tham quan thứ 7"},
            any_of=[("tư vấn viên",), ("sắp xếp", "xếp"), ("xác nhận", "liên hệ", "gọi"), ASKS_PHONE],
            none_of=PROMISES_SLOT,
            next_step=False,
            agreed=True,
        ),
    ],
    # Phản hồi của trường (đợt 7): hỏi thời gian học từng môn, bot trả lời giờ tiếng Anh chung mà không nhắc Cambridge.
    "cambridge_thoi_luong": [
        Turn(
            "Cambridge học mấy tiếng một ngày",
            known=VISIT_MD,
            any_of=[("cambridge",), ("1,5", "english", "mathematics", "let's explore")],
        ),
    ],
    # "Tìm hiểu thêm" (mục 2f): hỏi Ba/Mẹ muốn biết thêm gì, chưa mời lại, chưa hỏi tuần/buổi.
    "tim_hieu_them": [
        Turn("bé nhà mình 3 tuổi, mình quan tâm cơ sở Mỹ Đình", known=FB_NAME),
        Turn("trường có cho học thử không ạ", known=VISIT_MD, any_of=[("học thử",)]),
        Turn(
            QUICK_REPLIES["trial_invite"][1][1],
            known=VISIT_MD,
            any_of=[("biết thêm", "quan tâm", "tìm hiểu")],
            none_of=("[QUICK:trial_invite]", "[QUICK:visit_invite]", "[QUICK:trial_week]", "[QUICK:visit_time]"),
            next_step=False,
        ),
    ],
}


TOPIC_SUITE = "topics"
TOPIC_PASS_RATIO = 0.8
FULL, PARTIAL, WRONG = "đúng", "một phần", "sai"
ASK_PHONE_BOT = "Nếu tiện, Ba/Mẹ để lại SĐT/Zalo để tư vấn viên liên hệ nhé? [QUICK:phone]"
ASK_AGE_BOT = "Dạ Ba/Mẹ cho em xin tuổi bé để em tư vấn lớp phù hợp ạ? [QUICK:age]"
ASK_TIME_BOT = "Vâng ạ. Ba/Mẹ muốn đưa bé qua tham quan buổi sáng hay buổi chiều ạ? [QUICK:visit_time]"
BOOKED_BOT = "Dạ em đã báo tư vấn viên, tư vấn viên sẽ gọi Ba/Mẹ xác nhận giờ cụ thể ạ."


@dataclass
class TopicCase:
    message: str
    expected: tuple[str, ...]  # chủ đề kỳ vọng, viết như trong TOPICS; () = tin không có chủ đề
    last_bot_message: str = ""  # câu bot gửi ngay trước, như process_message truyền cho extract (lịch sử giữ token [QUICK:])


TOPIC_CASES: list[TopicCase] = [
    TopicCase("hp bn ạ", ("Học phí",)),
    TopicCase("tiền học 1 thág bao nhiu v ạ", ("Học phí",)),
    TopicCase("học phí bao nhiêu, có ưu đãi gì không ạ", ("Học phí", "Ưu đãi")),
    TopicCase("trường dạy theo phương pháp gì vậy ạ", ("Chương trình/phương pháp",)),
    TopicCase("be hoc tieng anh may tieng 1 ngay vay", ("Tiếng Anh/GV nước ngoài",)),
    TopicCase("1 lớp mấy cô mấy bạn ạ", ("Giáo viên/tỷ lệ cô trò",)),
    TopicCase("trường có sân chơi không, phòng học có điều hoà không ạ", ("Cơ sở vật chất",)),
    TopicCase("có camera không, ăn uống thế nào", ("An toàn/sức khoẻ/camera", "Ăn uống/thực đơn")),
    TopicCase("mấy giờ đón con ạ, có trông muộn không", ("Giờ học/đón trả/trông muộn",)),
    TopicCase("trường có xe bus đưa đón không ạ", ("Xe đưa đón",)),
    TopicCase("bé 14 tháng trường nhận chưa ạ, nhập học cần giấy tờ gì", ("Độ tuổi/nhập học/hồ sơ",)),
    TopicCase("cho bé đi học thử vài hôm được không ạ", ("Học thử/tham quan",)),
    TopicCase("con mình hay khóc khi xa mẹ, đi học có quen được không", ("Thích nghi/tâm lý bé",)),
    TopicCase("trường mình khác gì so với Vinschool ạ", ("So sánh trường khác",)),
    TopicCase("giá bitcoin hôm nay bao nhiêu vậy", ("Khác",)),
    TopicCase(TEST_PHONE, (), last_bot_message=ASK_PHONE_BOT),
    # Phụ huynh tự gõ tuổi (bấm nút thì bot nhận "Bé nhà em dưới 2 tuổi ạ").
    TopicCase("Dưới 2 tuổi", (), last_bot_message=ASK_AGE_BOT),
    # Bấm nút "Buổi chiều": bot nhận nghĩa của nút (app.main quick_reply_meaning), không phải tiêu đề.
    TopicCase(QUICK_REPLIES["visit_time"][1][1], (), last_bot_message=ASK_TIME_BOT),
    TopicCase("Chào trường ạ", ()),
    TopicCase("Cảm ơn ạ", (), last_bot_message=BOOKED_BOT),
]


UPSET_SUITE = "upset"
UPSET_POSITIVE_RATIO = Fraction(2, 3)


@dataclass
class UpsetCase:
    message: str
    upset: bool
    last_bot_message: str = ""


UPSET_CASES: list[UpsetCase] = [
    UpsetCase("sao cứ đòi số thế", True, last_bot_message=ASK_PHONE_BOT),
    UpsetCase("không cho số thì không tư vấn à, gửi qua đây đi", True, last_bot_message=ASK_PHONE_BOT),
    UpsetCase("hỏi mãi, gửi bảng giá qua đây luôn", True, last_bot_message=ASK_PHONE_BOT),
    # Ca CARE: bot phải đồng cảm và mời học thử, không xin lỗi rồi chuyển tư vấn viên.
    UpsetCase("học phí đắt quá, trường gần nhà rẻ hơn", False),
    UpsetCase("trường mình so với Vinschool thì thế nào ạ", False),
    UpsetCase("con mình hay khóc khi xa mẹ, mình lo quá", False),
    UpsetCase("em chưa muốn để số ạ", False, last_bot_message=ASK_PHONE_BOT),
    UpsetCase("học phí cho bé 3 tuổi bao nhiêu ạ", False),
]


def sentences(text: str) -> list[str]:
    """Các câu của câu bot gửi, bỏ token [QUICK:]/[IMAGES:] và mẩu chỉ có emoji.

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
    return [piece.strip() for piece in pieces if any(ch.isalpha() for ch in piece)]


def sentence_count(text: str) -> int:
    return len(sentences(text))


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).lower())


def near_copies(text: str, references: list[str]) -> list[str]:
    """Câu trong text (từ MIN_COPY_WORDS từ) gần trùng một câu tham chiếu: lộ bot khi lặp tin trước hoặc chép ví dụ."""
    refs = [_words(r) for r in references]
    return [
        s for s in sentences(text)
        if len(words := _words(s)) >= MIN_COPY_WORDS and any(SequenceMatcher(None, words, r).ratio() >= COPY_RATIO for r in refs)
    ]


OPENING = re.search(r'Mở bằng: "([^"]*)"', SYSTEM_PROMPT).group(1)
# Câu kể trong các ví dụ "Em: …" của prompt. Bỏ câu chào bắt buộc và câu hỏi (bước tiếp theo được phép dùng lại).
EXAMPLE_STATEMENTS = [
    s for reply in re.findall(r'^Em: "(.*)"$', SYSTEM_PROMPT, re.M) for s in sentences(reply)
    if not s.endswith("?") and _words(s) != _words(OPENING)
]


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


def check_turn(
    turn: Turn, is_first: bool, escalated: bool, text: str, parent_messages: list[str], previous_reply: str = ""
) -> list[str]:
    """parent_messages: mọi tin phụ huynh tới lượt này, kể cả turn.message; previous_reply: tin bot liền trước."""
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
    if repeated := near_copies(text, sentences(previous_reply)):
        problems.append(f"lặp lại tin trước: {repeated[0]!r}")
    if copied := near_copies(text, EXAMPLE_STATEMENTS):
        problems.append(f"chép câu ví dụ trong prompt: {copied[0]!r}")
    if match := WRONG_ADDRESS.search(text):
        problems.append(f"xưng hô sai: {match.group(0)!r}")
    if match := MONEY.search(text):
        problems.append(f"nêu số tiền: {match.group(0)!r}")
    if turn.next_step and not (any(a in last for a in NEXT_ACTIONS) or ("?" in last and any(q in last for q in NEXT_QUESTIONS))):
        problems.append(f"câu cuối không có bước tiếp theo: {last_sentence(text)!r}")
    keys = QUICK_TOKEN.findall(text)
    if not turn.agreed and (FORCED_CHOICE.search(last) or TIME_KEYS & set(keys)):
        problems.append(f"hỏi tuần/buổi khi phụ huynh chưa đồng ý học thử/tham quan: {last_sentence(text)!r}")
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
    history: list[dict] = list(turns[0].prior_history)
    failures = 0
    for turn in turns:
        context = format_profile_for_prompt(turn.known)
        resp = await engine.get_response(
            turn.message, conversation_history=history, customer_context=context, gap_hours=turn.gap_hours
        )
        if resp.model_used == "none":
            print(f"PH: {turn.message}\n  ! mọi model đều lỗi")
            return failures, False
        shown = "[ESCALATE]" if resp.should_escalate else resp.text
        print(f"PH: {turn.message}\nBOT ({resp.model_used}): {shown}")
        parent_messages = [m["content"] for m in history if m["role"] == "user"] + [turn.message]
        previous_reply = history[-1]["content"] if history else ""
        problems = check_turn(turn, not history, resp.should_escalate, resp.text, parent_messages, previous_reply)
        for problem in problems:
            print(f"  ✘ {problem}")
        failures += bool(problems)
        history += [{"role": "user", "content": turn.message}, {"role": "assistant", "content": resp.text}]
    return failures, True


ALL_MODELS_FAILED = "INCONCLUSIVE: mọi model AI đều lỗi (key sai, hết quota hoặc mất mạng)"


class EvalEngine(AIEngine):
    """AIEngine đếm số lời gọi có model trả lời: extract_customer_info trả {} cả khi mọi model lỗi."""

    answered = 0

    async def _generate(self, *args, **kwargs) -> str:
        text = await super()._generate(*args, **kwargs)
        self.answered += 1
        return text


def grade_topics(expected: tuple[str, ...], got: list[str]) -> str:
    want, have = set(expected), set(got)
    if want == have:
        return FULL
    return PARTIAL if want & have else WRONG


async def extract(engine: EvalEngine, message: str, last_bot_message: str) -> dict | None:
    """Trích xuất như process_message; None khi mọi model lỗi."""
    before = engine.answered
    extracted = await engine.extract_customer_info(message, FB_NAME, last_bot_message=last_bot_message)
    return extracted if engine.answered > before else None


async def extract_topics(engine: EvalEngine, case: TopicCase) -> list[str] | None:
    """Chủ đề bot sẽ đếm cho tin này; None khi mọi model lỗi."""
    extracted = await extract(engine, case.message, case.last_bot_message)
    return None if extracted is None else clean_topics(extracted.get("topics"))


async def run_topic_cases(engine: EvalEngine) -> bool | None:
    """True/False = bộ chủ đề đạt/dưới ngưỡng; None = mọi model lỗi."""
    print(f"\n===== {TOPIC_SUITE} =====")
    grades = Counter()
    for case in TOPIC_CASES:
        got = await extract_topics(engine, case)
        if got is None:
            print(f"PH: {case.message}\n  ! mọi model đều lỗi")
            return None
        grade = grade_topics(case.expected, got)
        grades[grade] += 1
        print(f"{grade} | {case.message!r} | kỳ vọng {list(case.expected)} | ra {got}")
    total = len(TOPIC_CASES)
    print(
        f"\nChủ đề ({total} câu): đúng hoàn toàn {grades[FULL]}/{total} ({grades[FULL] / total:.0%}), "
        f"đúng một phần {grades[PARTIAL]}/{total} ({grades[PARTIAL] / total:.0%}); "
        f"đạt khi đúng hoàn toàn ≥ {TOPIC_PASS_RATIO:.0%}"
    )
    return grades[FULL] / total >= TOPIC_PASS_RATIO


async def run_upset_cases(engine: EvalEngine) -> bool | None:
    """True/False = bộ upset đạt/dưới ngưỡng; None = mọi model lỗi."""
    print(f"\n===== {UPSET_SUITE} =====")
    positives = sum(case.upset for case in UPSET_CASES)
    caught = false_alarms = 0
    label = {True: "upset", False: "không"}
    for case in UPSET_CASES:
        extracted = await extract(engine, case.message, case.last_bot_message)
        if extracted is None:
            print(f"PH: {case.message}\n  ! mọi model đều lỗi")
            return None
        got = extracted.get("upset") is True  # như app.main
        caught += got and case.upset
        false_alarms += got and not case.upset
        print(f"{FULL if got == case.upset else WRONG} | {case.message!r} | kỳ vọng {label[case.upset]} | ra {label[got]}")
    print(
        f"\nUpset ({len(UPSET_CASES)} câu): câu dương bắt được {caught}/{positives} (cần ≥ {UPSET_POSITIVE_RATIO}), "
        f"câu âm báo nhầm {false_alarms}/{len(UPSET_CASES) - positives} (cần 0)"
    )
    return false_alarms == 0 and caught >= UPSET_POSITIVE_RATIO * positives


async def main(selected: list[str]) -> int:
    unknown = [name for name in selected if name not in SCENARIOS and name not in (TOPIC_SUITE, UPSET_SUITE)]
    if unknown:
        print(f"Không có kịch bản: {', '.join(unknown)}. Có: {', '.join(SCENARIOS)}, {TOPIC_SUITE}, {UPSET_SUITE}")
        return 2
    if not any(API_KEY_MAP.get(name.strip()) for name in settings.AI_MODEL_ORDER):
        print("INCONCLUSIVE: chưa có API key AI")
        print(f"Đặt key cho một model trong AI_MODEL_ORDER ({','.join(settings.AI_MODEL_ORDER)}) vào .env rồi chạy lại.")
        return 2

    engine = EvalEngine(QADatabase(str(ROOT / "data" / "qa_database.json")).build_context())
    scenarios = [name for name in selected if name in SCENARIOS] if selected else list(SCENARIOS)
    failed_turns = 0
    for name in scenarios:
        failures, answered = await run_scenario(engine, name, SCENARIOS[name])
        if not answered:
            print(f"\n{ALL_MODELS_FAILED}")
            return 2
        failed_turns += failures
    if scenarios:
        total = sum(len(SCENARIOS[name]) for name in scenarios)
        print(f"\n{total - failed_turns}/{total} lượt đạt heuristic")

    topics_passed = True
    if not selected or TOPIC_SUITE in selected:
        topics_passed = await run_topic_cases(engine)
        if topics_passed is None:
            print(f"\n{ALL_MODELS_FAILED}")
            return 2
    upset_passed = True
    if not selected or UPSET_SUITE in selected:
        upset_passed = await run_upset_cases(engine)
        if upset_passed is None:
            print(f"\n{ALL_MODELS_FAILED}")
            return 2
    return 1 if failed_turns or not topics_passed or not upset_passed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(asyncio.run(main(sys.argv[1:])))

import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Em là tư vấn viên tuyển sinh online của hệ thống mầm non Casa dei Bambini (Hà Nội), trả lời tin nhắn Messenger của phụ huynh có con từ 15 tháng đến 6 tuổi. Mục tiêu: tư vấn ấm áp, đúng sự thật và đưa phụ huynh tới bước tiếp theo (để lại SĐT/Zalo, tham quan trường, học thử).

GIỌNG VĂN (BẮT BUỘC)
- Luôn viết tiếng Việt CÓ DẤU đầy đủ.
- Xưng "em", gọi phụ huynh là "Ba/Mẹ". Chỉ gọi "anh", "chị", "mẹ bé X"… khi phụ huynh TỰ xưng như vậy trong hội thoại (vd "mình là mẹ bé", "chị muốn hỏi"). TUYỆT ĐỐI không đoán giới tính hay cách xưng hô từ tên Facebook/tên phụ huynh. Không dùng "bạn", "quý khách", "tôi", "chúng tôi".
- Ngắn như nhắn tin: 1–3 câu ngắn mỗi tin. Trả lời đúng ý phụ huynh hỏi, thêm tối đa 1 điểm nổi bật, rồi 1 bước tiếp theo (mục 6). Phụ huynh muốn biết thêm sẽ hỏi tiếp.
- Không nhắc lại thông tin phụ huynh vừa gửi hoặc đã biết (SĐT, tuổi bé, cơ sở, buổi hẹn; có trong lịch sử hoặc [THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT]): biết rồi thì không hỏi lại, không kể lại. Không bao giờ đọc lại số điện thoại. Chỉ khi vừa chốt lịch hẹn mới xác nhận ngắn 1 lần.
- Mở đầu đa dạng, không phải tin nào cũng "Dạ … ạ"; không dùng khuôn "em ghi nhận…". Lịch sự, ấm áp, không khoa trương.
- Gọi trẻ là "bé" hoặc "con"; biết tên bé thì gọi tên.
- Emoji chỉ thỉnh thoảng (tối đa 1, đa số tin không có); không dùng khi nói về học phí, quy định, sức khỏe.

THÔNG TIN CỐT LÕI (luôn đúng)
- 3 cơ sở tại Hà Nội:
  1. Hệ Quốc tế Chùa Láng: Tầng 1+2 Sảnh A1 tòa Hongkong Tower, 185 Huỳnh Thúc Kháng, phường Láng, Hà Nội
  2. Hệ Quốc tế Mỹ Đình: Tầng 3 FLC Complex, 36 Phạm Hùng, phường Từ Liêm, Hà Nội
  3. Hệ Song ngữ Kim Mã: 23 ngõ 294 Kim Mã, phường Ngọc Hà, Hà Nội
- Nhận bé từ 15 tháng, điều kiện đã đi vững.
- Hệ Quốc tế: giáo viên nước ngoài đồng hành cả ngày 8h30–17h00. Hệ Song ngữ: 1 giáo viên nước ngoài tại cơ sở, lớp 0–3 tuổi ~1–1,5 giờ/ngày, lớp 3–6 tuổi ~2–2,5 giờ/ngày.
- Giờ đón chuẩn 17h30.
- Khai giảng chính thức 05/09 hằng năm; nhận hồ sơ và nhập học linh hoạt quanh năm.
- Tặng 1 tuần học thử hoàn toàn miễn phí.

CÁCH TƯ VẤN (theo kịch bản tuyển sinh của trường)
1. Phễu: chào → hỏi tuổi bé + khu vực nhà/cơ sở quan tâm → tư vấn theo nhóm tuổi → học phí → bước tiếp theo.
   - 15 tháng–3 tuổi: chăm sóc, thích nghi, xây nền tảng ngôn ngữ, vận động, giác quan, tự lập, cảm xúc – xã hội qua Montessori; làm quen tiếng Anh tự nhiên cùng giáo viên nước ngoài toàn thời gian (hệ Quốc tế).
   - 3–6 tuổi: Cambridge Early Years kết hợp Montessori. Hệ Quốc tế học đủ English – Mathematics – Let's Explore (khám phá thế giới); Kim Mã học English, còn lại theo 5 lĩnh vực Montessori.
   - Bé dưới 15 tháng hoặc chưa đi vững: nhẹ nhàng nói con còn hơi nhỏ, trường nhận từ 15 tháng khi bé đi vững; xin ngày sinh của bé để tư vấn thời điểm phù hợp.
2. Học phí:
   - Chưa biết tuổi bé VÀ cơ sở quan tâm thì KHÔNG nói con số; hỏi 2 thông tin này trước.
   - Kể giá trị trước: giáo viên nước ngoài toàn thời gian ở hệ Quốc tế, Cambridge Early Years kết hợp Montessori, cam kết không tăng học phí trong suốt thời gian con theo học.
   - KHÔNG gửi bảng học phí trên chat; không bịa số, không tự cộng tổng chi phí. Xin SĐT/Zalo để tư vấn viên tư vấn và gửi bảng phí chi tiết kèm ưu đãi đang áp dụng.
   - Phụ huynh không để lại số mà vẫn muốn biết học phí → trả lời đúng chuỗi [ESCALATE] để nhân viên trả lời trực tiếp.
   - Không hỏi thẳng ngân sách; có thể hỏi gia đình đang cân nhắc hệ Quốc tế hay Song ngữ.
3. Ưu đãi:
   - Hỏi ưu đãi/khuyến mãi: xin SĐT/Zalo trước để tư vấn viên báo đúng ưu đãi của đợt hiện tại. Phụ huynh không cho số → chỉ nói Casa đang có ưu đãi hấp dẫn, tùy từng đợt/chương trình; KHÔNG nêu con số %.
   - Ưu đãi anh chị em ruột / cư dân tòa nhà: nói là CÓ, xin SĐT để tư vấn chi tiết. Không cho số → hỏi cơ sở quan tâm (mỗi cơ sở chính sách khác nhau), rồi nêu đúng chính sách của cơ sở đó theo Q&A.
4. Khách còn phân vân: mời học thử 1 tuần miễn phí hoặc tham quan, không cố chốt trên chat.
5. Chê đắt / so sánh với trường khác → CARE: Connect (đồng cảm, cảm ơn phụ huynh chia sẻ) → Acknowledge (ghi nhận băn khoăn là chính đáng) → Resolve (nêu giá trị khác biệt ở trên; KHÔNG gợi ý hệ/cơ sở khác như phương án rẻ hơn) → Evaluate (hỏi phụ huynh thấy vậy đã rõ chưa), rồi mời học thử 1 tuần miễn phí hoặc tham quan. Không chê trường khác.
6. MỌI câu trả lời (trừ [ESCALATE]) kết thúc bằng ĐÚNG 1 bước tiếp theo cụ thể, dạng câu hỏi dễ trả lời: xin SĐT/Zalo, hẹn tham quan (sáng hay chiều), hẹn học thử (tuần này hay tuần sau), hoặc hỏi tuổi bé/cơ sở còn thiếu. Phụ huynh đang lo lắng (bé nhút nhát, hay khóc, biếng ăn, an toàn): đồng cảm và trấn an trước, rồi mới mời nhẹ nhàng tham quan hoặc học thử.
7. Xin SĐT/Zalo đúng lúc: khi phụ huynh hỏi ưu đãi, học phí chi tiết, xe bus, hoặc cần tư vấn viên hỗ trợ; nói rõ phụ huynh nhận được gì (bảng phí, ưu đãi, được tư vấn trực tiếp).
   - Phụ huynh vừa gửi số → cảm ơn ngắn, báo tư vấn viên sẽ liên hệ sớm (không đọc lại số) và hỏi thời điểm bé dự kiến nhập học. [THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT] đã có SĐT → KHÔNG xin lại.
   - Phụ huynh từ chối cho số (kể cả khi [TRẠNG THÁI TƯ VẤN] ghi "Phụ huynh đã từ chối để lại SĐT: có") → tôn trọng, KHÔNG xin lại; bước tiếp theo là tham quan/học thử.
8. Tài liệu: Q&A có Images (vd thực đơn mẫu) → gửi luôn theo mục KÈM HÌNH ẢNH. Tài liệu không có Images (bảng phí, catalogue, hồ sơ giáo viên…): KHÔNG hứa "gửi ngay qua đây"; tư vấn viên gửi qua Zalo khi có SĐT, hoặc mời tham quan để xem trực tiếp.
9. Xe bus/xe đưa đón: hiện Nhà trường chưa có tuyến xe bus; khi đủ phụ huynh đăng ký, Nhà trường sẽ mở tuyến. Không nêu tuyến, phí, ưu đãi. Xin khu vực nhà + SĐT/Zalo để ghi nhận nhu cầu. Không [ESCALATE] chỉ vì xe bus.
10. [TRẠNG THÁI TƯ VẤN] (trong [THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT]) quyết định bước tiếp theo:
   - "Còn thiếu: …" → bước tiếp theo hỏi điều còn thiếu đầu tiên (SĐT/Zalo vẫn xin đúng lúc như mục 7).
   - "Nguồn: quảng cáo …" → tạo thiện cảm, rồi hỏi tuổi bé/cơ sở hoặc mời để lại SĐT.
   - "Đã hẹn: …" → KHÔNG mời hay hẹn lại tham quan/học thử. Lúc vừa chốt: xác nhận ngắn tư vấn viên sẽ liên hệ để chốt giờ; sau đó không nhắc lại lịch hẹn.

TIN NHẮN ĐẦU TIÊN (có [FIRST_MESSAGE])
- Mở bằng: "Dạ Casa chào Ba/Mẹ ạ 🌿 Cảm ơn Ba/Mẹ đã quan tâm đến Casa dei Bambini." rồi trả lời câu hỏi trong 1 câu.
- Kết bằng câu hỏi tuổi bé kèm [QUICK:age]. Phụ huynh chỉ chào → hỏi Ba/Mẹ quan tâm thông tin nào, kèm [QUICK:topics].

CÁCH TRẢ LỜI
- Tin tiếp theo: không chào lại, vào thẳng câu trả lời. Có [TÓM TẮT CÁC LẦN TRÒ CHUYỆN TRƯỚC ĐÂY] thì đọc để nối tiếp mạch tư vấn.
- Dựa vào THÔNG TIN CỐT LÕI và Q&A bên dưới; diễn đạt lại tự nhiên, chỉ lấy ý chính phụ huynh cần. Không bịa tên, ngày, con số hay dịch vụ không có trong Q&A.

KHI NÀO TRẢ LỜI ĐÚNG CHUỖI "[ESCALATE]" (không thêm chữ nào khác, kể cả ở tin nhắn đầu tiên)
- Câu hỏi hoàn toàn ngoài lề, không liên quan trường/giáo dục/trẻ em (bitcoin, thời tiết, chính trị…).
- Hỏi thông tin cụ thể không có trong Q&A: tên giáo viên cụ thể, ngày sự kiện, lịch chi tiết, kế hoạch mở cơ sở mới…
- Phụ huynh từ chối cho số (ở lượt này hoặc từ trước) mà vẫn cần biết học phí.
- Không chắc → [ESCALATE].

KÈM HÌNH ẢNH
- Q&A có dòng "Images: <url1>,<url2>" thì thêm vào CUỐI câu trả lời chuỗi "[IMAGES:url1,url2]" đúng định dạng; hệ thống tự gửi ảnh và ẩn chuỗi này. Không tự bịa URL.

NÚT TRẢ LỜI NHANH
- Câu hỏi cuối khớp một nút dưới đây thì thêm ĐÚNG MỘT token tương ứng ở tận cùng câu trả lời (sau cả [IMAGES:]); hệ thống hiện nút và ẩn token. Chỉ dùng các token này; không khớp thì thôi; không dùng khi [ESCALATE].
  - [QUICK:topics]: hỏi Ba/Mẹ quan tâm thông tin gì
  - [QUICK:age]: hỏi tuổi bé
  - [QUICK:campus]: hỏi cơ sở quan tâm
  - [QUICK:phone]: xin SĐT/Zalo
  - [QUICK:visit_time]: hỏi tham quan buổi sáng hay buổi chiều
  - [QUICK:trial_week]: hỏi học thử tuần này hay tuần sau

VÍ DỤ (học giọng điệu: ngắn, tự nhiên; không chép máy móc)

Phụ huynh: "[FIRST_MESSAGE] cho hoi hoc phi ntn a"
Em: "Dạ Casa chào Ba/Mẹ ạ 🌿 Cảm ơn Ba/Mẹ đã quan tâm đến Casa dei Bambini. Học phí tùy độ tuổi của bé và cơ sở Ba/Mẹ chọn. Bé nhà mình được bao nhiêu tháng rồi ạ? [QUICK:age]"
Phụ huynh: "Dưới 2 tuổi"
Em: "Casa nhận bé từ 15 tháng, khi con đã đi vững ạ. Lứa này con học tự lập, vận động qua Montessori và làm quen tiếng Anh với cô nước ngoài. Ba/Mẹ quan tâm cơ sở nào ạ? [QUICK:campus]"

(Phụ huynh vừa gửi SĐT)
Em: "Cảm ơn Ba/Mẹ, tư vấn viên sẽ gọi cho mình sớm ạ. Bé dự kiến đi học từ khoảng khi nào ạ?"

(Đã biết bé Bông 3 tuổi) Phụ huynh: "truong co day tieng anh khong"
Em: "Có ạ, Bông học tiếng Anh theo Cambridge Early Years; hệ Quốc tế có giáo viên nước ngoài cả ngày, Kim Mã khoảng 2–2,5 giờ/ngày. Ba/Mẹ muốn ghé tham quan lớp buổi sáng hay buổi chiều ạ? [QUICK:visit_time]"

Phụ huynh: "con em nhat nhung, em so con khong theo dc cac ban"
Em: "Em hiểu nỗi lo này ạ 💕 Các cô cho bé mới làm quen từ từ, có cô đồng hành sát sao và không ép con. Ba/Mẹ cho bé học thử 1 tuần miễn phí xem con thích nghi thế nào nhé, tuần này hay tuần sau ạ? [QUICK:trial_week]"

Phụ huynh: "dat qua, truong gan nha em re hon nhieu" (CARE)
Em: "Em cảm ơn Ba/Mẹ đã chia sẻ, cân nhắc chi phí là rất nên ạ. Ở hệ Quốc tế con có giáo viên nước ngoài cả ngày, Cambridge kết hợp Montessori và học phí cam kết không tăng suốt thời gian học. Ba/Mẹ thấy vậy đã rõ hơn chưa, hay cho bé học thử 1 tuần miễn phí, tuần này hay tuần sau ạ? [QUICK:trial_week]"

(Hỏi ưu đãi, em đã xin SĐT/Zalo) Phụ huynh: "thoi chua muon de so"
Em: "Không sao ạ, hiện Casa đang có ưu đãi hấp dẫn, tùy từng đợt/chương trình. Ba/Mẹ có muốn ghé tham quan lớp không, buổi sáng hay buổi chiều ạ? [QUICK:visit_time]"

Phụ huynh: "truong co xe bus khong"
Em: "Dạ hiện Nhà trường chưa có tuyến xe bus, khi đủ phụ huynh đăng ký sẽ mở tuyến ạ. Ba/Mẹ cho em xin khu vực nhà và SĐT/Zalo để Nhà trường nắm nhu cầu nhé? [QUICK:phone]"

(Đã hẹn tham quan Chùa Láng buổi sáng) Phụ huynh: "sang mai nhe"
Em: "Vâng ạ, tư vấn viên sẽ liên hệ Ba/Mẹ để chốt giờ tham quan sáng mai. Hẹn gặp Ba/Mẹ và bé ở trường nhé!"

CƠ SỞ DỮ LIỆU Q&A:
{qa_context}
"""


# Model suy luận (vd qwen3 trên Groq) trả "<think>…</think>" trước câu trả lời; khối có thể
# bị cắt dở khi chạm max_tokens nên chấp nhận cả trường hợp không có thẻ đóng.
_THINK_RE = re.compile(r"<think>.*?(?:</think>|\Z)\s*", re.S | re.I)


def strip_reasoning(text: str | None) -> str:
    return _THINK_RE.sub("", text or "").strip()


CHAT_MAX_TOKENS = 1024
# JSON trích hồ sơ đủ cả 14 trường dài ~470 ký tự (~150–250 token tiếng Việt); JSON phân loại Q&A ngắn hơn.
# Phải dưới hạn mức token đầu ra/phút của gói miễn phí (Groq: 1000), nếu không lời gọi bị từ chối ngay.
JSON_MAX_TOKENS = 300
# Tóm tắt 2–4 câu, hoặc câu admin trả lời viết lại cho phụ huynh.
TEXT_MAX_TOKENS = 600

# Provider báo quá tải tạm thời (429 do số request): chờ rồi thử lại cùng model, sau đó mới sang model kế.
RETRY_DELAYS = (1.5, 3.0)
MAX_RETRY_AFTER = 5.0
MAX_RETRY_WAIT = 8.0


def _retry_delay(error: Exception, attempt: int) -> float | None:
    """Số giây chờ trước lần thử lại `attempt + 1`, hoặc None nếu lỗi này không đáng thử lại.

    Chỉ 429 do số request mới qua đi sau vài giây. "Request too large" (Groq: vượt hạn mức token/phút),
    413 và các 4xx khác (sai key, sai model) gửi lại y nguyên vẫn bị từ chối.
    """
    if attempt >= len(RETRY_DELAYS):
        return None
    # openai, groq, mistralai: status_code; google-genai: code
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    if status != 429:
        return None
    detail = " ".join(str(getattr(error, name, "") or "") for name in ("body", "message", "details"))
    if "request too large" in detail.lower():
        return None
    # mistralai: raw_response; openai, groq, google-genai: response
    response = getattr(error, "raw_response", None) or getattr(error, "response", None)
    retry_after = getattr(response, "headers", {}).get("retry-after")
    try:
        seconds = float(retry_after)
    except (TypeError, ValueError):
        return RETRY_DELAYS[attempt]
    return seconds if seconds <= MAX_RETRY_AFTER else None


@dataclass
class AIResponse:
    text: str
    should_escalate: bool
    model_used: str


class AIProvider(ABC):
    @abstractmethod
    async def generate(
        self, system_prompt: str, user_message: str, conversation_history: list[dict], max_tokens: int = CHAT_MAX_TOKENS
    ) -> str:
        pass


class OpenAIProvider(AIProvider):
    def __init__(self):
        from openai import AsyncOpenAI
        # SDK openai/groq mặc định tự thử lại 2 lần mọi 429, kể cả "Request too large", chờ tới 60s;
        # tắt đi để chỉ còn chính sách thử lại của AIEngine._generate.
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, max_retries=0)

    async def generate(
        self, system_prompt: str, user_message: str, conversation_history: list[dict], max_tokens: int = CHAT_MAX_TOKENS
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        response = await self.client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content


class GroqProvider(AIProvider):
    def __init__(self):
        from groq import AsyncGroq
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY, max_retries=0)

    async def generate(
        self, system_prompt: str, user_message: str, conversation_history: list[dict], max_tokens: int = CHAT_MAX_TOKENS
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        response = await self.client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content


class GroqSecondProvider(AIProvider):
    """Second Groq model (GROQ_SECOND_MODEL); key "groq_llama" kept for existing AI_MODEL_ORDER."""

    def __init__(self):
        from groq import AsyncGroq
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY, max_retries=0)

    async def generate(
        self, system_prompt: str, user_message: str, conversation_history: list[dict], max_tokens: int = CHAT_MAX_TOKENS
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        response = await self.client.chat.completions.create(
            model=settings.GROQ_SECOND_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content


class MistralProvider(AIProvider):
    def __init__(self):
        from mistralai import Mistral
        self.client = Mistral(api_key=settings.MISTRAL_API_KEY)

    async def generate(
        self, system_prompt: str, user_message: str, conversation_history: list[dict], max_tokens: int = CHAT_MAX_TOKENS
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        response = await self.client.chat.complete_async(
            model=settings.MISTRAL_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content


class DeepSeekProvider(AIProvider):
    """DeepSeek uses OpenAI-compatible API."""

    def __init__(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com",
            max_retries=0,
        )

    async def generate(
        self, system_prompt: str, user_message: str, conversation_history: list[dict], max_tokens: int = CHAT_MAX_TOKENS
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        response = await self.client.chat.completions.create(
            model=settings.DEEPSEEK_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        return response.choices[0].message.content


class GeminiProvider(AIProvider):
    def __init__(self):
        from google import genai
        self.client = genai.Client(api_key=settings.GEMINI_API_KEY)

    async def generate(
        self, system_prompt: str, user_message: str, conversation_history: list[dict], max_tokens: int = CHAT_MAX_TOKENS
    ) -> str:
        from google.genai import types

        contents = [
            types.Content(
                role="user" if msg["role"] == "user" else "model",
                parts=[types.Part.from_text(text=msg["content"])],
            )
            for msg in conversation_history
        ]
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_message)]))

        response = await self.client.aio.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=max_tokens,
                temperature=0.3,
            ),
        )
        return response.text


PROVIDER_MAP: dict[str, type[AIProvider]] = {
    "openai": OpenAIProvider,
    "groq": GroqProvider,
    "groq_llama": GroqSecondProvider,
    "mistral": MistralProvider,
    "deepseek": DeepSeekProvider,
    "gemini": GeminiProvider,
}

API_KEY_MAP: dict[str, str] = {
    "openai": settings.OPENAI_API_KEY,
    "groq": settings.GROQ_API_KEY,
    "groq_llama": settings.GROQ_API_KEY,
    "mistral": settings.MISTRAL_API_KEY,
    "deepseek": settings.DEEPSEEK_API_KEY,
    "gemini": settings.GEMINI_API_KEY,
}


# Trường hồ sơ khách do extract_customer_info trích (lưu vào data/customers.json).
PROFILE_FIELDS = (
    "kid_name", "kid_age", "kid_gender", "parent_name", "address", "area", "phone", "phone_declined",
    "interested_program", "interested_campus", "expected_start", "visit_request", "concerns", "kid_traits",
)


# Module-level reference to the active AIEngine instance.
# Set by main.py after instantiation; used by customer_memory.py for summarization.
ai_engine_instance: "AIEngine | None" = None


class AIEngine:
    def __init__(self, qa_context: str):
        self.qa_context = qa_context
        self.system_prompt = SYSTEM_PROMPT.format(qa_context=qa_context)
        self._providers: dict[str, AIProvider] = {}
        # Register self as the global instance
        global ai_engine_instance
        ai_engine_instance = self

    def _get_provider(self, name: str) -> AIProvider | None:
        if name not in self._providers:
            if name not in PROVIDER_MAP:
                return None
            if not API_KEY_MAP.get(name):
                logger.debug(f"No API key for {name}, skipping")
                return None
            try:
                self._providers[name] = PROVIDER_MAP[name]()
            except Exception as e:
                logger.error(f"Failed to initialize {name}: {e}")
                return None
        return self._providers[name]

    async def _generate(
        self,
        provider: AIProvider,
        system_prompt: str,
        user_message: str,
        history: list[dict],
        max_tokens: int = CHAT_MAX_TOKENS,
    ) -> str:
        """Điểm gọi model duy nhất: bỏ khối <think> để nó không tới phụ huynh hay bị đọc nhầm [ESCALATE].

        Quá tải tạm thời thì chờ rồi thử lại cùng model (tối đa 2 lần, tổng chờ ≤ MAX_RETRY_WAIT); lỗi khác
        ném ra ngay để chuỗi dự phòng thử model kế. Chỉ còn rỗng sau khi lọc (model nghĩ hết max_tokens)
        cũng coi như model lỗi.
        """
        waited = 0.0
        attempt = 0
        while True:
            try:
                raw = await provider.generate(system_prompt, user_message, history, max_tokens=max_tokens)
                break
            except Exception as e:
                delay = _retry_delay(e, attempt)
                if delay is None or waited + delay > MAX_RETRY_WAIT:
                    raise
                attempt += 1
                logger.warning(
                    f"{type(provider).__name__} quá tải ({type(e).__name__} 429), thử lại lần {attempt} sau {delay:g}s"
                )
                await asyncio.sleep(delay)
                waited += delay
        text = strip_reasoning(raw)
        if not text:
            raise ValueError("model không trả câu trả lời nào ngoài khối suy luận")
        return text

    async def get_response(
        self,
        user_message: str,
        conversation_history: list[dict] | None = None,
        customer_context: str = "",
        gap_hours: float = 0.0,
    ) -> AIResponse:
        """Try each model in the fallback chain until one succeeds.

        customer_context: optional string with known customer info to inject into prompt.
        gap_hours: hours since last interaction with this customer (0 if first time).
        """
        history = conversation_history or []

        # Detect first-time message vs returning customer vs continuing conversation
        is_returning_customer = bool(customer_context) and gap_hours >= 24
        # Chỉ dựa vào lịch sử: khách mới từ quảng cáo đã có hồ sơ (nguồn, trạng thái) trước tin đầu tiên.
        is_first_message = len(history) == 0
        first_marker = "[FIRST_MESSAGE] " if is_first_message else ""

        if is_first_message:
            conversation_hint = (
                "- Đây là TIN NHẮN ĐẦU TIÊN của phụ huynh (khách mới). Mở bằng 'Dạ Casa chào Ba/Mẹ ạ 🌿 Cảm ơn Ba/Mẹ "
                "đã quan tâm đến Casa dei Bambini.', trả lời thật ngắn rồi hỏi tuổi bé.\n"
            )
        elif is_returning_customer:
            # Format gap nicely
            if gap_hours < 48:
                gap_text = "hôm qua"
            elif gap_hours < 168:
                gap_text = f"{int(gap_hours / 24)} ngày trước"
            elif gap_hours < 720:
                gap_text = f"khoảng {int(gap_hours / 168)} tuần trước"
            else:
                gap_text = f"khoảng {int(gap_hours / 720)} tháng trước"
            conversation_hint = (
                f"- Đây là phụ huynh CŨ quay lại sau {gap_text}. Chào lại ngắn, ấm áp, gọi tên bé nếu biết "
                f"(VD: 'Casa chào Ba/Mẹ ạ, lâu rồi mới gặp lại, bé Bông dạo này thế nào rồi ạ?'), "
                f"rồi nối tiếp mạch tư vấn theo [TÓM TẮT CÁC LẦN TRÒ CHUYỆN TRƯỚC ĐÂY] và lịch sử tin nhắn.\n"
            )
        else:
            conversation_hint = "- Đây là tin nhắn tiếp theo trong cuộc trò chuyện. KHÔNG chào lại, đi thẳng vào trả lời.\n"

        # Inject customer context if available
        context_section = ""
        if customer_context:
            context_section = f"\n{customer_context}\n"

        # Wrap user message with enforcement reminders
        wrapped_message = (
            f"{context_section}"
            f"[Phụ huynh hỏi]: {first_marker}{user_message}\n\n"
            f"[NHẮC NHỞ QUAN TRỌNG]:\n"
            f"{conversation_hint}"
            f"- Tiếng Việt CÓ DẤU, xưng 'em', gọi 'Ba/Mẹ'; chỉ gọi 'anh/chị/mẹ bé…' khi phụ huynh đã tự xưng như vậy trong hội thoại, "
            f"không đoán giới tính từ tên Facebook/tên phụ huynh. Không dùng 'bạn/quý khách/tôi'.\n"
            f"- Nhắn như người thật: 1–3 câu ngắn, trả lời đúng ý hỏi, thêm tối đa 1 điểm nổi bật; không phải tin nào cũng 'Dạ… ạ', "
            f"không mở bằng 'em ghi nhận'. Không nhắc lại thông tin phụ huynh vừa gửi hoặc đã biết (tuổi bé, cơ sở, lịch hẹn) — "
            f"thông tin đã biết chỉ để không hỏi lại; không đọc lại SĐT.\n"
            f"- Kết thúc bằng ĐÚNG 1 bước tiếp theo cụ thể (xin SĐT/Zalo, hẹn tham quan sáng hay chiều, "
            f"hẹn học thử tuần này hay tuần sau, hoặc hỏi tuổi bé/cơ sở còn thiếu). Phụ huynh đang lo lắng: đồng cảm trước rồi mới mời nhẹ nhàng.\n"
            f"- Học phí/ưu đãi: chưa biết tuổi bé + cơ sở thì không nói con số; không bịa số, không gửi bảng phí trên chat; không nêu % ưu đãi theo đợt. "
            f"[THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT] đã có SĐT, phụ huynh vừa gửi số, hoặc đã từ chối cho số → KHÔNG xin SĐT nữa.\n"
            f"- Xe bus: hiện Nhà trường chưa có tuyến xe bus; khi đủ phụ huynh đăng ký, Nhà trường sẽ mở tuyến. "
            f"Không nêu tuyến, phí, ưu đãi; mời để lại khu vực nhà + SĐT/Zalo để ghi nhận nhu cầu. Không [ESCALATE] chỉ vì xe bus.\n"
            f"- Câu ngoài lề, thông tin cụ thể KHÔNG CÓ trong Q&A (tên giáo viên cụ thể, ngày sự kiện, lịch chi tiết, kế hoạch mở rộng...), "
            f"hoặc đã từ chối cho số mà vẫn cần biết học phí → BẮT BUỘC trả lời chính xác chuỗi [ESCALATE] và KHÔNG nói gì thêm.\n"
            f"- Có [TRẠNG THÁI TƯ VẤN] thì chọn bước tiếp theo theo mục 10; 'Đã hẹn' → không hẹn lại; chỉ lúc vừa chốt mới xác nhận ngắn "
            f"tư vấn viên sẽ liên hệ, sau đó không nhắc lại lịch hẹn.\n"
            f"- Câu hỏi cuối khớp một nút trả lời nhanh thì kết bằng đúng 1 token QUICK (xem NÚT TRẢ LỜI NHANH); không dùng khi [ESCALATE].\n"
            f"- KHÔNG BAO GIỜ tự suy đoán hoặc bịa thông tin. Chỉ dùng THÔNG TIN CỐT LÕI và Q&A."
        )

        for model_name in settings.AI_MODEL_ORDER:
            model_name = model_name.strip()
            provider = self._get_provider(model_name)
            if not provider:
                continue

            try:
                logger.info(f"Trying model: {model_name}")
                response_text = await self._generate(provider, self.system_prompt, wrapped_message, history)

                should_escalate = "[ESCALATE]" in response_text
                if should_escalate:
                    response_text = response_text.replace("[ESCALATE]", "").strip()

                return AIResponse(
                    text=response_text,
                    should_escalate=should_escalate,
                    model_used=model_name,
                )
            except Exception as e:
                logger.warning(f"Model {model_name} failed: {e}")
                continue

        # All models failed
        logger.error("All AI models failed")
        return AIResponse(
            text="",
            should_escalate=True,
            model_used="none",
        )

    async def extract_customer_info(
        self, user_message: str, existing_profile: dict | None = None, last_bot_message: str = ""
    ) -> dict:
        """Extract customer/kid information from user message.

        Asks the model for PROFILE_FIELDS; returns only non-empty values.
        Only those fields of existing_profile go into the prompt, not history or summaries.
        last_bot_message: what the bot sent just before, so a bare "không ạ" to a phone request reads as a refusal.
        """
        profile = existing_profile or {}
        known = {k: profile[k] for k in PROFILE_FIELDS if profile.get(k)}
        existing_context = f"\nThông tin đã biết: {json.dumps(known, ensure_ascii=False)}\n" if known else ""

        extract_prompt = (
            "Bạn là hệ thống trích xuất thông tin từ tin nhắn phụ huynh gửi trường mầm non. "
            "Phân tích tin nhắn và trả về JSON với các trường sau (CHỈ thêm trường khi tin nhắn CÓ đề cập rõ ràng, KHÔNG đoán):\n"
            '- "kid_name": tên bé (VD: "Bông", "Minh")\n'
            '- "kid_age": tuổi bé (VD: "3 tuổi", "18 tháng")\n'
            '- "kid_gender": "bé trai" hoặc "bé gái"\n'
            '- "parent_name": tên phụ huynh\n'
            '- "address": địa chỉ\n'
            '- "area": khu vực nhà (VD: "Cầu Giấy", "Long Biên")\n'
            '- "phone": số điện thoại hoặc số Zalo\n'
            '- "phone_declined": true khi phụ huynh từ chối rõ ràng để lại SĐT/Zalo (VD: "chưa muốn để số", '
            'hoặc "không ạ" khi câu bot vừa hỏi là xin SĐT/Zalo)\n'
            '- "interested_program": "song ngữ" / "quốc tế"\n'
            '- "interested_campus": "Chùa Láng" / "Mỹ Đình" / "Kim Mã"\n'
            '- "expected_start": thời điểm dự kiến cho bé nhập học (VD: "tháng 9", "sau Tết")\n'
            '- "visit_request": lịch tham quan/học thử phụ huynh ĐÃ CHỐT (VD: "tham quan buổi sáng", "học thử tuần sau"); '
            "KHÔNG ghi khi phụ huynh mới hỏi hoặc còn cân nhắc\n"
            '- "concerns": list các mối quan tâm (VD: ["học phí", "an toàn", "ăn uống"])\n'
            '- "kid_traits": list tính cách/đặc điểm bé (VD: ["nhút nhát", "hiếu động", "biếng ăn"])\n\n'
            "CHỈ trả về JSON object. Nếu tin nhắn không chứa thông tin mới nào, trả về {}. "
            "KHÔNG giải thích, KHÔNG markdown code block."
        )
        bot_context = f"Câu bot vừa hỏi: {last_bot_message}\n" if last_bot_message else ""
        user_msg = f"{bot_context}Tin nhắn phụ huynh: {user_message}{existing_context}"

        for model_name in settings.AI_MODEL_ORDER:
            model_name = model_name.strip()
            provider = self._get_provider(model_name)
            if not provider:
                continue
            try:
                result = await self._generate(provider, extract_prompt, user_msg, [], max_tokens=JSON_MAX_TOKENS)
                if result.startswith("```"):
                    result = result.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                    if result.startswith("json"):
                        result = result[4:].strip()
                parsed = json.loads(result)
                # Filter out empty values
                return {k: v for k, v in parsed.items() if v}
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Extract customer info with {model_name} failed: {e}")
                continue

        return {}

    async def summarize_conversation(self, messages: list[dict]) -> str:
        """Use AI to create a concise summary of a conversation chunk.

        messages: list of {role, content, timestamp?} dicts.
        Returns a Vietnamese summary string capturing key facts/decisions.
        """
        if not messages:
            return ""

        # Build readable transcript
        transcript_lines = []
        for m in messages:
            role = "Phụ huynh" if m.get("role") == "user" else "Bot"
            content = m.get("content", "").strip()
            if content:
                transcript_lines.append(f"{role}: {content}")
        transcript = "\n".join(transcript_lines)

        if not transcript:
            return ""

        summarize_prompt = (
            "Bạn là hệ thống tóm tắt hội thoại tư vấn trường mầm non. "
            "Tóm tắt đoạn hội thoại dưới đây thành 2-4 câu tiếng Việt, "
            "tập trung vào: (1) câu hỏi/mối quan tâm chính của phụ huynh, "
            "(2) thông tin đã được tư vấn, (3) quyết định/phản hồi của phụ huynh nếu có. "
            "Viết theo ngôi thứ ba, ngắn gọn, không xưng 'em' hay 'mẹ'. "
            "CHỈ trả về văn bản tóm tắt, KHÔNG thêm gì khác."
        )
        user_msg = f"Đoạn hội thoại:\n{transcript}\n\nTóm tắt:"

        for model_name in settings.AI_MODEL_ORDER:
            model_name = model_name.strip()
            provider = self._get_provider(model_name)
            if not provider:
                continue
            try:
                summary = await self._generate(provider, summarize_prompt, user_msg, [], max_tokens=TEXT_MAX_TOKENS)
                # Strip code blocks if any
                if summary.startswith("```"):
                    summary = summary.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                return summary
            except Exception as e:
                logger.warning(f"Summarize with {model_name} failed: {e}")
                continue

        return ""

    async def format_admin_reply(self, admin_answer: str, original_question: str) -> str:
        """Use AI to format an admin's raw reply into a polite customer response."""
        format_prompt = (
            "Bạn là nhân viên tư vấn trường mầm non Casa. "
            "Admin đã cung cấp câu trả lời cho câu hỏi của phụ huynh. "
            "Viết lại thành tin nhắn Messenger tiếng Việt có dấu, 1–3 câu ngắn, lịch sự, tự nhiên như người thật nhắn tin. "
            "Xưng 'em', gọi phụ huynh là 'Ba/Mẹ'; chỉ gọi 'anh/chị' khi câu hỏi cho thấy phụ huynh tự xưng như vậy, "
            "không đoán giới tính. Giữ nguyên ý nghĩa, không thêm thông tin mới, không chào hỏi dài, không emoji."
        )
        user_msg = (
            f"Câu hỏi của phụ huynh: {original_question}\n"
            f"Câu trả lời từ admin: {admin_answer}\n\n"
            f"Hãy viết lại câu trả lời cho phụ huynh:"
        )

        for model_name in settings.AI_MODEL_ORDER:
            model_name = model_name.strip()
            provider = self._get_provider(model_name)
            if not provider:
                continue
            try:
                return await self._generate(provider, format_prompt, user_msg, [], max_tokens=TEXT_MAX_TOKENS)
            except Exception as e:
                logger.warning(f"Format reply with {model_name} failed: {e}")
                continue

        # Fallback: return admin answer as-is
        return admin_answer

    async def classify_qa(self, question: str, answer: str) -> dict:
        """Use AI to classify a Q&A pair with category, keywords, and similar questions."""
        classify_prompt = (
            "Bạn là hệ thống phân loại Q&A cho trường mầm non. "
            "Cho một cặp câu hỏi và trả lời, hãy phân tích và trả về JSON với format chính xác sau:\n"
            '{"category": "Tên danh mục ngắn gọn (VD: Chương trình học, Chính sách trường, Học phí, Đội ngũ giáo viên, Cơ sở vật chất, Ăn uống, Xe đưa đón...)", '
            '"keywords": ["từ khóa 1", "từ khóa 2", "từ khóa 3"], '
            '"similar_questions": ["Câu hỏi tương tự 1?", "Câu hỏi tương tự 2?"]}\n\n'
            "CHỈ trả về JSON, KHÔNG giải thích thêm."
        )
        user_msg = f"Câu hỏi: {question}\nCâu trả lời: {answer}"

        for model_name in settings.AI_MODEL_ORDER:
            model_name = model_name.strip()
            provider = self._get_provider(model_name)
            if not provider:
                continue
            try:
                result = await self._generate(provider, classify_prompt, user_msg, [], max_tokens=JSON_MAX_TOKENS)
                if result.startswith("```"):
                    result = result.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                return json.loads(result)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Classify with {model_name} failed: {e}")
                continue

        # Fallback
        return {
            "category": "Khác",
            "keywords": [],
            "similar_questions": [],
        }

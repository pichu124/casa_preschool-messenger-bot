import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Em là tư vấn viên tuyển sinh online của hệ thống mầm non Casa dei Bambini (Hà Nội), nhắn Messenger với phụ huynh có con 15 tháng–6 tuổi: tư vấn ấm áp, đúng sự thật, dẫn tới bước tiếp theo.

GIỌNG VĂN (BẮT BUỘC)
- Luôn viết tiếng Việt CÓ DẤU đầy đủ.
- Xưng "em", gọi "Ba/Mẹ"; chỉ gọi "anh", "chị", "mẹ bé X"… khi phụ huynh TỰ xưng như vậy (vd "mình là mẹ bé", "chị muốn hỏi"). TUYỆT ĐỐI không đoán giới tính hay cách xưng hô từ tên Facebook/tên phụ huynh. Không dùng "bạn", "quý khách", "tôi".
- Ngắn như nhắn tin: 1–3 câu ngắn mỗi tin. Trả lời đúng ý phụ huynh hỏi, thêm tối đa 1 điểm nổi bật, rồi 1 bước tiếp theo (mục 6).
- Không nhắc lại thông tin phụ huynh vừa gửi hoặc đã biết (SĐT, tuổi bé, cơ sở, buổi hẹn): dùng để tư vấn đúng hệ/cơ sở/nhóm tuổi, không hỏi lại, không kể lại. Không bao giờ đọc lại số điện thoại.
- Mở đầu đa dạng, không phải tin nào cũng "Dạ … ạ"; không dùng khuôn "em ghi nhận…". Lịch sự, ấm áp, không khoa trương.
- Mỗi tin diễn đạt mới, không lặp lại câu/khuôn câu em vừa gửi ở tin trước; không chép nguyên câu ví dụ (chỉ để học giọng).
- Gọi trẻ là "bé" hoặc "con"; biết tên bé thì gọi tên.
- Emoji tối đa 1, đa số tin không có; không dùng khi nói về học phí, quy định, sức khỏe.

THÔNG TIN CỐT LÕI (luôn đúng)
- 3 cơ sở tại Hà Nội:
  1. Hệ Quốc tế Chùa Láng: Tầng 1+2 Sảnh A1 tòa Hongkong Tower, 185 Huỳnh Thúc Kháng, phường Láng, Hà Nội
  2. Hệ Quốc tế Mỹ Đình: Tầng 3 FLC Complex, 36 Phạm Hùng, phường Từ Liêm, Hà Nội
  3. Hệ Song ngữ Kim Mã: 23 ngõ 294 Kim Mã, phường Ngọc Hà, Hà Nội
- Nhận bé từ 15 tháng, điều kiện đã đi vững.
- Hệ Quốc tế: giáo viên nước ngoài đồng hành cả ngày 8h30–17h00. Hệ Song ngữ: 1 giáo viên nước ngoài tại cơ sở, lớp 0–3 tuổi ~1–1,5 giờ/ngày, lớp 3–6 tuổi ~2–2,5 giờ/ngày.
- Giờ đón chuẩn 17h30.
- Khai giảng chính thức 05/09 hằng năm; nhận hồ sơ và nhập học quanh năm.
- Tặng 1 tuần học thử hoàn toàn miễn phí.

CÁCH TƯ VẤN
1. Phễu: chào → hỏi tuổi bé + khu vực nhà/cơ sở quan tâm → tư vấn theo nhóm tuổi → học phí → bước tiếp theo.
   - 15 tháng–3 tuổi: chăm sóc, thích nghi, xây nền tảng ngôn ngữ, vận động, giác quan, tự lập, cảm xúc – xã hội qua Montessori; làm quen tiếng Anh cùng giáo viên nước ngoài cả ngày (hệ Quốc tế).
   - 3–6 tuổi: Cambridge Early Years kết hợp Montessori. Hệ Quốc tế học đủ English – Mathematics – Let's Explore (khám phá thế giới); Kim Mã học English, còn lại theo 5 lĩnh vực Montessori.
   - Bé dưới 15 tháng hoặc chưa đi vững: nhẹ nhàng nói trường nhận từ 15 tháng khi bé đi vững; xin ngày sinh bé để tư vấn thời điểm phù hợp.
2. Học phí:
   - Chưa biết tuổi bé VÀ cơ sở quan tâm thì KHÔNG nói con số; hỏi 2 thông tin này trước.
   - Kể giá trị trước: giáo viên nước ngoài cả ngày (hệ Quốc tế), Cambridge Early Years kết hợp Montessori, cam kết không tăng học phí suốt thời gian con theo học.
   - KHÔNG gửi bảng học phí trên chat; không bịa số, không tự cộng tổng chi phí. Xin SĐT/Zalo để tư vấn viên gửi bảng phí chi tiết kèm ưu đãi.
   - Phụ huynh không để lại số mà vẫn muốn biết học phí → [ESCALATE] để nhân viên trả lời trực tiếp.
   - Không hỏi thẳng ngân sách; có thể hỏi gia đình đang cân nhắc hệ Quốc tế hay Song ngữ.
3. Ưu đãi:
   - Hỏi ưu đãi/khuyến mãi: xin SĐT/Zalo trước để tư vấn viên báo ưu đãi đợt hiện tại. Phụ huynh không cho số → chỉ nói Casa đang có ưu đãi hấp dẫn, tùy từng đợt/chương trình; KHÔNG nêu con số %.
   - Ưu đãi anh chị em ruột / cư dân tòa nhà: nói là CÓ, xin SĐT. Không cho số → hỏi cơ sở quan tâm (mỗi cơ sở chính sách khác), rồi nêu đúng chính sách cơ sở đó theo Q&A.
4. Khách còn phân vân: mời học thử 1 tuần miễn phí hoặc tham quan, không cố chốt trên chat.
5. Chê đắt / so sánh trường khác → CARE: Connect (đồng cảm, cảm ơn chia sẻ) → Acknowledge (băn khoăn là chính đáng) → Resolve (nêu giá trị khác biệt ở trên; KHÔNG gợi ý hệ/cơ sở khác như phương án rẻ hơn) → Evaluate (hỏi Ba/Mẹ thấy đã rõ chưa), rồi mời học thử 1 tuần miễn phí hoặc tham quan. Không chê trường khác.
6. MỌI câu trả lời (trừ [ESCALATE], 'Đã hẹn') kết thúc bằng ĐÚNG 1 bước tiếp theo cụ thể: câu trọn ý, có từ đệm tự nhiên, không cụt, không thúc ép (xin SĐT/Zalo, mời tham quan/học thử, hoặc hỏi tuổi bé/cơ sở còn thiếu). Mời là hỏi ý ("không biết Ba/Mẹ có muốn … không ạ?", "nếu tiện…") kèm [QUICK:trial_invite]/[QUICK:visit_invite], chưa bắt chọn tuần/buổi; phụ huynh đã đồng ý (bấm nút hoặc nói muốn) mới hỏi thời gian kèm [QUICK:trial_week]/[QUICK:visit_time]. Phụ huynh muốn tìm hiểu thêm → hỏi Ba/Mẹ muốn biết thêm gì, chưa mời lại. Phụ huynh lo lắng (bé nhút nhát, hay khóc, biếng ăn, an toàn): đồng cảm, trấn an trước rồi mới mời nhẹ nhàng.
7. Xin SĐT/Zalo mềm ("Nếu tiện, Ba/Mẹ để lại SĐT/Zalo…") khi phụ huynh hỏi ưu đãi, học phí chi tiết, xe bus hoặc cần tư vấn viên; nói rõ nhận được gì (bảng phí, ưu đãi, tư vấn trực tiếp).
   - Phụ huynh vừa gửi số → cảm ơn ngắn, báo tư vấn viên sẽ liên hệ sớm (không đọc lại số) và hỏi thời điểm bé dự kiến nhập học. [THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT] đã có SĐT → KHÔNG xin lại.
   - Phụ huynh từ chối cho số (kể cả khi [TRẠNG THÁI TƯ VẤN] ghi "Phụ huynh đã từ chối để lại SĐT: có") → tôn trọng, KHÔNG xin lại; bước tiếp theo là tham quan/học thử.
8. Tài liệu không có Images trong Q&A (bảng phí, catalogue, hồ sơ giáo viên…): KHÔNG hứa "gửi ngay qua đây"; tư vấn viên gửi qua Zalo khi có SĐT, hoặc mời tham quan để xem trực tiếp.
9. Xe bus: hiện Nhà trường chưa có tuyến xe bus; khi đủ phụ huynh đăng ký sẽ mở tuyến. Không nêu tuyến, phí, ưu đãi; xin khu vực nhà + SĐT/Zalo để ghi nhận nhu cầu. Không [ESCALATE] chỉ vì xe bus.
10. [TRẠNG THÁI TƯ VẤN] (trong [THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT]) quyết định bước tiếp theo:
   - "Còn thiếu: …" → bước tiếp theo hỏi điều còn thiếu đầu tiên (SĐT/Zalo vẫn xin đúng lúc như mục 7).
   - "Nguồn: quảng cáo …" → tạo thiện cảm, rồi hỏi tuổi bé/cơ sở hoặc mời để lại SĐT.
   - "Đã hẹn: …" → KHÔNG mời/hẹn lại, không cần bước tiếp theo. Vừa chốt: xác nhận ngắn tư vấn viên sẽ liên hệ chốt giờ; phụ huynh đổi/chốt cụ thể hơn → trả lời thẳng ý mới, không lặp lại câu xác nhận, không tự hứa lịch; sau đó không nhắc lại lịch hẹn.

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
- Q&A có dòng "Images: <url1>,<url2>" (vd thực đơn mẫu) thì gửi luôn: thêm vào CUỐI câu trả lời chuỗi "[IMAGES:url1,url2]"; hệ thống tự gửi ảnh và ẩn chuỗi này. Không tự bịa URL.

NÚT TRẢ LỜI NHANH
- Câu hỏi cuối khớp một nút dưới đây thì thêm ĐÚNG MỘT token ở tận cùng (sau cả [IMAGES:]); hệ thống hiện nút, ẩn token. Chỉ dùng các token này; không khớp hoặc [ESCALATE] thì thôi.
  - [QUICK:topics]: hỏi Ba/Mẹ quan tâm thông tin gì
  - [QUICK:age]: hỏi tuổi bé
  - [QUICK:campus]: hỏi cơ sở quan tâm
  - [QUICK:phone]: xin SĐT/Zalo
  - [QUICK:trial_invite]: mời học thử (Đăng ký học thử / Tìm hiểu thêm)
  - [QUICK:visit_invite]: mời tham quan (Đặt lịch tham quan / Tìm hiểu thêm)
  - [QUICK:trial_week]: đã đồng ý học thử, hỏi tuần
  - [QUICK:visit_time]: đã đồng ý tham quan, hỏi buổi

VÍ DỤ

Phụ huynh: "[FIRST_MESSAGE] cho hoi hoc phi ntn a"
Em: "Dạ Casa chào Ba/Mẹ ạ 🌿 Cảm ơn Ba/Mẹ đã quan tâm đến Casa dei Bambini. Học phí tùy độ tuổi của bé và cơ sở Ba/Mẹ chọn. Bé nhà mình được bao nhiêu tháng rồi ạ? [QUICK:age]"
Phụ huynh: "Dưới 2 tuổi"
Em: "Casa nhận bé từ 15 tháng, khi con đã đi vững ạ. Lứa này con học tự lập, vận động qua Montessori và làm quen tiếng Anh với cô nước ngoài. Ba/Mẹ quan tâm cơ sở nào ạ? [QUICK:campus]"

(Phụ huynh vừa gửi SĐT)
Em: "Cảm ơn Ba/Mẹ, tư vấn viên sẽ gọi cho mình sớm ạ. Bé dự kiến đi học từ khoảng khi nào ạ?"

(Đã biết bé Bông 3 tuổi) Phụ huynh: "truong co day tieng anh khong"
Em: "Có ạ, Bông học tiếng Anh theo Cambridge Early Years; hệ Quốc tế có giáo viên nước ngoài cả ngày, Kim Mã khoảng 2–2,5 giờ/ngày. Không biết Ba/Mẹ có muốn ghé tham quan lớp một buổi không ạ? [QUICK:visit_invite]"

Phụ huynh: "con em nhat nhung, em so con khong theo dc cac ban"
Em: "Em hiểu nỗi lo này ạ 💕 Các cô cho bé mới làm quen từ từ, có cô đồng hành sát sao và không ép con. Casa tặng 1 tuần học thử miễn phí để con quen dần, Ba/Mẹ có muốn cho bé thử không ạ? [QUICK:trial_invite]"

Phụ huynh: "dat qua, truong gan nha em re hon nhieu" (CARE)
Em: "Em hiểu, khoản này nhà nào cũng cân nhắc kỹ ạ. Hệ Quốc tế có cô nước ngoài cả ngày, học phí không tăng suốt thời gian con học. Ba/Mẹ có muốn để bé học thử 1 tuần miễn phí rồi hẵng quyết không ạ? [QUICK:trial_invite]"

Phụ huynh: "Em muốn đăng ký cho bé học thử 1 tuần ạ"
Em: "Vâng ạ, em báo tư vấn viên sắp xếp cho bé. Ba/Mẹ tiện cho con bắt đầu tuần này hay tuần sau ạ? [QUICK:trial_week]"

(Hỏi ưu đãi, em đã xin SĐT/Zalo) Phụ huynh: "thoi chua muon de so"
Em: "Không sao ạ, hiện Casa đang có ưu đãi hấp dẫn, tùy từng đợt/chương trình. Hôm nào tiện, Ba/Mẹ đưa bé qua trường xem lớp một buổi nhé? [QUICK:visit_invite]"

Phụ huynh: "truong co xe bus khong"
Em: "Dạ hiện Nhà trường chưa có tuyến xe bus, khi đủ phụ huynh đăng ký sẽ mở tuyến ạ. Nếu tiện, Ba/Mẹ để lại khu vực nhà và SĐT/Zalo để trường nắm nhu cầu nhé? [QUICK:phone]"

(Vừa xác nhận tham quan sáng) Phụ huynh: "sang mai duoc khong"
Em: "Dạ em báo tư vấn viên xếp sáng mai, rồi gọi Ba/Mẹ xác nhận giờ ạ."

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
# Tóm tắt 2–4 câu.
TEXT_MAX_TOKENS = 600
# Câu admin viết lại phải giữ đủ dữ kiện admin đưa; vẫn dưới OTPM 1000 của Groq miễn phí.
ADMIN_REPLY_MAX_TOKENS = 900

# Mặc định SDK openai/groq chờ 600s, mistralai và google-genai không giới hạn: một lời gọi treo giữ phụ huynh
# chờ mãi. 30s đủ cho câu trả lời chính 1024 token; hết giờ thì thử lại 1 lần rồi sang model kế.
AI_TIMEOUT = 30.0

# Provider báo quá tải tạm thời (429 do số request): chờ rồi thử lại cùng model, sau đó mới sang model kế.
RETRY_DELAYS = (1.5, 3.0)
MAX_RETRY_AFTER = 5.0
MAX_RETRY_WAIT = 8.0
# Lỗi máy chủ (5xx, 408, 409) hoặc mất kết nối/hết giờ: thử lại 1 lần.
TRANSIENT_RETRY_DELAY = 1.0


def _is_connection_error(error: Exception) -> bool:
    """Mất kết nối hoặc hết giờ: openai/groq gói lỗi httpx lại, mistralai và google-genai để nguyên."""
    import groq
    import openai

    return isinstance(error, (openai.APIConnectionError, groq.APIConnectionError, httpx.TransportError))


def _status(error: Exception) -> int | None:
    # openai, groq, mistralai: status_code; google-genai: code (openai/groq cũng có `code` nhưng là chuỗi)
    status = getattr(error, "status_code", None) or getattr(error, "code", None)
    return status if isinstance(status, int) else None


def _retry_delay(error: Exception, attempt: int) -> float | None:
    """Số giây chờ trước lần thử lại `attempt + 1`, hoặc None nếu lỗi này không đáng thử lại.

    429 do số request qua đi sau vài giây: thử lại tối đa 2 lần. Lỗi máy chủ (5xx, 408, 409) và mất kết nối
    thường chỉ thoáng qua: thử lại 1 lần. "Request too large" (Groq: vượt hạn mức token/phút), 413 và các
    4xx khác (sai key, sai model) gửi lại y nguyên vẫn bị từ chối.
    """
    status = _status(error)
    if _is_connection_error(error) or (status is not None and (status >= 500 or status in (408, 409))):
        return TRANSIENT_RETRY_DELAY if attempt == 0 else None
    if status != 429 or attempt >= len(RETRY_DELAYS):
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
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, max_retries=0, timeout=AI_TIMEOUT)

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
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY, max_retries=0, timeout=AI_TIMEOUT)

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
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY, max_retries=0, timeout=AI_TIMEOUT)

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
        self.client = Mistral(api_key=settings.MISTRAL_API_KEY, timeout_ms=int(AI_TIMEOUT * 1000))

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
            timeout=AI_TIMEOUT,
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
        from google.genai import types

        self.client = genai.Client(
            api_key=settings.GEMINI_API_KEY, http_options=types.HttpOptions(timeout=int(AI_TIMEOUT * 1000))
        )

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

        Lỗi tạm thời thì chờ rồi thử lại cùng model (xem _retry_delay; tổng chờ ≤ MAX_RETRY_WAIT); lỗi khác
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
                status = _status(e)
                cause = f"{type(e).__name__} {status}" if status else type(e).__name__
                logger.warning(
                    f"{type(provider).__name__} lỗi tạm thời ({cause}), thử lại lần {attempt} sau {delay:g}s"
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
            f"dùng nó để tư vấn đúng hệ/cơ sở/nhóm tuổi, không hỏi lại, nhưng không kể lại cho phụ huynh; không đọc lại SĐT.\n"
            f"- Mỗi tin diễn đạt mới: không lặp lại câu/khuôn câu em vừa gửi ở tin trước; không chép nguyên câu ví dụ trong hướng dẫn.\n"
            f"- Kết thúc bằng ĐÚNG 1 bước tiếp theo cụ thể, hỏi mềm, không thúc ép, câu kết trọn ý: xin SĐT/Zalo ('nếu tiện…'), "
            f"mời tham quan/học thử dạng hỏi ý ('không biết Ba/Mẹ có muốn … không ạ?') kèm [QUICK:trial_invite]/[QUICK:visit_invite], "
            f"hoặc hỏi tuổi bé/cơ sở còn thiếu. Chưa bắt chọn tuần/buổi: phụ huynh đã đồng ý thì mới hỏi thời gian kèm "
            f"[QUICK:trial_week]/[QUICK:visit_time]. Phụ huynh muốn tìm hiểu thêm → hỏi muốn biết thêm điều gì, chưa mời lại. "
            f"Phụ huynh đang lo lắng: đồng cảm trước rồi mới mời nhẹ nhàng.\n"
            f"- Học phí/ưu đãi: chưa biết tuổi bé + cơ sở thì không nói con số; không bịa số, không gửi bảng phí trên chat; không nêu % ưu đãi theo đợt. "
            f"[THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT] đã có SĐT, phụ huynh vừa gửi số, hoặc đã từ chối cho số → KHÔNG xin SĐT nữa.\n"
            f"- Xe bus: hiện Nhà trường chưa có tuyến xe bus; khi đủ phụ huynh đăng ký, Nhà trường sẽ mở tuyến. "
            f"Không nêu tuyến, phí, ưu đãi; mời để lại khu vực nhà + SĐT/Zalo để ghi nhận nhu cầu. Không [ESCALATE] chỉ vì xe bus.\n"
            f"- Câu ngoài lề, thông tin cụ thể KHÔNG CÓ trong Q&A (tên giáo viên cụ thể, ngày sự kiện, lịch chi tiết, kế hoạch mở rộng...), "
            f"hoặc đã từ chối cho số mà vẫn cần biết học phí → BẮT BUỘC trả lời chính xác chuỗi [ESCALATE] và KHÔNG nói gì thêm.\n"
            f"- Có [TRẠNG THÁI TƯ VẤN] thì chọn bước tiếp theo theo mục 10; 'Đã hẹn' → không hẹn lại, không cần bước tiếp theo; chỉ lúc vừa chốt mới xác nhận ngắn "
            f"tư vấn viên sẽ liên hệ; phụ huynh đổi/chốt cụ thể hơn thì trả lời thẳng ý mới thật ngắn, không lặp lại câu xác nhận trước, không tự hứa lịch trống (tư vấn viên sẽ gọi xác nhận giờ); "
            f"sau đó không nhắc lại lịch hẹn.\n"
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
            "Viết lại thành tin nhắn Messenger tiếng Việt có dấu, ngắn gọn, lịch sự, tự nhiên như người thật nhắn tin. "
            "GIỮ ĐỦ mọi dữ kiện admin đưa (ngày, giờ, con số, tên, từng mục trong danh sách), không bỏ bớt, không đổi; "
            "được dài hơn 3 câu khi cần để giữ đủ. "
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
                return await self._generate(provider, format_prompt, user_msg, [], max_tokens=ADMIN_REPLY_MAX_TOKENS)
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

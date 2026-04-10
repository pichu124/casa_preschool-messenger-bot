import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Bạn là trợ lý tư vấn tuyển sinh của hệ thống trường mầm non Casa (Casa dei Bambini). Đối tượng khách hàng là phụ huynh có con từ 1.5 đến 5 tuổi - họ rất quan tâm đến sự an toàn, yêu thương và phát triển của con. Nhiệm vụ của bạn là tư vấn thân thiện, ấm áp như một nhân viên thực sự quan tâm.

QUY TẮC VỀ NGÔN NGỮ (BẮT BUỘC):
1. LUÔN trả lời bằng tiếng Việt CÓ DẤU đầy đủ. TUYỆT ĐỐI không tiếng Việt không dấu.
2. Xưng hô: gọi phụ huynh là "mẹ" (mặc định), "ba" (nếu biết là bố), hoặc "chị/anh". Xưng "em". KHÔNG BAO GIỜ gọi "bạn", "quý khách" hay xưng "tôi/chúng tôi".
3. Dùng "dạ" đầu câu, "ạ" cuối câu, "nhé ạ" tự nhiên. Giọng điệu ấm áp, tôn trọng.
4. Gọi trẻ là "bé" hoặc "con", không gọi "cháu", "trẻ em". Khi biết tên bé thì gọi tên.

PHÂN BIỆT TIN NHẮN ĐẦU TIÊN vs TIN NHẮN TIẾP THEO:

📍 Khi là TIN NHẮN ĐẦU TIÊN (context marker [FIRST_MESSAGE] xuất hiện trong tin nhắn):
- BẮT ĐẦU bằng lời chào ấm áp và giới thiệu ngắn: "Dạ em chào mẹ ạ! Em là trợ lý tư vấn của trường mầm non Casa 🌸"
- Trả lời câu hỏi của mẹ NGẮN GỌN (2-4 câu thôi)
- Hỏi thêm về bé để tư vấn đúng: tên bé, tuổi bé, mối quan tâm chính (học phí/chương trình/cơ sở)
- KẾT THÚC bằng 1 câu hỏi mở hoặc gợi ý: "Mẹ cho em biết con nhà mình mấy tuổi để em tư vấn cụ thể hơn nhé ạ!"
- KHÔNG dội quá nhiều thông tin ngay tin nhắn đầu - mẹ sẽ bị ngợp.

📍 Khi là TIN NHẮN TIẾP THEO (không có [FIRST_MESSAGE], đã có conversation history):
- KHÔNG chào lại "em chào mẹ", đi thẳng vào trả lời: "Dạ", "Dạ vâng ạ", "Dạ con nhà mình..."
- Tham chiếu thông tin đã biết về bé (tên, tuổi) nếu có trong history
- Trả lời trực tiếp, ngắn gọn hơn
- Proactive gợi ý bước tiếp theo nếu phù hợp (tham quan, học thử, brochure...)

CÁCH TRẢ LỜI (áp dụng cho CẢ HAI loại tin nhắn):
- DỰA VÀO Q&A database bên dưới làm nền tảng. KHÔNG tự bịa thông tin ngoài Q&A.
- Hiểu Ý câu hỏi dù cách diễn đạt khác, tìm thông tin phù hợp nhất để trả lời.
- Diễn đạt lại theo ngữ cảnh, KHÔNG copy nguyên văn Q&A.
- NGẮN GỌN: tối đa 4-6 câu cho một tin nhắn (phụ huynh bận, ngại đọc dài).
- Kết hợp nhiều Q&A nếu cần, nhưng chỉ lấy ý chính.
- Đồng cảm với lo lắng của mẹ (đặc biệt bé mới đi học, bé nhỏ, mẹ lo về an toàn).

EMOJI (dùng tiết chế - tối đa 1-2 emoji/tin nhắn):
- 🌸 chào đầu, 💕 ấm áp, 👶 nói về bé nhỏ, 🏫 trường, 📅 lịch/tham quan, ☀️ tích cực
- KHÔNG dùng emoji cho chủ đề nghiêm túc (học phí, quy định, y tế)

GỢI Ý BƯỚC TIẾP THEO (CTAs) - kết câu trả lời bằng 1 gợi ý phù hợp:
- "Mẹ có muốn em sắp xếp lịch tham quan trường cho mình không ạ?"
- "Em có thể tặng mẹ 1 tuần học thử miễn phí cho bé nhé ạ?"
- "Mẹ cho em xin địa chỉ để check cơ sở gần nhất nhé ạ!"
- "Mẹ muốn em gửi thông tin học phí chi tiết qua đây không ạ?"
- KHÔNG thêm CTA khi phụ huynh đang bày tỏ lo lắng/thắc mắc cá nhân - lúc đó cần đồng cảm trước.

KHI NÀO ESCALATE (trả lời chính xác "[ESCALATE]"):
- Câu hỏi HOÀN TOÀN không liên quan trường/giáo dục/trẻ em (bitcoin, thời tiết, chính trị...).
- Hỏi về THÔNG TIN CỤ THỂ không có trong Q&A: tên giáo viên cụ thể, ngày sự kiện, lịch chi tiết, kế hoạch mở cơ sở mới, giá cả chính xác từng hệ...
- TUYỆT ĐỐI KHÔNG tự bịa. Không chắc → "[ESCALATE]".

KÈM HÌNH ẢNH:
- Nếu Q&A có dòng "Images: <url1>,<url2>" thì THÊM vào CUỐI câu trả lời chuỗi "[IMAGES:url1,url2]" (đúng format).
- Bot tự parse và gửi ảnh, KHÔNG hiển thị [IMAGES:...] cho phụ huynh.
- Chỉ thêm khi Q&A có trường Images, không tự bịa URL.

VÍ DỤ (học theo giọng điệu này):

--- TIN NHẮN ĐẦU TIÊN ---
Phụ huynh: "[FIRST_MESSAGE] cho hoi hoc phi ntn a"
Trả lời: "Dạ em chào mẹ ạ! Em là trợ lý tư vấn của trường mầm non Casa 🌸 Về học phí, mức phí sẽ tùy thuộc vào hệ học (song ngữ/quốc tế) và độ tuổi của bé ạ. Mẹ cho em biết con nhà mình mấy tuổi và mẹ đang quan tâm hệ nào để em tư vấn cụ thể nhé ạ!"

Phụ huynh: "[FIRST_MESSAGE] truong minh o dau"
Trả lời: "Dạ em chào mẹ ạ! 🌸 Trường Casa có nhiều cơ sở tại Hà Nội ạ. Mẹ cho em xin địa chỉ nhà mình để em gợi ý cơ sở gần nhất cho thuận tiện đưa đón bé nhé ạ. Con nhà mình được mấy tuổi rồi ạ?"

--- TIN NHẮN TIẾP THEO (đã biết bé 3 tuổi tên Bông) ---
Phụ huynh: "truong co day tieng anh khong"
Trả lời: "Dạ có ạ! Bé Bông 3 tuổi học ở Casa sẽ được học tiếng Anh với giáo viên nước ngoài. Hệ song ngữ bé sẽ có 1-1.5h tiếng Anh/ngày, hệ quốc tế thì giáo viên nước ngoài ở lớp cả ngày 8h30-17h ạ. Mẹ muốn em giới thiệu chi tiết hệ nào không ạ?"

--- TIN NHẮN TIẾP THEO (đồng cảm, không CTA) ---
Phụ huynh: "con em nhat nhung, em so con khong theo dc cac ban"
Trả lời: "Dạ em hiểu lo lắng của mẹ ạ 💕 Ở Casa, mỗi tuần em chỉ nhận 1 bé mới nên bé sẽ luôn có 1 cô đi kèm chăm sóc riêng lúc đầu ạ. Các cô sẽ giúp bé làm quen từ từ, không ép buộc. Mẹ yên tâm nhé, bé nhút nhát bình thường khoảng 1-2 tuần là hoà nhập tốt rồi ạ."

CƠ SỞ DỮ LIỆU Q&A:
{qa_context}
"""


@dataclass
class AIResponse:
    text: str
    should_escalate: bool
    model_used: str


class AIProvider(ABC):
    @abstractmethod
    async def generate(self, system_prompt: str, user_message: str, conversation_history: list[dict]) -> str:
        pass


class OpenAIProvider(AIProvider):
    def __init__(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def generate(self, system_prompt: str, user_message: str, conversation_history: list[dict]) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        response = await self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=1024,
            temperature=0.3,
        )
        return response.choices[0].message.content


class GroqProvider(AIProvider):
    def __init__(self):
        from groq import AsyncGroq
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    async def generate(self, system_prompt: str, user_message: str, conversation_history: list[dict]) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        response = await self.client.chat.completions.create(
            model="deepseek-r1-distill-llama-70b",
            messages=messages,
            max_tokens=1024,
            temperature=0.3,
        )
        return response.choices[0].message.content


class GroqLlamaProvider(AIProvider):
    """Fallback Groq provider using Llama model."""

    def __init__(self):
        from groq import AsyncGroq
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    async def generate(self, system_prompt: str, user_message: str, conversation_history: list[dict]) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        response = await self.client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            max_tokens=1024,
            temperature=0.3,
        )
        return response.choices[0].message.content


class MistralProvider(AIProvider):
    def __init__(self):
        from mistralai import Mistral
        self.client = Mistral(api_key=settings.MISTRAL_API_KEY)

    async def generate(self, system_prompt: str, user_message: str, conversation_history: list[dict]) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        response = await self.client.chat.complete_async(
            model="mistral-small-latest",
            messages=messages,
            max_tokens=1024,
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
        )

    async def generate(self, system_prompt: str, user_message: str, conversation_history: list[dict]) -> str:
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": user_message})

        response = await self.client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            max_tokens=1024,
            temperature=0.3,
        )
        return response.choices[0].message.content


class GeminiProvider(AIProvider):
    def __init__(self):
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY)
        self.model = genai.GenerativeModel("gemini-2.0-flash")

    async def generate(self, system_prompt: str, user_message: str, conversation_history: list[dict]) -> str:
        # Build conversation for Gemini
        full_prompt = f"{system_prompt}\n\n"
        for msg in conversation_history:
            role = "Khach hang" if msg["role"] == "user" else "Tu van vien"
            full_prompt += f"{role}: {msg['content']}\n"
        full_prompt += f"Khach hang: {user_message}\nTu van vien:"

        response = await self.model.generate_content_async(
            full_prompt,
            generation_config={"max_output_tokens": 1024, "temperature": 0.3},
        )
        return response.text


PROVIDER_MAP: dict[str, type[AIProvider]] = {
    "openai": OpenAIProvider,
    "groq": GroqProvider,
    "groq_llama": GroqLlamaProvider,
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


class AIEngine:
    def __init__(self, qa_context: str):
        self.qa_context = qa_context
        self.system_prompt = SYSTEM_PROMPT.format(qa_context=qa_context)
        self._providers: dict[str, AIProvider] = {}

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

    async def get_response(
        self,
        user_message: str,
        conversation_history: list[dict] | None = None,
        customer_context: str = "",
    ) -> AIResponse:
        """Try each model in the fallback chain until one succeeds.

        customer_context: optional string with known customer info to inject into prompt.
        """
        history = conversation_history or []

        # Detect first-time message (no prior conversation AND no prior profile)
        is_returning_customer = bool(customer_context)
        is_first_message = len(history) == 0 and not is_returning_customer
        first_marker = "[FIRST_MESSAGE] " if is_first_message else ""

        if is_first_message:
            conversation_hint = "- Đây là TIN NHẮN ĐẦU TIÊN của phụ huynh (khách mới). Hãy chào ấm áp, giới thiệu ngắn, trả lời ngắn gọn và hỏi thêm về bé.\n"
        elif is_returning_customer and len(history) == 0:
            conversation_hint = "- Đây là phụ huynh CŨ quay lại sau một thời gian. Hãy chào lại ấm áp và nhắc đến thông tin bé đã biết (VD: 'Dạ chào mẹ Bông ạ! Lâu rồi không gặp mẹ, bé Bông giờ khoẻ không ạ?'). KHÔNG hỏi lại thông tin đã biết.\n"
        else:
            conversation_hint = "- Đây là tin nhắn tiếp theo trong cuộc trò chuyện. KHÔNG chào lại 'em chào mẹ', đi thẳng vào trả lời. Tham chiếu thông tin bé đã biết nếu có.\n"

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
            f"- Trả lời bằng tiếng Việt CÓ DẤU, xưng 'em', gọi 'mẹ/ba/chị/anh', dùng 'ạ'\n"
            f"- NGẮN GỌN 2-5 câu, không lan man. Kết bằng 1 câu hỏi mở hoặc gợi ý bước tiếp theo (trừ khi phụ huynh đang bày tỏ lo lắng).\n"
            f"- Nếu câu hỏi này HỎI VỀ THÔNG TIN KHÔNG CÓ trong Q&A database (tên giáo viên cụ thể, ngày sự kiện, lịch trình, kế hoạch mở rộng, dịch vụ không được đề cập...) → BẮT BUỘC trả lời chính xác chuỗi [ESCALATE] và KHÔNG nói gì thêm.\n"
            f"- KHÔNG BAO GIỜ tự suy đoán hoặc bịa thông tin. Chỉ dùng thông tin CÓ TRONG Q&A."
        )

        for model_name in settings.AI_MODEL_ORDER:
            model_name = model_name.strip()
            provider = self._get_provider(model_name)
            if not provider:
                continue

            try:
                logger.info(f"Trying model: {model_name}")
                response_text = await provider.generate(
                    self.system_prompt, wrapped_message, history
                )

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

    async def extract_customer_info(self, user_message: str, existing_profile: dict | None = None) -> dict:
        """Extract customer/kid information from user message.

        Returns dict with keys (only non-empty ones are included):
        kid_name, kid_age, kid_gender, parent_name, address, phone,
        interested_program, interested_campus, concerns, kid_traits
        """
        existing_context = ""
        if existing_profile:
            existing_context = f"\nThông tin đã biết: {json.dumps(existing_profile, ensure_ascii=False)}\n"

        extract_prompt = (
            "Bạn là hệ thống trích xuất thông tin từ tin nhắn phụ huynh gửi trường mầm non. "
            "Phân tích tin nhắn và trả về JSON với các trường sau (CHỈ thêm trường khi tin nhắn CÓ đề cập rõ ràng, KHÔNG đoán):\n"
            '- "kid_name": tên bé (VD: "Bông", "Minh")\n'
            '- "kid_age": tuổi bé (VD: "3 tuổi", "18 tháng")\n'
            '- "kid_gender": "bé trai" hoặc "bé gái"\n'
            '- "parent_name": tên phụ huynh\n'
            '- "address": địa chỉ\n'
            '- "phone": số điện thoại\n'
            '- "interested_program": "song ngữ" / "quốc tế" / "Montessori"\n'
            '- "interested_campus": "Chùa Láng" / "Mỹ Đình" / "Kim Mã"\n'
            '- "concerns": list các mối quan tâm (VD: ["học phí", "an toàn", "ăn uống"])\n'
            '- "kid_traits": list tính cách/đặc điểm bé (VD: ["nhút nhát", "hiếu động", "biếng ăn"])\n\n'
            "CHỈ trả về JSON object. Nếu tin nhắn không chứa thông tin mới nào, trả về {}. "
            "KHÔNG giải thích, KHÔNG markdown code block."
        )
        user_msg = f"Tin nhắn phụ huynh: {user_message}{existing_context}"

        for model_name in settings.AI_MODEL_ORDER:
            model_name = model_name.strip()
            provider = self._get_provider(model_name)
            if not provider:
                continue
            try:
                result = await provider.generate(extract_prompt, user_msg, [])
                # Clean up response
                result = result.strip()
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

    async def format_admin_reply(self, admin_answer: str, original_question: str) -> str:
        """Use AI to format an admin's raw reply into a polite customer response."""
        format_prompt = (
            "Bạn là nhân viên tư vấn trường mầm non Casa. "
            "Admin đã cung cấp câu trả lời cho câu hỏi của phụ huynh. "
            "Hãy viết lại câu trả lời sao cho lịch sự, thân thiện, có dấu tiếng Việt, "
            "xưng 'em', gọi phụ huynh là 'mẹ/ba/chị/anh', dùng 'ạ' cuối câu. "
            "Giữ nguyên ý nghĩa, không thêm thông tin mới."
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
                return await provider.generate(format_prompt, user_msg, [])
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
                result = await provider.generate(classify_prompt, user_msg, [])
                # Extract JSON from response
                result = result.strip()
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

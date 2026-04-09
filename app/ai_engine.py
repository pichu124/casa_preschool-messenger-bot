import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Bạn là nhân viên tư vấn của hệ thống trường mầm non Casa. Nhiệm vụ của bạn là trả lời câu hỏi của phụ huynh một cách thân thiện, chuyên nghiệp và tự nhiên.

QUY TẮC BẮT BUỘC:
1. LUÔN LUÔN trả lời bằng tiếng Việt CÓ DẤU. TUYỆT ĐỐI không bao giờ trả lời tiếng Việt không dấu. Mọi ký tự tiếng Việt phải có đầy đủ dấu thanh và dấu mũ.
2. Xưng hô LỄ PHÉP: luôn gọi phụ huynh là "ba/mẹ" hoặc "anh/chị", xưng "em". KHÔNG BAO GIỜ gọi "bạn" hay xưng "tôi/chúng tôi". Đây là phụ huynh - ba mẹ các bé, cần tôn trọng tối đa.
3. Giọng điệu: lễ phép, ấm áp, chu đáo như nhân viên tư vấn chuyên nghiệp. Luôn dùng "ạ" cuối câu, "dạ" đầu câu khi phù hợp, "nhé ạ", "nha ạ" để thể hiện sự tôn trọng.
4. Mở đầu câu trả lời tự nhiên, ví dụ: "Dạ", "Dạ thưa ba/mẹ", "Dạ chào mẹ ạ".

CÁCH TRẢ LỜI:
- Dưới đây là cơ sở dữ liệu Q&A chứa thông tin về trường. Hãy SỬ DỤNG thông tin này làm NỀN TẢNG để trả lời.
- Câu hỏi của phụ huynh có thể KHÔNG GIỐNG HỆT câu hỏi trong Q&A. Hãy HIỂU Ý phụ huynh muốn hỏi gì và tìm thông tin liên quan nhất để trả lời.
- KHÔNG cần copy nguyên văn câu trả lời trong Q&A. Hãy diễn đạt lại cho PHÙ HỢP với ngữ cảnh và câu hỏi cụ thể của phụ huynh.
- Nếu phụ huynh cung cấp thông tin cá nhân (tên con, tuổi, địa chỉ...), hãy ghi nhận và tư vấn phù hợp.
- Có thể KẾT HỢP thông tin từ NHIỀU câu Q&A khác nhau để trả lời một câu hỏi nếu cần.
- Trả lời ngắn gọn, đúng trọng tâm, không lan man.

KHI NÀO CHUYỂN CHO BỘ PHẬN TƯ VẤN:
- CHỈ trả lời "[ESCALATE]" khi câu hỏi HOÀN TOÀN không liên quan đến trường học, giáo dục, chăm sóc trẻ (ví dụ: hỏi về bitcoin, thời tiết, chính trị...).
- Nếu câu hỏi liên quan đến trường nhưng bạn không có đủ thông tin chi tiết, hãy trả lời những gì bạn biết và gợi ý phụ huynh liên hệ trực tiếp để được tư vấn cụ thể hơn. KHÔNG escalate trong trường hợp này.

VÍ DỤ CÁCH TRẢ LỜI ĐÚNG (hãy học theo giọng điệu này):
- Phụ huynh: "cho hoi hoc phi ntn a"
  Trả lời: "Dạ chào mẹ ạ! Về học phí thì tùy vào chương trình học mà mức phí sẽ khác nhau ạ. Mẹ cho em biết con nhà mình bao nhiêu tuổi và mẹ quan tâm hệ song ngữ hay quốc tế để em tư vấn cụ thể hơn nhé ạ!"

- Phụ huynh: "con toi 2 tuoi co hoc duoc khong"
  Trả lời: "Dạ, con nhà mình 2 tuổi là hoàn toàn phù hợp để đi học rồi ạ! Trường mình nhận các bé từ 15 tháng tuổi biết đi. Lớp 0-3 tuổi sẽ có 23-25 bé với 4 cô chăm sóc nên mẹ yên tâm nhé ạ. Mẹ có muốn đăng ký cho bé học thử 1 tuần không ạ?"

- Phụ huynh: "truong co camera khong"
  Trả lời: "Dạ thưa mẹ, mẹ có thể xem camera tại văn phòng trường ạ. Để đảm bảo tính bảo mật và sự riêng tư của các con nên nhà trường không online camera, tuy nhiên các cô sẽ thường xuyên cập nhật tình hình con qua app liên lạc để ba mẹ yên tâm ạ."

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
    ) -> AIResponse:
        """Try each model in the fallback chain until one succeeds."""
        history = conversation_history or []

        # Wrap user message with a reminder to enforce Vietnamese with diacritics
        wrapped_message = (
            f"[Phụ huynh hỏi]: {user_message}\n\n"
            f"[NHẮC NHỞ: Trả lời bằng tiếng Việt CÓ DẤU, xưng 'em', gọi phụ huynh là 'mẹ/ba/chị/anh', dùng 'ạ' cuối câu, KHÔNG gọi 'bạn', KHÔNG xưng 'tôi']"
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

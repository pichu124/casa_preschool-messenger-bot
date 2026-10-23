"""Bot không chào lại giữa cuộc trò chuyện và không hỏi lại điều đã biết (phản hồi của trường, đợt 7).

process_message thật cộng AIEngine.get_response thật; model chat ghi lại tin gửi nó, model trích xuất trả theo kịch
bản, Messenger và Telegram giả. Lời chào tin đầu chỉ có khi chưa có lịch sử (hoặc khách cũ quay lại sau ≥ 24 giờ),
nên phụ huynh chỉ bị chào lại, hỏi lại khi bot mất hồ sơ và lịch sử, hoặc khi hai tin liền nhau được trả lời cùng lúc
(cả hai đọc lịch sử từ trước tin đầu).
"""
import asyncio
from datetime import datetime, timedelta

import pytest

import app.main as main
from app import customer_memory
from app.ai_engine import AIProvider
from app.config import settings

CUSTOMER_ID = "9000000000000701"
PHONE = "0900000701"
GREETING = "Dạ Casa chào Ba/Mẹ ạ"
REPLY = "Dạ học phí tùy độ tuổi của bé và cơ sở ạ. Bé nhà mình được mấy tuổi rồi ạ?"


class ChatModel(AIProvider):
    """Model chat ghi lại tin gửi nó; model trích xuất (nhận diện qua câu mở đầu prompt) trả `extracted`."""

    def __init__(self):
        self.messages = []
        self.extracted = "{}"

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024) -> str:
        if system_prompt.startswith("Bạn là hệ thống trích xuất"):
            return self.extracted
        self.messages.append(user_message)
        return REPLY


@pytest.fixture
def model(monkeypatch):
    model = ChatModel()

    async def nothing(*args, **kwargs):
        return {}

    monkeypatch.setattr(settings, "AI_MODEL_ORDER", ["chat"])
    monkeypatch.setattr(main.ai_engine, "_providers", {"chat": model})
    for name in ("send_message", "send_typing_indicator", "get_user_profile"):
        monkeypatch.setattr(main, name, nothing)
    monkeypatch.setattr(customer_memory, "sync_to_github", nothing)
    return model


def say(model, text, extracted="{}"):
    model.extracted = extracted
    asyncio.run(main.process_message(CUSTOMER_ID, text))
    return model.messages[-1]


CONTINUING = "- Đây là tin nhắn tiếp theo trong cuộc trò chuyện. KHÔNG chào lại, đi thẳng vào trả lời."


def parts(message: str) -> tuple[str, str, list[str]]:
    """(khối thông tin khách, dòng "[Phụ huynh hỏi]", các dòng nhắc nhở) của tin gửi model chat."""
    context, rest = message.split("[Phụ huynh hỏi]: ", 1)
    asked, reminder = rest.split("\n\n[NHẮC NHỞ QUAN TRỌNG]:\n", 1)
    return context, asked, reminder.splitlines()


def test_known_campus_and_phone_are_kept_and_not_asked_again_mid_conversation(model):
    _, asked, reminder = parts(say(model, "cho mình hỏi học phí"))
    assert asked == "[FIRST_MESSAGE] cho mình hỏi học phí" and GREETING in reminder[0]

    say(model, f"bé 3 tuổi, mình quan tâm Mỹ Đình, số mình {PHONE}", '{"kid_age": "3 tuổi", "interested_campus": "Mỹ Đình"}')
    for hours_later in (0, 5):
        profile = customer_memory._customers[CUSTOMER_ID]
        profile["last_seen"] = (datetime.now() - timedelta(hours=hours_later)).isoformat()
        context, asked, reminder = parts(say(model, "học phí bên đó thế nào ạ"))

        assert asked == "học phí bên đó thế nào ạ"
        assert reminder[0] == CONTINUING
        assert "- Cơ sở quan tâm: Mỹ Đình" in context and f"- SĐT: {PHONE}" in context
        assert "Còn thiếu" not in context
        assert any("không hỏi lại" in line for line in reminder)


def test_parent_is_greeted_and_asked_again_only_once_the_bot_has_lost_their_profile(model):
    # Render gói Free: máy chủ ngủ hoặc khởi động lại thì data/customers.json chỉ còn bản trong image (hoặc bản trên
    # CUSTOMERS_GITHUB_REPO nếu có đặt); hồ sơ và lịch sử mất thì phụ huynh đang nói dở là khách mới.
    say(model, f"bé 3 tuổi, mình quan tâm Mỹ Đình, số mình {PHONE}", '{"kid_age": "3 tuổi", "interested_campus": "Mỹ Đình"}')
    customer_memory._customers.clear()

    context, asked, reminder = parts(say(model, "học phí bên đó thế nào ạ"))

    assert asked == "[FIRST_MESSAGE] học phí bên đó thế nào ạ" and GREETING in reminder[0]
    assert context == ""


class SlowChatModel(ChatModel):
    """Trả lời sau một nhịp, như model thật mất vài giây: tin thứ hai của phụ huynh tới khi tin đầu còn đang xử lý."""

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024) -> str:
        await asyncio.sleep(0.05)
        return await super().generate(system_prompt, user_message, conversation_history, max_tokens)


def test_two_quick_messages_are_answered_in_turn_so_the_second_is_not_a_first_message(monkeypatch, model):
    slow = SlowChatModel()
    monkeypatch.setattr(main.ai_engine, "_providers", {"chat": slow})

    async def two_messages():
        await asyncio.gather(
            main.process_message(CUSTOMER_ID, "chào em"), main.process_message(CUSTOMER_ID, "cho mình hỏi học phí")
        )

    asyncio.run(two_messages())

    asked = [parts(m)[1] for m in slow.messages]
    assert asked == ["[FIRST_MESSAGE] chào em", "cho mình hỏi học phí"]

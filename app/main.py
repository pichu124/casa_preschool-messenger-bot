import logging
from collections import defaultdict

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app.config import settings
from app.qa_database import QADatabase
from app.ai_engine import AIEngine
from app.messenger import (
    send_message,
    send_typing_indicator,
    get_user_profile,
    verify_webhook_signature,
)
from app.escalation import escalate_to_admin, get_pending_escalation, resolve_escalation, send_telegram_reply

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Preschool Messenger Bot", version="1.0.0")

# Initialize Q&A database and AI engine
qa_db = QADatabase(settings.QA_DATABASE_PATH)
ai_engine = AIEngine(qa_context=qa_db.build_context())

# Simple in-memory conversation history (user_id -> list of messages)
# In production, use Redis or a database
conversation_history: dict[str, list[dict]] = defaultdict(list)
MAX_HISTORY = 10  # Keep last N messages per user

ESCALATION_MESSAGE = (
    "Dạ, cảm ơn ba/mẹ đã liên hệ với trường ạ! "
    "Câu hỏi của mình đã được chuyển đến bộ phận tư vấn. "
    "Bộ phận tư vấn sẽ phản hồi mình trong thời gian sớm nhất nhé ạ!"
)


@app.get("/")
async def health_check():
    return {
        "status": "ok",
        "qa_pairs": len(qa_db.qa_pairs),
        "ai_models": settings.AI_MODEL_ORDER,
    }


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Facebook webhook verification endpoint."""
    if hub_mode == "subscribe" and hub_verify_token == settings.FB_VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/webhook")
async def handle_webhook(request: Request):
    """Handle incoming messages from Facebook Messenger."""
    body = await request.body()
    logger.info(f"Webhook POST received, body length: {len(body)}")

    # Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if settings.FB_APP_SECRET and not verify_webhook_signature(body, signature):
        logger.error(f"Invalid signature: {signature[:20]}...")
        raise HTTPException(status_code=403, detail="Invalid signature")

    data = await request.json()
    logger.info(f"Webhook data: object={data.get('object')}")

    if data.get("object") != "page":
        return {"status": "ignored"}

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            message = event.get("message", {})
            text = message.get("text")

            if not sender_id or not text:
                continue

            # Don't respond to echo messages (sent by the page itself)
            if message.get("is_echo"):
                continue

            # Process message in background-like fashion
            await process_message(sender_id, text)

    return {"status": "ok"}


async def process_message(sender_id: str, text: str):
    """Process an incoming message and respond."""
    try:
        # Show typing indicator
        await send_typing_indicator(sender_id)

        # Get user profile for personalization
        profile = await get_user_profile(sender_id)
        user_name = profile.get("first_name", "ban")

        # Get conversation history for this user
        history = conversation_history[sender_id]

        # Get AI response
        response = await ai_engine.get_response(
            user_message=text,
            conversation_history=history,
        )

        logger.info(
            f"User {sender_id} ({user_name}): {text[:100]} "
            f"-> Model: {response.model_used}, Escalate: {response.should_escalate}"
        )

        if response.should_escalate or not response.text:
            # Escalate to admin
            await escalate_to_admin(
                customer_id=sender_id,
                customer_name=f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip(),
                question=text,
            )
            await send_message(sender_id, ESCALATION_MESSAGE)
        else:
            await send_message(sender_id, response.text)

        # Update conversation history
        history.append({"role": "user", "content": text})
        if response.text:
            history.append({"role": "assistant", "content": response.text})

        # Trim history
        if len(history) > MAX_HISTORY * 2:
            conversation_history[sender_id] = history[-MAX_HISTORY * 2:]

    except Exception as e:
        logger.error(f"Error processing message from {sender_id}: {e}", exc_info=True)
        try:
            await send_message(
                sender_id,
                "Xin loi, he thong dang gap su co. Vui long thu lai sau it phut.",
            )
        except Exception:
            pass


@app.post("/reload-qa")
async def reload_qa():
    """Reload Q&A database (call after updating qa_database.json)."""
    qa_db.reload()
    _rebuild_ai_context()
    return {"status": "reloaded", "qa_pairs": len(qa_db.qa_pairs)}


@app.get("/qa-database")
async def get_qa_database():
    """View all Q&A pairs including learned ones."""
    return {
        "total": len(qa_db.qa_pairs),
        "qa_pairs": qa_db.qa_pairs,
    }


@app.get("/qa-learned")
async def get_qa_learned():
    """View only Q&A pairs learned from admin replies."""
    learned = [p for p in qa_db.qa_pairs if p.get("category") == "Học từ admin"]
    return {
        "total": len(learned),
        "learned_pairs": learned,
    }


@app.post("/import-excel")
async def import_excel(file_path: str):
    """Import Q&A from Excel file."""
    try:
        qa_db.import_from_excel(file_path)
        from app.ai_engine import SYSTEM_PROMPT
        ai_engine.system_prompt = SYSTEM_PROMPT.format(qa_context=qa_db.build_context())
        ai_engine._providers.clear()
        return {"status": "imported", "qa_pairs": len(qa_db.qa_pairs)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


from pydantic import BaseModel


class TestMessage(BaseModel):
    message: str
    user_id: str = "test_user"


@app.post("/test-chat")
async def test_chat(body: TestMessage):
    """Test AI response without Facebook (for development/debugging)."""
    history = conversation_history[body.user_id]

    response = await ai_engine.get_response(
        user_message=body.message,
        conversation_history=history,
    )

    history.append({"role": "user", "content": body.message})
    if response.text:
        history.append({"role": "assistant", "content": response.text})
    if len(history) > MAX_HISTORY * 2:
        conversation_history[body.user_id] = history[-MAX_HISTORY * 2:]

    return {
        "response": response.text,
        "model_used": response.model_used,
        "should_escalate": response.should_escalate,
    }


def _rebuild_ai_context():
    """Rebuild AI engine system prompt with updated Q&A context."""
    from app.ai_engine import SYSTEM_PROMPT
    ai_engine.system_prompt = SYSTEM_PROMPT.format(qa_context=qa_db.build_context())
    ai_engine._providers.clear()


@app.post("/telegram-webhook")
async def handle_telegram_webhook(request: Request):
    """Handle admin replies from Telegram group."""
    data = await request.json()
    message = data.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    reply_msg_id = message.get("message_id")

    try:
        # Only process replies to bot messages
        reply = message.get("reply_to_message")
        if not reply:
            return {"status": "ignored"}

        original_msg_id = reply.get("message_id")
        logger.info(f"Telegram reply to msg_id={original_msg_id}")

        # Check if this is a reply to an escalation message
        escalation = get_pending_escalation(original_msg_id)
        if not escalation:
            # Try to parse customer info from the original bot message text
            original_text = reply.get("text", "")
            logger.warning(f"No pending escalation for msg_id={original_msg_id}, trying to parse from message")

            # Extract customer ID and question from the escalation message
            import re
            customer_id = None
            customer_name = "Khách hàng"
            question = ""

            # Parse ID (after "ID:" or "🆔 ID:")
            id_match = re.search(r"ID:\s*(\d+)", original_text)
            if id_match:
                customer_id = id_match.group(1)

            # Parse customer name (after "Khách hàng:" or "👤 Khách hàng:")
            name_match = re.search(r"Khách hàng:\s*(.+)", original_text)
            if name_match:
                customer_name = name_match.group(1).strip()

            # Parse question (after "Câu hỏi:" - could be on same or next line)
            q_match = re.search(r"Câu hỏi:\s*\n?(.*?)(?:\n\n|\n🕐|\n💬|$)", original_text, re.DOTALL)
            if q_match:
                question = q_match.group(1).strip()

            logger.info(f"Parsed from message: customer_id={customer_id}, name={customer_name}, question={question[:50]}")

            if not customer_id or not question:
                await send_telegram_reply(chat_id, reply_msg_id, "❌ Không tìm thấy thông tin khách hàng. Hãy reply đúng tin nhắn escalation.")
                return {"status": "no_escalation_found"}
        else:
            customer_id = escalation["customer_id"]
            customer_name = escalation["customer_name"]
            question = escalation["question"]

        admin_text = message.get("text", "")
        if not admin_text:
            return {"status": "no_text"}

        # 1. Format admin reply politely via AI
        formatted_reply = await ai_engine.format_admin_reply(admin_text, question)

        # 2. Send to customer on Facebook Messenger
        try:
            await send_message(customer_id, formatted_reply)
        except Exception as send_err:
            logger.error(f"Failed to send to Messenger (customer_id={customer_id}): {send_err}")
            await send_telegram_reply(chat_id, reply_msg_id, f"❌ Không gửi được cho khách (ID: {customer_id}). Lỗi: {send_err}")
            return {"status": "messenger_error"}

        # 3. Classify Q&A with AI (category, keywords, similar questions)
        classification = await ai_engine.classify_qa(question, admin_text)
        category = classification.get("category", "Khác")
        keywords = classification.get("keywords", [])
        similar_questions = classification.get("similar_questions", [])

        # 4. Save new Q&A to database with proper classification
        all_questions = [question] + similar_questions
        await qa_db.add_qa_pair(category, all_questions, admin_text, keywords)

        # 5. Rebuild AI context so it knows the new Q&A
        _rebuild_ai_context()

        # 6. Confirm in Telegram
        await send_telegram_reply(
            chat_id, reply_msg_id,
            f"✅ Đã gửi cho khách hàng ({customer_name}) và lưu vào Q&A database.\n📁 Danh mục: {category}\n🔑 Keywords: {', '.join(keywords)}"
        )

        # 7. Mark escalation as resolved
        if escalation:
            resolve_escalation(original_msg_id)

        logger.info(f"Admin replied to escalation for {customer_name}: {admin_text[:100]}")
        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error handling admin reply: {e}", exc_info=True)
        if chat_id and reply_msg_id:
            await send_telegram_reply(chat_id, reply_msg_id, f"❌ Lỗi: {str(e)}")
        return {"status": "error", "detail": str(e)}


@app.post("/setup-telegram-webhook")
async def setup_telegram_webhook():
    """Register Telegram webhook URL."""
    import httpx
    webhook_url = f"https://casa-preschool-messenger-bot.onrender.com/telegram-webhook"
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setWebhook"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={
            "url": webhook_url,
            "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
        })
        return response.json()

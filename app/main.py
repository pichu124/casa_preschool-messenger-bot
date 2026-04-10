import logging
import re
from collections import defaultdict

from fastapi import FastAPI, Request, HTTPException, Query, BackgroundTasks
from fastapi.responses import PlainTextResponse

from app.config import settings
from app.qa_database import QADatabase
from app.ai_engine import AIEngine
from app.messenger import (
    send_message,
    send_image,
    send_typing_indicator,
    get_user_profile,
    verify_webhook_signature,
)
from app.escalation import escalate_to_admin, get_pending_escalation, resolve_escalation, send_telegram_reply
from app import analytics

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

APP_VERSION = "1.4.0"
app = FastAPI(title="Preschool Messenger Bot", version=APP_VERSION)

# Initialize Q&A database and AI engine
qa_db = QADatabase(settings.QA_DATABASE_PATH)
ai_engine = AIEngine(qa_context=qa_db.build_context())

# Simple in-memory conversation history (user_id -> list of messages)
conversation_history: dict[str, list[dict]] = defaultdict(list)
MAX_HISTORY = 10  # Keep last N messages per user

# Dedup: track processed message IDs to prevent duplicates
_processed_fb_mids: set[str] = set()
_processed_tg_mids: set[int] = set()
MAX_DEDUP_SIZE = 500

ESCALATION_MESSAGE = (
    "Dạ, cảm ơn ba/mẹ đã liên hệ với trường ạ! "
    "Câu hỏi của mình đã được chuyển đến bộ phận tư vấn. "
    "Bộ phận tư vấn sẽ phản hồi mình trong thời gian sớm nhất nhé ạ!"
)


@app.get("/")
async def health_check():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "qa_pairs": len(qa_db.qa_pairs),
        "ai_models": settings.AI_MODEL_ORDER,
    }


@app.get("/dashboard")
async def dashboard():
    """Serve analytics dashboard HTML."""
    from pathlib import Path
    from fastapi.responses import HTMLResponse
    dashboard_path = Path(__file__).parent / "dashboard.html"
    if dashboard_path.exists():
        return HTMLResponse(dashboard_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="Dashboard not found")


@app.get("/analytics/stats")
async def analytics_stats():
    """Return analytics statistics as JSON."""
    return analytics.get_stats()


@app.get("/analytics/messages")
async def analytics_messages(limit: int = 20):
    """Return recent messages as JSON."""
    return analytics.get_recent_messages(limit=limit)


@app.post("/analytics/reset")
async def analytics_reset(secret: str = ""):
    """Delete all analytics data. Requires secret to prevent abuse."""
    if secret != settings.TELEGRAM_WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret")
    from pathlib import Path
    path = Path(settings.ANALYTICS_LOG_PATH)
    if path.exists():
        path.unlink()
    return {"status": "reset", "message": "Analytics data cleared"}


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
async def handle_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle incoming messages from Facebook Messenger.

    Returns 200 immediately and processes messages in background
    to prevent Facebook from retrying (which causes duplicate replies
    when Render wakes up from sleep).
    """
    body = await request.body()

    # Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if settings.FB_APP_SECRET and not verify_webhook_signature(body, signature):
        logger.error(f"Invalid signature: {signature[:20]}...")
        raise HTTPException(status_code=403, detail="Invalid signature")

    data = await request.json()

    if data.get("object") != "page":
        return {"status": "ignored"}

    for entry in data.get("entry", []):
        for event in entry.get("messaging", []):
            sender_id = event.get("sender", {}).get("id")
            message = event.get("message", {})
            text = message.get("text")

            if not sender_id or not text:
                continue

            # Don't respond to echo messages
            if message.get("is_echo"):
                continue

            # Dedup: skip if already processed
            mid = message.get("mid", "")
            if mid and mid in _processed_fb_mids:
                logger.info(f"Skipping duplicate FB message: {mid}")
                continue
            if mid:
                _processed_fb_mids.add(mid)
                if len(_processed_fb_mids) > MAX_DEDUP_SIZE:
                    _processed_fb_mids.clear()

            # Process in background so webhook returns 200 immediately
            background_tasks.add_task(process_message, sender_id, text)

    return {"status": "ok"}


IMAGES_PATTERN = re.compile(r"\[IMAGES:([^\]]+)\]")


def _extract_images(text: str) -> tuple[str, list[str]]:
    """Parse [IMAGES:url1,url2] token from response text.

    Returns (clean_text, list_of_urls).
    """
    images = []
    match = IMAGES_PATTERN.search(text)
    if match:
        raw = match.group(1)
        images = [url.strip() for url in raw.split(",") if url.strip()]
        text = IMAGES_PATTERN.sub("", text).strip()
    return text, images


def _guess_category(question: str, answer: str = "") -> str:
    """Guess the Q&A category by matching the user's question against keywords + questions in database.

    Returns the best matching category, or empty string if no match.
    """
    if not question:
        return ""

    q_lower = question.lower()
    best_score = 0
    best_category = ""

    for pair in qa_db.qa_pairs:
        category = pair.get("category", "")
        if not category:
            continue
        score = 0

        # Match against keywords (each match = 2 points)
        for kw in pair.get("keywords", []):
            if kw and kw.lower() in q_lower:
                score += 2

        # Match against stored questions (substring match = 3 points)
        for stored_q in pair.get("questions", []):
            if not stored_q:
                continue
            stored_lower = stored_q.lower()
            # Count common significant words (length > 3)
            q_words = set(w for w in q_lower.split() if len(w) > 3)
            stored_words = set(w for w in stored_lower.split() if len(w) > 3)
            common = q_words & stored_words
            score += len(common)

        if score > best_score:
            best_score = score
            best_category = category

    return best_category if best_score >= 2 else ""


async def process_message(sender_id: str, text: str):
    """Process an incoming message and respond."""
    try:
        # Show typing indicator
        await send_typing_indicator(sender_id)

        # Get user profile for personalization
        profile = await get_user_profile(sender_id)
        user_name = profile.get("first_name", "ban")
        full_name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()

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

        category = ""
        if response.should_escalate or not response.text:
            # Escalate to admin
            await escalate_to_admin(
                customer_id=sender_id,
                customer_name=full_name,
                question=text,
            )
            await send_message(sender_id, ESCALATION_MESSAGE)
        else:
            # Parse images from AI response
            clean_text, image_urls = _extract_images(response.text)
            category = _guess_category(text)

            if clean_text:
                await send_message(sender_id, clean_text)
            for img_url in image_urls:
                try:
                    await send_image(sender_id, img_url)
                except Exception as img_err:
                    logger.error(f"Failed to send image {img_url}: {img_err}")

        # Log analytics
        try:
            analytics.log_message(
                user_id=sender_id,
                user_name=full_name or user_name,
                question=text,
                model_used=response.model_used,
                escalated=response.should_escalate,
                category=category,
            )
        except Exception as log_err:
            logger.warning(f"Analytics logging failed: {log_err}")

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

    # Parse all variables before try block so they exist in except
    customer_id = None
    customer_name = "Khách hàng"
    question = ""
    admin_text = ""

    try:
        # Only process replies to bot messages
        reply = message.get("reply_to_message")
        if not reply:
            return {"status": "ignored"}

        # Dedup: skip if already processed
        tg_mid = message.get("message_id", 0)
        if tg_mid and tg_mid in _processed_tg_mids:
            logger.info(f"Skipping duplicate TG message: {tg_mid}")
            return {"status": "duplicate"}
        if tg_mid:
            _processed_tg_mids.add(tg_mid)
            if len(_processed_tg_mids) > MAX_DEDUP_SIZE:
                _processed_tg_mids.clear()

        original_msg_id = reply.get("message_id")
        admin_text = message.get("text", "")
        if not admin_text:
            return {"status": "no_text"}

        logger.info(f"Telegram reply to msg_id={original_msg_id}, text={admin_text[:50]}")

        # Check if this is a reply to an escalation message
        escalation = get_pending_escalation(original_msg_id)
        if escalation:
            customer_id = escalation.get("customer_id")
            customer_name = escalation.get("customer_name", "Khách hàng")
            question = escalation.get("question", "")
        else:
            # Parse customer info from the original bot message text
            original_text = reply.get("text", "")
            logger.warning(f"No pending escalation for msg_id={original_msg_id}, parsing from message")

            id_match = re.search(r"ID:\s*(\d+)", original_text)
            if id_match:
                customer_id = id_match.group(1)

            name_match = re.search(r"Khách hàng:\s*(.+)", original_text)
            if name_match:
                customer_name = name_match.group(1).strip()

            q_match = re.search(r"Câu hỏi:\s*\n?(.*?)(?:\n\n|\n🕐|\n💬|$)", original_text, re.DOTALL)
            if q_match:
                question = q_match.group(1).strip()

        logger.info(f"Escalation data: customer_id={customer_id}, name={customer_name}, question={question[:50]}")

        if not customer_id or not question:
            return {"status": "no_escalation_found"}

        # 1. Format admin reply politely via AI
        formatted_reply = await ai_engine.format_admin_reply(admin_text, question)

        # 2. Send to customer on Facebook Messenger
        await send_message(customer_id, formatted_reply)

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

        # 6. Mark escalation as resolved
        if escalation:
            resolve_escalation(original_msg_id)

        logger.info(f"Admin replied to escalation for {customer_name}: {admin_text[:100]}")
        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error handling admin reply: {e}", exc_info=True)
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

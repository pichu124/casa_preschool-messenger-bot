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
from app.escalation import escalate_to_admin

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

    # Verify signature
    signature = request.headers.get("X-Hub-Signature-256", "")
    if settings.FB_APP_SECRET and not verify_webhook_signature(body, signature):
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
    ai_engine.qa_context = qa_db.build_context()
    ai_engine.system_prompt = ai_engine.system_prompt.__class__(
        ai_engine.system_prompt
    )
    # Rebuild system prompt with new context
    from app.ai_engine import SYSTEM_PROMPT
    ai_engine.system_prompt = SYSTEM_PROMPT.format(qa_context=qa_db.build_context())
    ai_engine._providers.clear()
    return {"status": "reloaded", "qa_pairs": len(qa_db.qa_pairs)}


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

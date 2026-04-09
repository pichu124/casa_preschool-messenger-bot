import json
import logging
from datetime import datetime
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ESCALATION_LOG_PATH = "data/escalation_log.json"
PENDING_ESCALATIONS_PATH = "data/pending_escalations.json"

# In-memory mapping: telegram_message_id -> escalation info
_pending: dict[int, dict] = {}


def _load_pending():
    """Load pending escalations from disk."""
    global _pending
    path = Path(PENDING_ESCALATIONS_PATH)
    if path.exists():
        try:
            _pending = {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}
        except (json.JSONDecodeError, ValueError):
            _pending = {}


def _save_pending():
    """Save pending escalations to disk."""
    path = Path(PENDING_ESCALATIONS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_pending, ensure_ascii=False, indent=2), encoding="utf-8")


# Load on import
_load_pending()


async def escalate_to_admin(
    customer_id: str,
    customer_name: str,
    question: str,
    page_name: str = "",
) -> bool:
    """Send escalated question to Telegram group and track for admin reply."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.error("Telegram escalation not configured")
        return False

    message = (
        f"⚠️ CẦN TRỢ GIÚP ⚠️\n\n"
        f"👤 Khách hàng: {customer_name}\n"
        f"🆔 ID: {customer_id}\n"
        f"📄 Trang: {page_name}\n\n"
        f"❓ Câu hỏi:\n{question}\n\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"💬 Reply tin nhắn này để trả lời khách hàng."
    )

    try:
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": message,
                },
                timeout=10,
            )
            if response.status_code != 200:
                logger.error(f"Telegram API error: {response.status_code} {response.text}")
                return False

            # Save mapping: telegram_message_id -> customer info
            result = response.json()
            telegram_msg_id = result["result"]["message_id"]
            _pending[telegram_msg_id] = {
                "customer_id": customer_id,
                "customer_name": customer_name,
                "question": question,
                "timestamp": datetime.now().isoformat(),
            }
            _save_pending()

        logger.info(f"Escalated to Telegram (msg_id={telegram_msg_id}) from {customer_name}")
        _log_escalation(customer_id, customer_name, question)
        return True
    except Exception as e:
        logger.error(f"Failed to escalate to Telegram: {e}")
        return False


def get_pending_escalation(telegram_msg_id: int) -> dict | None:
    """Look up a pending escalation by Telegram message ID."""
    return _pending.get(telegram_msg_id)


def resolve_escalation(telegram_msg_id: int):
    """Remove a resolved escalation from pending."""
    if telegram_msg_id in _pending:
        del _pending[telegram_msg_id]
        _save_pending()


async def send_telegram_reply(chat_id: str | int, reply_to_msg_id: int, text: str):
    """Send a reply message in Telegram."""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
                "reply_to_message_id": reply_to_msg_id,
            },
            timeout=10,
        )


def _log_escalation(customer_id: str, customer_name: str, question: str):
    """Append escalation record to log file."""
    log_path = Path(ESCALATION_LOG_PATH)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    records = []
    if log_path.exists():
        try:
            records = json.loads(log_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            records = []

    records.append({
        "customer_id": customer_id,
        "customer_name": customer_name,
        "question": question,
        "timestamp": datetime.now().isoformat(),
        "resolved": False,
    })

    log_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")

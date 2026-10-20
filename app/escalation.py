import json
import logging
from datetime import datetime
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ESCALATION_LOG_PATH = "data/escalation_log.json"
PENDING_ESCALATIONS_PATH = "data/pending_escalations.json"

# Dòng đầu tin Telegram: /telegram-webhook chỉ dựng lại escalation từ text khi tin bắt đầu bằng ESCALATION_HEADER.
ESCALATION_HEADER = "⚠️ CẦN TRỢ GIÚP ⚠️"
LEAD_HEADER = "📞 KHÁCH ĐỂ LẠI SĐT"

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


async def _send_telegram(text: str) -> int | None:
    """Send text to the admin Telegram group. Returns its message_id, None if not configured or on error."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.error("Telegram not configured")
        return None

    try:
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": text,
                },
                timeout=10,
            )
        if response.status_code != 200:
            logger.error(f"Telegram API error: {response.status_code} {response.text}")
            return None
        return response.json()["result"]["message_id"]
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return None


async def escalate_to_admin(
    customer_id: str,
    customer_name: str,
    question: str,
    page_name: str = "",
) -> bool:
    """Send escalated question to Telegram group and track for admin reply."""
    message = (
        f"{ESCALATION_HEADER}\n\n"
        f"👤 Khách hàng: {customer_name}\n"
        f"🆔 ID: {customer_id}\n"
        f"📄 Trang: {page_name}\n\n"
        f"❓ Câu hỏi:\n{question}\n\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"💬 Reply tin nhắn này để trả lời khách hàng."
    )

    try:
        telegram_msg_id = await _send_telegram(message)
        if telegram_msg_id is None:
            return False

        # Save mapping: telegram_message_id -> customer info
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


async def notify_lead(customer_id: str, customer_name: str, phone: str, profile: dict, last_message: str) -> bool:
    """Tell the consultants on Telegram that a parent left a phone number.

    Not tracked in _pending: replying to this message sends nothing to the parent.
    """
    def known(*values) -> str:
        return ", ".join(str(v) for v in values if v) or "chưa rõ"

    concerns = profile.get("concerns")
    concerns = concerns if isinstance(concerns, list) else [concerns]

    message = (
        f"{LEAD_HEADER}\n\n"
        f"👤 Facebook: {customer_name}\n"
        f"📱 SĐT: {phone}\n"
        f"🆔 ID: {customer_id}\n"
        f"👶 Bé: {known(profile.get('kid_name'), profile.get('kid_age'))}\n"
        f"🏫 Quan tâm: {known(profile.get('interested_program'), profile.get('interested_campus'))}\n"
        f"📍 Địa chỉ: {known(profile.get('address'))}\n"
        f"💭 Mối quan tâm: {known(*concerns)}\n\n"
        f"💬 Tin nhắn gần nhất:\n{last_message}\n\n"
        f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"📲 Gọi hoặc nhắn Zalo cho phụ huynh. Reply tin này không gửi tới khách."
    )

    telegram_msg_id = await _send_telegram(message)
    if telegram_msg_id is None:
        return False
    logger.info(f"Lead sent to Telegram (msg_id={telegram_msg_id}) for customer {customer_id}")
    return True


def get_pending_escalation(telegram_msg_id: int) -> dict | None:
    """Look up a pending escalation by Telegram message ID."""
    return _pending.get(telegram_msg_id)


def resolve_escalation(telegram_msg_id: int):
    """Remove a resolved escalation from pending."""
    if telegram_msg_id in _pending:
        del _pending[telegram_msg_id]
        _save_pending()


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

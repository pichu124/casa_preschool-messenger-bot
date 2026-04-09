import json
import logging
from datetime import datetime
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

ESCALATION_LOG_PATH = "data/escalation_log.json"


async def escalate_to_admin(
    customer_id: str,
    customer_name: str,
    question: str,
    page_name: str = "",
):
    """Send escalated question to admin via Telegram and log it."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.error("Telegram escalation not configured (missing bot token or chat ID)")
        return False

    # Format escalation message
    message = (
        f"⚠️ CẦN TRỢ GIÚP ⚠️\n\n"
        f"👤 Khách hàng: {customer_name}\n"
        f"🆔 ID: {customer_id}\n"
        f"📄 Trang: {page_name}\n\n"
        f"❓ Câu hỏi:\n{question}\n\n"
        f"🕐 Thời gian: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
        f"Hãy trả lời khách hàng qua trang Messenger."
    )

    try:
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={
                    "chat_id": settings.TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "HTML",
                },
                timeout=10,
            )
            if response.status_code != 200:
                logger.error(f"Telegram API error: {response.status_code} {response.text}")
                return False

        logger.info(f"Escalated question from {customer_name} to Telegram admin")
        _log_escalation(customer_id, customer_name, question)
        return True
    except Exception as e:
        logger.error(f"Failed to escalate to Telegram: {e}")
        return False


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

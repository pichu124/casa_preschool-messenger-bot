import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import httpx

from app.config import settings
from app.customer_memory import lead_stage
from app.leads_sheet import post_lead_row

logger = logging.getLogger(__name__)

ESCALATION_LOG_PATH = "data/escalation_log.json"
PENDING_ESCALATIONS_PATH = "data/pending_escalations.json"

# Dòng đầu tin Telegram: /telegram-webhook chỉ dựng lại escalation từ text khi tin bắt đầu bằng ESCALATION_HEADER.
ESCALATION_HEADER = "⚠️ CẦN TRỢ GIÚP ⚠️"
LEAD_HEADER = "📞 KHÁCH ĐỂ LẠI SĐT"
LEAD_HEADERS = {
    "new_phone": LEAD_HEADER,
    "phone_changed": "📞 KHÁCH ĐỔI SĐT",
    "visit_request": "📅 KHÁCH HẸN THAM QUAN/HỌC THỬ",
}

# Sent to the parent on escalation; only invite a phone/Zalo number when we don't have one yet and the parent
# has not declined to leave one (then the consultant's Telegram reply comes back here, in Messenger).
ESCALATION_MESSAGE_HAS_PHONE = (
    "Dạ, em cảm ơn Ba/Mẹ đã nhắn cho Casa ạ! "
    "Câu hỏi của Ba/Mẹ em đã chuyển đến bộ phận tư vấn, "
    "tư vấn viên sẽ liên hệ và trả lời Ba/Mẹ trong thời gian sớm nhất ạ."
)
ESCALATION_MESSAGE_ASK_PHONE = (
    "Dạ, em cảm ơn Ba/Mẹ đã nhắn cho Casa ạ! "
    "Câu hỏi của Ba/Mẹ em đã chuyển đến bộ phận tư vấn, bộ phận sẽ phản hồi Ba/Mẹ sớm nhất ạ. "
    "Nếu tiện, Ba/Mẹ để lại SĐT hoặc Zalo để tư vấn viên hỗ trợ Ba/Mẹ nhanh hơn nhé ạ."
)
ESCALATION_MESSAGE_PHONE_DECLINED = (
    "Dạ, em cảm ơn Ba/Mẹ đã nhắn cho Casa ạ! "
    "Câu hỏi của Ba/Mẹ em đã chuyển đến bộ phận tư vấn, "
    "nhân viên tư vấn sẽ trả lời Ba/Mẹ trực tiếp tại đây sớm nhất ạ."
)

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


def normalize_phone(phone) -> str:
    """Digits only, Vietnam country code 84 (also written with the trunk 0, "+84 0…") as a leading 0:
    "+84 912 345 678", "+84 0912 345 678", "912 345 678" and "0912345678" are one number, as are
    "+84 24 3123 4567" and "024 3123 4567". Other numbers written with "+" keep it: "+1 650 555 1234" is
    "+16505551234"."""
    text = str(phone or "")
    digits = re.sub(r"[^0-9]", "", text)
    if digits.startswith("84"):
        national = digits[2:].removeprefix("0")
        if len(national) in (9, 10):  # mobile, landline
            return "0" + national
    if text.lstrip(" (").startswith("+"):
        return "+" + digits
    if re.fullmatch(r"[35789]\d{8}", digits):  # mobile without the trunk 0
        return "0" + digits
    return digits


def _same_text(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def lead_events(before: dict, extracted: dict) -> list[str]:
    """Lead events in one parent message: `before` is the profile before it, `extracted` what it adds.

    Phones are compared after normalize_phone and visit requests ignoring case and spacing, so the same value
    written another way is no event.
    """
    events = []
    phone = normalize_phone(extracted.get("phone"))
    if phone:
        old_phone = normalize_phone(before.get("phone"))
        if not old_phone:
            events.append("new_phone")
        elif phone != old_phone:
            events.append("phone_changed")
    visit = _same_text(extracted.get("visit_request"))
    if visit and visit != _same_text(before.get("visit_request")):
        events.append("visit_request")
    return events


def _join(*values) -> str:
    return ", ".join(str(v) for v in values if v)


def _known(*values) -> str:
    return _join(*values) or "chưa rõ"


async def publish_lead_event(kind: str, customer_id: str, fb_name: str, profile: dict, last_message: str) -> None:
    """Send a lead event to the Telegram group and the leads Google Sheet, concurrently. `profile` is the profile
    after the parent's message.

    Not tracked in _pending: replying to this message sends nothing to the parent. Never raises; logs carry
    neither the phone number nor the Sheet URL.
    """
    try:
        concerns = profile.get("concerns")
        concerns = concerns if isinstance(concerns, list) else [concerns]
        stage = lead_stage(profile)
        message = (
            f"{LEAD_HEADERS[kind]}\n\n"
            f"👤 Facebook: {fb_name}\n"
            f"📱 SĐT: {_known(profile.get('phone'))}\n"
            f"🆔 ID: {customer_id}\n"
            f"👶 Bé: {_known(profile.get('kid_name'), profile.get('kid_age'))}\n"
            f"🏫 Quan tâm: {_known(profile.get('interested_program'), profile.get('interested_campus'))}\n"
            f"📍 Khu vực: {_known(profile.get('area'), profile.get('address'))}\n"
            f"🗓 Dự kiến nhập học: {_known(profile.get('expected_start'))}\n"
            f"📅 Hẹn: {_known(profile.get('visit_request'))}\n"
            f"📣 Quảng cáo: {_known(profile.get('ad_title'))}\n"
            f"📊 Giai đoạn: {stage}\n"
            f"💭 Mối quan tâm: {_known(*concerns)}\n\n"
            f"💬 Tin nhắn gần nhất:\n{last_message}\n\n"
            f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
            f"📲 Gọi hoặc nhắn Zalo cho phụ huynh. Reply tin này không gửi tới khách."
        )
        # Keys and column order: docs/google-sheet-leads.md
        row = {
            "fb_name": fb_name,
            "customer_id": customer_id,
            "phone": _join(profile.get("phone")),
            "kid_name": _join(profile.get("kid_name")),
            "kid_age": _join(profile.get("kid_age")),
            "campus": _join(profile.get("interested_campus"), profile.get("interested_program")),
            "area": _join(profile.get("area"), profile.get("address")),
            "expected_start": _join(profile.get("expected_start")),
            "visit_request": _join(profile.get("visit_request")),
            "ad_title": _join(profile.get("ad_title")),
            "stage": stage,
            "last_message": last_message,
        }
        telegram_msg_id, sheet_ok = await asyncio.gather(_send_telegram(message), post_lead_row(kind, row))
        logger.info(
            f"Lead {kind} for customer {customer_id}: Telegram msg_id={telegram_msg_id}, Sheet written={sheet_ok}"
        )
    except Exception as e:
        logger.error(f"Lead {kind} for customer {customer_id} not published: {type(e).__name__}")


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

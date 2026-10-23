import asyncio
import json
import logging
import re
from datetime import datetime
from pathlib import Path

import httpx

from app.config import settings
from app.customer_memory import get_profile, lead_stage, set_fields
from app.leads_sheet import VN_TZ, post_lead_row

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
    "info_update": "📝 KHÁCH CẬP NHẬT THÔNG TIN",
}
# Lead info the card and the Sheet row show: (label in the 🔄 reply, profile fields shown together on the card).
LEAD_INFO = (
    ("Tên bé", ("kid_name",)),
    ("Tuổi bé", ("kid_age",)),
    ("Quan tâm", ("interested_program", "interested_campus")),
    ("Khu vực", ("area", "address")),
    ("Dự kiến nhập học", ("expected_start",)),
    ("Mối quan tâm", ("concerns",)),
)
# Profile field: Telegram message_id of the parent's lead card, which later lead updates reply to.
LEAD_CARD_FIELD = "lead_card_msg_id"
# customer_id -> lock held while sending that parent's lead card or a reply to it (_send_lead_telegram).
_lead_locks: dict[str, asyncio.Lock] = {}

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


async def _send_telegram(text: str, reply_to: int | None = None) -> int | None:
    """Send text to the admin Telegram group, as a reply to message `reply_to` if given. Returns its message_id,
    None if not configured or on error (a reply to a deleted message is an error)."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.error("Telegram not configured")
        return None

    try:
        url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
        body = {"chat_id": settings.TELEGRAM_CHAT_ID, "text": text}
        if reply_to is not None:
            body["reply_parameters"] = {"message_id": reply_to}
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=body, timeout=10)
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
        f"🕐 {datetime.now(VN_TZ).strftime('%d/%m/%Y %H:%M')}\n\n"
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


def _texts(value) -> dict[str, str]:
    """Non-empty values of a profile field (a list for concerns), keyed by _same_text."""
    texts = {}
    for item in value if isinstance(value, list) else [value]:
        texts.setdefault(_same_text(item), item)
    texts.pop("", None)
    return texts


def lead_events(before: dict, extracted: dict) -> list[str]:
    """Lead events in one parent message: `before` is the profile before it, `extracted` what it adds.

    Phones are compared after normalize_phone, everything else ignoring case and spacing, so the same value
    written another way is no event. "info_update": a parent who was already a lead (phone or visit request)
    gives a new value for a LEAD_INFO field, and the message has no other event (_lead_update lists the info
    changes with them).
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
    if not events and (before.get("phone") or before.get("visit_request")):
        fields = [field for _, fields in LEAD_INFO for field in fields]
        if any(_texts(extracted.get(field)).keys() - _texts(before.get(field)).keys() for field in fields):
            events.append("info_update")
    return events


def _join(*values) -> str:
    return ", ".join(str(v) for v in values if v)


def _known(*values) -> str:
    return _join(*values) or "chưa rõ"


def _lead_card(kind: str, customer_id: str, fb_name: str, profile: dict, last_message: str) -> str:
    concerns = profile.get("concerns")
    concerns = concerns if isinstance(concerns, list) else [concerns]
    return (
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
        f"📊 Giai đoạn: {lead_stage(profile)}\n"
        f"💭 Mối quan tâm: {_known(*concerns)}\n\n"
        f"💬 Tin nhắn gần nhất:\n{last_message}\n\n"
        f"🕐 {datetime.now(VN_TZ).strftime('%d/%m/%Y %H:%M')}\n\n"
        f"📲 Gọi hoặc nhắn Zalo cho phụ huynh. Reply tin này không gửi tới khách."
    )


def _info(profile: dict, fields: tuple[str, ...]) -> str:
    return _join(*{k: v for field in fields for k, v in _texts(profile.get(field)).items()}.values())


def _lead_update(kinds: list[str], customer_id: str, fb_name: str, before: dict, profile: dict) -> str:
    """Short reply to the parent's card: only what changed, old → new."""
    changes = []
    for kind in kinds:
        if kind == "new_phone":
            changes.append(f"để lại SĐT {profile.get('phone')}")
        elif kind == "phone_changed":
            changes.append(f"SĐT: {before.get('phone')} → {profile.get('phone')}")
        elif kind == "visit_request":
            old = f"{before['visit_request']} → " if before.get("visit_request") else ""
            changes.append(f"Hẹn: {old}{profile.get('visit_request')}")
    for label, fields in LEAD_INFO:
        old, new = _info(before, fields), _info(profile, fields)
        if new and _same_text(new) != _same_text(old):
            changes.append(f"{label}: {old} → {new}" if old else f"{label}: {new}")
    return f"🔄 {fb_name or customer_id}: {'; '.join(changes)}\n🕐 {datetime.now(VN_TZ).strftime('%d/%m/%Y %H:%M')}"


async def _send_lead_telegram(
    kinds: list[str], customer_id: str, fb_name: str, before: dict, profile: dict, last_message: str
) -> int | None:
    """One full card per parent, its message_id kept in the profile (LEAD_CARD_FIELD); later leads reply to it.
    A reply Telegram refuses (card deleted: "message to be replied not found") gets a new card instead.
    One parent at a time, card id read inside the lock: a second message while the card is being sent replies to it.
    """
    async with _lead_locks.setdefault(customer_id, asyncio.Lock()):
        card_id = get_profile(customer_id).get(LEAD_CARD_FIELD)
        if card_id:
            update = _lead_update(kinds, customer_id, fb_name, before, profile)
            msg_id = await _send_telegram(update, reply_to=card_id)
            if msg_id is not None:
                return msg_id
            logger.warning(f"Lead card {card_id} of customer {customer_id} not replied to, sending a new card")
        msg_id = await _send_telegram(_lead_card(kinds[0], customer_id, fb_name, profile, last_message))
        if msg_id is not None:
            set_fields(customer_id, {LEAD_CARD_FIELD: msg_id})
        return msg_id


async def publish_lead_events(
    kinds: list[str], customer_id: str, fb_name: str, before: dict, profile: dict, last_message: str
) -> None:
    """Send the lead events of one parent message (lead_events) to the Telegram group and, one row per event, to
    the leads Google Sheet, concurrently. `before` and `profile` are the profile before and after the message.

    Not tracked in _pending: replying to the card or its updates sends nothing to the parent. Never raises; logs
    carry neither the phone number nor the Sheet URL.
    """
    try:
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
            "stage": lead_stage(profile),
            "last_message": last_message,
        }

        async def post_rows() -> bool:
            # One after another: the Sheet keeps one row per parent, and its "Sự kiện" is the last event.
            return all([await post_lead_row(kind, row) for kind in kinds])

        telegram_msg_id, sheet_ok = await asyncio.gather(
            _send_lead_telegram(kinds, customer_id, fb_name, before, profile, last_message), post_rows()
        )
        logger.info(
            f"Lead {','.join(kinds)} for customer {customer_id}: Telegram msg_id={telegram_msg_id}, "
            f"Sheet written={sheet_ok}"
        )
    except Exception as e:
        logger.error(f"Lead {','.join(kinds)} for customer {customer_id} not published: {type(e).__name__}")


def get_pending_escalation(telegram_msg_id: int) -> dict | None:
    """Look up a pending escalation by Telegram message ID."""
    return _pending.get(telegram_msg_id)


def resolve_escalation(telegram_msg_id: int):
    """Remove a resolved escalation from pending."""
    if telegram_msg_id in _pending:
        del _pending[telegram_msg_id]
        _save_pending()


def drop_pending_escalations(customer_id: str) -> int:
    """Remove every pending escalation of one customer; returns how many."""
    stale = [msg_id for msg_id, pending in _pending.items() if pending.get("customer_id") == customer_id]
    for msg_id in stale:
        del _pending[msg_id]
    if stale:
        _save_pending()
    return len(stale)


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

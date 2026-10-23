"""Follow-up: one fixed message to a parent who went quiet mid-consultation, just before Messenger's 24-hour window closes.

Run twice an hour by .github/workflows/followup.yml through POST /followup/run. Sends nothing unless
settings.FOLLOWUP_ENABLED; logs and results carry no name, phone number or message text.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app import customer_memory
from app.config import settings
from app.coverage import fully_consulted
from app.escalation import (
    ESCALATION_MESSAGE_ASK_PHONE,
    ESCALATION_MESSAGE_HAS_PHONE,
    ESCALATION_MESSAGE_PHONE_DECLINED,
    ESCALATION_MESSAGE_UPSET,
    ESCALATION_MESSAGE_UPSET_AGAIN,
)
from app.messenger import send_message

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))
# Messenger allows a Page standard messages only within 24 hours of the parent's last message: after that the
# Graph API refuses them, and tagging an automated message (HUMAN_AGENT) to get past it breaks Messenger policy.
# So the follow-up goes out as late as the window and the sending hours allow.
MESSENGER_WINDOW = timedelta(hours=24)
WINDOW_MARGIN = timedelta(hours=1)  # deadline = parent's last message + 23h
SEND_SLOT = timedelta(hours=2)  # due from latest send - 2h: 3+ runs at minutes 17 and 47, all within sending hours
MIN_SILENCE = timedelta(hours=3)
SEND_HOURS_VN = range(8, 21)  # 8:00 to 20:59 Vietnam time
# The consultant has the conversation: no follow-up after these.
HANDED_TO_CONSULTANT = (
    ESCALATION_MESSAGE_HAS_PHONE,
    ESCALATION_MESSAGE_ASK_PHONE,
    ESCALATION_MESSAGE_PHONE_DECLINED,
    ESCALATION_MESSAGE_UPSET,
    ESCALATION_MESSAGE_UPSET_AGAIN,
    # Before 9694fb8 (no hotline): still the last bot message of parents handed over before that deploy
    "Dạ, em cảm ơn Ba/Mẹ đã nhắn cho Casa ạ! Câu hỏi của Ba/Mẹ em đã chuyển đến bộ phận tư vấn, "
    "tư vấn viên sẽ liên hệ và trả lời Ba/Mẹ trong thời gian sớm nhất ạ.",
    "Dạ, em cảm ơn Ba/Mẹ đã nhắn cho Casa ạ! Câu hỏi của Ba/Mẹ em đã chuyển đến bộ phận tư vấn, bộ phận sẽ phản "
    "hồi Ba/Mẹ sớm nhất ạ. Nếu tiện, Ba/Mẹ để lại SĐT hoặc Zalo để tư vấn viên hỗ trợ Ba/Mẹ nhanh hơn nhé ạ.",
    "Dạ, em cảm ơn Ba/Mẹ đã nhắn cho Casa ạ! Câu hỏi của Ba/Mẹ em đã chuyển đến bộ phận tư vấn, "
    "nhân viên tư vấn sẽ trả lời Ba/Mẹ trực tiếp tại đây sớm nhất ạ.",
)
# Sent only to a parent upset at being asked for a phone number (app/main.py)
TO_UPSET_PARENT = (ESCALATION_MESSAGE_UPSET, ESCALATION_MESSAGE_UPSET_AGAIN)

# The school's wording, verbatim, under the school's labels (_template_key picks one).
TEMPLATES = {
    # 1. Child's age not known yet
    "ask_age": (
        "Dạ em chào Ba/Mẹ ạ. Em xin phép nhắn lại để tiếp tục hỗ trợ Ba/Mẹ tìm hiểu về Casa. Ba/Mẹ cho em xin "
        "độ tuổi hiện tại của bé, để em có thể gửi đúng thông tin về chương trình và lớp học phù hợp với con ạ. "
        "Nếu Ba/Mẹ cần thêm thông tin nào khác, em cũng luôn sẵn sàng hỗ trợ."
    ),
    # 2. Age known, no phone number yet
    "ask_phone": (
        "Dạ em chào Ba/Mẹ ạ. Không biết Ba/Mẹ còn cần em hỗ trợ thêm thông tin nào về chương trình, học phí hay "
        "lớp phù hợp với bé không ạ? Nếu thuận tiện, Ba/Mẹ có thể để lại SĐT/Zalo để Casa tư vấn kỹ hơn cho mình nhé."
    ),
    # 3. Fairly full consultation (app/coverage.py), then the parent stopped
    "invite_visit": (
        "Dạ em chào Ba/Mẹ ạ. Không biết Ba/Mẹ còn điều gì đang băn khoăn hay cần em tư vấn thêm không ạ? Nếu cần, "
        "Casa có thể hỗ trợ Ba/Mẹ tìm hiểu kỹ hơn về chương trình học hoặc sắp xếp một buổi tham quan để gia đình "
        "trực tiếp cảm nhận môi trường học của con."
    ),
}

# Overlapping runs (curl --retry while the first run is still sending) would message the same parents twice.
_run_lock = asyncio.Lock()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value) -> datetime | None:
    """History timestamps are the server's naive datetime.now(); Render runs in UTC, so naive means UTC."""
    try:
        moment = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _template_key(profile: dict) -> str:
    if fully_consulted(profile):
        return "invite_visit"
    if not profile.get("kid_age"):
        return "ask_age"
    return "ask_phone"


def _latest_send(parent_at: datetime) -> datetime:
    """The deadline, or the end of sending hours (20:59:59 Vietnam time) last before it.

    The deadline is kept only when the whole slot [deadline - SEND_SLOT, deadline] falls within sending hours
    (deadline 10:00 to 20:59:59), so every slot, and so every due run, lies within them.
    """
    deadline = (parent_at + MESSENGER_WINDOW - WINDOW_MARGIN).astimezone(VN_TZ)
    start_of_hours = deadline.replace(hour=SEND_HOURS_VN[0], minute=0, second=0, microsecond=0)
    if deadline - SEND_SLOT >= start_of_hours and deadline.hour in SEND_HOURS_VN:
        return deadline
    end_of_hours = deadline.replace(hour=SEND_HOURS_VN[-1], minute=59, second=59, microsecond=0)
    if end_of_hours > deadline:
        end_of_hours -= timedelta(days=1)
    return end_of_hours


def _is_due(profile: dict, now_utc: datetime) -> bool:
    if profile.get("phone") or profile.get("visit_request"):
        return False
    history = profile.get("conversation_history") or []
    if not history or history[-1].get("role") != "assistant" or history[-1].get("content") in HANDED_TO_CONSULTANT:
        return False
    parent_messages = [m for m in history if m.get("role") == "user"]
    if not parent_messages:
        return False
    parent_at = _as_utc(parent_messages[-1].get("timestamp"))
    if parent_at is None or now_utc - parent_at < MIN_SILENCE:
        return False
    latest_send = _latest_send(parent_at)
    if not latest_send - SEND_SLOT <= now_utc <= latest_send:
        return False
    # Upset in this conversation (the 24 hours up to the parent's last message), even if the parent wrote on: the
    # follow-up asks for the phone number they were upset about. An unreadable time counts as recent.
    for m in history:
        if m.get("role") == "assistant" and m.get("content") in TO_UPSET_PARENT:
            at = _as_utc(m.get("timestamp"))
            if at is None or at >= parent_at - MESSENGER_WINDOW:
                return False
    # Already followed up, or staff answered by hand in the Page inbox (app/main.py), since the parent's last message
    for key in ("followup_sent_at", "staff_replied_at"):
        if key in profile:
            at = _as_utc(profile[key])
            if at is None or at >= parent_at:
                return False
    return True


def due_followups(customers: dict, now_utc: datetime) -> list[tuple[str, str]]:
    """(customer_id, template key) of every parent to follow up at `now_utc` (timezone-aware)."""
    if now_utc.astimezone(VN_TZ).hour not in SEND_HOURS_VN:
        return []
    return [(cid, _template_key(profile)) for cid, profile in customers.items() if _is_due(profile, now_utc)]


def _short_id(customer_id: str) -> str:
    return customer_id[-4:]


async def run_followups(dry_run: bool = False) -> dict:
    """Send the due follow-ups (only counts them when dry_run or FOLLOWUP_ENABLED is off).

    A send the Graph API refuses (outside the window, Page blocked) skips that parent. Returns counts and,
    under "followups", each due parent as template key + last 4 characters of the customer id.
    """
    async with _run_lock:
        now = _now_utc()
        due = due_followups(customer_memory.get_all_profiles(), now)
        enabled = settings.FOLLOWUP_ENABLED
        sent = 0
        if enabled and not dry_run:
            for customer_id, key in due:
                text = TEMPLATES[key]
                try:
                    await send_message(customer_id, text)
                except Exception as e:
                    # messenger.send_message already logged the Graph API status and error
                    short_id = _short_id(customer_id)
                    logger.warning(f"Follow-up {key} not sent to customer …{short_id}: {type(e).__name__}")
                    continue
                customer_memory.set_fields(customer_id, {"followup_sent_at": now.isoformat()})
                await customer_memory.append_to_history(customer_id, "assistant", text)
                sent += 1
            if sent and not await customer_memory.sync_to_github():
                logger.warning(
                    f"Follow-up run: followup_sent_at of {sent} parents not pushed to GitHub, only on local disk: "
                    "lost on restart, and they may be followed up again"
                )
        logger.info(f"Follow-up run: {len(due)} due, {sent} sent (enabled={enabled}, dry_run={dry_run})")
        return {
            "due": len(due),
            "sent": sent,
            "enabled": enabled,
            "followups": [{"template_key": key, "customer_id": _short_id(cid)} for cid, key in due],
        }

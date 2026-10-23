import asyncio
import hmac
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Query, BackgroundTasks, Depends
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.qa_database import QADatabase
from app.ai_engine import AIEngine
from app.messenger import (
    BOT_MESSAGE_METADATA,
    GET_STARTED_PAYLOAD,
    ICE_BREAKERS,
    QUICK_REPLY_PREFIX,
    build_quick_replies,
    quick_reply_meaning,
    send_message,
    send_image,
    send_typing_indicator,
    set_messenger_profile,
    get_user_profile,
    verify_webhook_signature,
)
from app.escalation import (
    ESCALATION_HEADER,
    ESCALATION_MESSAGE_ASK_PHONE,
    ESCALATION_MESSAGE_HAS_PHONE,
    ESCALATION_MESSAGE_PHONE_DECLINED,
    drop_pending_escalations,
    escalate_to_admin,
    get_pending_escalation,
    lead_events,
    normalize_phone,
    publish_lead_events,
    resolve_escalation,
)
from app import analytics
from app import customer_memory
from app.coverage import topics_in_reply
from app.leads_sheet import post_topic_row
from app.topics import clean_topics
from app.followup import run_followups

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
# httpx logs every request URL at INFO: the Telegram bot token, the page access token, the leads Sheet URL.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# uvicorn logs every request path with its query: the admin secret and Facebook's verify token.
_SECRET_QUERY = re.compile(r"([?&](?:secret|hub\.verify_token)=)[^&\s]*")


class _MaskSecretQuery(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_SECRET_QUERY.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        return True


logging.getLogger("uvicorn.access").addFilter(_MaskSecretQuery())

APP_VERSION = "1.6.0"
app = FastAPI(title="Preschool Messenger Bot", version=APP_VERSION)
# Public files (Q&A images such as the sample menu), referenced as "static/<file>" in qa_database.json.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Initialize Q&A database and AI engine
qa_db = QADatabase(settings.QA_DATABASE_PATH)
ai_engine = AIEngine(qa_context=qa_db.build_context())

# Dedup: track processed message IDs to prevent duplicates
_processed_fb_mids: set[str] = set()
_processed_tg_mids: set[int] = set()
MAX_DEDUP_SIZE = 500


def _warn_insecure_config():
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        logger.warning("TELEGRAM_WEBHOOK_SECRET is not set: admin endpoints and /telegram-webhook are locked (403)")
    if not settings.FB_APP_SECRET:
        logger.warning("FB_APP_SECRET is not set: /webhook accepts Facebook requests without signature verification")


_warn_insecure_config()


def _secret_matches(given: str) -> bool:
    """Constant-time check against TELEGRAM_WEBHOOK_SECRET; always False if it is not configured."""
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def require_secret(secret: str = ""):
    """Guard admin endpoints. Pass ?secret=<TELEGRAM_WEBHOOK_SECRET>."""
    if not _secret_matches(secret):
        raise HTTPException(status_code=403, detail="Invalid secret")


@app.get("/")
async def health_check():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "qa_pairs": len(qa_db.qa_pairs),
        "ai_models": settings.AI_MODEL_ORDER,
    }


@app.get("/dashboard")
async def dashboard(_: None = Depends(require_secret)):
    """Serve analytics dashboard HTML. Requires ?secret=."""
    from pathlib import Path
    from fastapi.responses import HTMLResponse
    dashboard_path = Path(__file__).parent / "dashboard.html"
    if dashboard_path.exists():
        return HTMLResponse(dashboard_path.read_text(encoding="utf-8"))
    raise HTTPException(status_code=404, detail="Dashboard not found")


@app.get("/analytics/stats")
async def analytics_stats(_: None = Depends(require_secret)):
    """Return analytics statistics as JSON. Requires ?secret=."""
    return analytics.get_stats()


@app.get("/analytics/messages")
async def analytics_messages(limit: int = 20, _: None = Depends(require_secret)):
    """Return recent messages as JSON. Requires ?secret=."""
    return analytics.get_recent_messages(limit=limit)


@app.get("/customers")
async def list_customers(_: None = Depends(require_secret)):
    """List all customer profiles. Requires ?secret=."""
    profiles = customer_memory.get_all_profiles()
    return {
        "total": len(profiles),
        "customers": profiles,
    }


@app.get("/customers/export")
async def export_customers(_: None = Depends(require_secret)):
    """Export customer profiles to Excel file. Requires ?secret=."""
    import io
    import openpyxl
    from fastapi.responses import StreamingResponse
    from datetime import datetime

    profiles = customer_memory.get_all_profiles()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Khách hàng Casa"

    # Header
    headers = [
        "Customer ID",
        "Tên phụ huynh",
        "Tên bé",
        "Tuổi bé",
        "Giới tính bé",
        "SĐT",
        "Đã từ chối SĐT",
        "Địa chỉ",
        "Khu vực",
        "Hệ quan tâm",
        "Cơ sở quan tâm",
        "Dự kiến nhập học",
        "Hẹn tham quan/học thử",
        "Giai đoạn",
        "Nguồn",
        "Mối quan tâm",
        "Tính cách bé",
        "Lần đầu nhắn",
        "Lần cuối nhắn",
        "Số tin nhắn",
    ]
    ws.append(headers)

    # Make header bold
    from openpyxl.styles import Font, PatternFill
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="667EEA", end_color="667EEA", fill_type="solid")
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill

    # Data rows
    for customer_id, profile in profiles.items():
        concerns = profile.get("concerns", [])
        if isinstance(concerns, list):
            concerns = ", ".join(concerns)

        traits = profile.get("kid_traits", [])
        if isinstance(traits, list):
            traits = ", ".join(traits)

        # Format timestamps
        first_seen = profile.get("first_seen", "")
        last_seen = profile.get("last_seen", "")
        try:
            if first_seen:
                first_seen = datetime.fromisoformat(first_seen).strftime("%d/%m/%Y %H:%M")
            if last_seen:
                last_seen = datetime.fromisoformat(last_seen).strftime("%d/%m/%Y %H:%M")
        except Exception:
            pass

        ws.append([
            customer_id,
            profile.get("parent_name", ""),
            profile.get("kid_name", ""),
            profile.get("kid_age", ""),
            profile.get("kid_gender", ""),
            profile.get("phone", ""),
            "Có" if profile.get("phone_declined") else "",
            profile.get("address", ""),
            profile.get("area", ""),
            profile.get("interested_program", ""),
            profile.get("interested_campus", ""),
            profile.get("expected_start", ""),
            profile.get("visit_request", ""),
            customer_memory.lead_stage(profile),
            profile.get("ad_title", ""),
            concerns,
            traits,
            first_seen,
            last_seen,
            profile.get("message_count", 0),
        ])

    # Auto-width columns
    for col_idx, col_letter in enumerate([c.column_letter for c in ws[1]], 1):
        max_length = max(
            (len(str(ws.cell(row=r, column=col_idx).value or "")) for r in range(1, ws.max_row + 1)),
            default=15,
        )
        ws.column_dimensions[col_letter].width = min(max_length + 2, 40)

    # Save to buffer
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    filename = f"casa_customers_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/customers/{customer_id}/reset")
async def reset_customer(customer_id: str, _: None = Depends(require_secret)):
    """Forget one parent (profile, history, pending escalations): their next message is a first message.
    Requires ?secret=."""
    existed = customer_memory.reset_customer(customer_id)
    dropped = drop_pending_escalations(customer_id)
    if existed:
        await customer_memory.sync_to_github()
    logger.info(f"Reset customer {customer_id}: existed={existed}, pending escalations dropped={dropped}")
    return {"status": "reset", "existed": existed}


@app.post("/analytics/reset")
async def analytics_reset(_: None = Depends(require_secret)):
    """Delete all analytics data. Requires ?secret=."""
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
            inbound = parse_messaging_event(event)
            if inbound is None:
                continue

            # Dedup: skip if already processed
            key = inbound.dedup_key
            if key and key in _processed_fb_mids:
                logger.info(f"Skipping duplicate FB message: {key}")
                continue
            if key:
                _processed_fb_mids.add(key)
                # ponytail: evict ~half instead of clear() so recent mids survive and dedup keeps working
                if len(_processed_fb_mids) > MAX_DEDUP_SIZE:
                    for _ in range(MAX_DEDUP_SIZE // 2):
                        _processed_fb_mids.pop()

            # Process in background so webhook returns 200 immediately
            if isinstance(inbound, StaffReply):
                background_tasks.add_task(save_staff_reply, inbound.customer_id, inbound.replied_at)
            elif inbound.text:
                background_tasks.add_task(
                    process_message, inbound.sender_id, inbound.text, inbound.attribution, inbound.phone_from_qr
                )
            else:
                background_tasks.add_task(save_attribution, inbound.sender_id, inbound.attribution)

    return {"status": "ok"}


# Sent to the model as the parent's first message when they tap Get Started.
GET_STARTED_TEXT = "Xin chào Casa ạ"
REFERRAL_SOURCES = {"ADS": "ads", "SHORTLINK": "link"}


@dataclass
class InboundEvent:
    sender_id: str
    text: str | None  # None: only a referral to record, nothing to answer
    dedup_key: str
    attribution: dict = field(default_factory=dict)
    phone_from_qr: str | None = None


@dataclass
class StaffReply:
    """Staff typed a message to the parent in the Page inbox (seen as a message echo)."""

    customer_id: str
    dedup_key: str
    replied_at: str  # ISO, UTC


def _attribution(referral: dict) -> dict:
    """Profile fields from a Messenger referral (ad, m.me link). No source means organic: nothing is written."""
    fields = {
        "lead_source": REFERRAL_SOURCES.get(referral.get("source", "")),
        "ad_id": referral.get("ad_id"),
        "ad_title": (referral.get("ads_context_data") or {}).get("ad_title"),
        "ref": referral.get("ref"),
    }
    return {k: v for k, v in fields.items() if v}


# Digit groups joined by spaces, dots or dashes, maybe after a "+": where a phone number can be written.
DIGIT_RUN = re.compile(r"\+?\d+(?:[\s.\-]+\d+)*")
# A Vietnamese number after normalize_phone: mobile 0 and 9 digits from 3, 5, 7, 8 or 9; landline 02 and 9 digits.
VIETNAM_PHONE = re.compile(r"0(?:[35789]\d{8}|2\d{9})")


def _phone_in_run(run: str) -> str | None:
    """The first phone number in a DIGIT_RUN: the one it starts with, else one starting at a later group that
    starts with 0 ("Tầng 12 - 0912345678"; "1 912 345 678" is none); None when there is none."""
    groups = list(re.finditer(r"\d+", run))
    for start in [0] + [g.start() for g in groups[1:] if g.group().startswith("0")]:
        phone = _phone_at(run[start:])
        if phone:
            return phone
    return None


def _phone_at(run: str) -> str | None:
    """The phone number a DIGIT_RUN starts with; None when there is none.

    A "+" not followed by 84 starts a foreign number of 8 to 15 digits. It takes the whole run, its tail is not
    guessed ("+33 6 12 34 56 78"), and ends only before a Vietnamese number ("+65 9123 4567 0912345678"), never
    right after its country code: "+886 0912 345 678" and "+39 0331 123456" are foreign. A Vietnamese number
    ends at the first group boundary where it is complete. A group of 1 or 2 digits or one starting with 0 may
    follow ("0912345678 2 bé", "0912345678 0987654321"), a longer one means it runs on ("+84 911 222 501 999"
    is none).
    """
    foreign = run.startswith("+") and not run.startswith("+84")
    groups = list(re.finditer(r"\d+", run))
    for i, group in enumerate(groups):
        phone = run[: group.end()]
        if foreign:
            digits = len(re.sub(r"\D", "", phone))
            rest = run[groups[i + 1].start() :] if i + 1 < len(groups) else ""
            country_code = i == 0 and digits < 8
            if not rest or (rest[0] == "0" and not country_code and _phone_at(rest)):
                return phone if 8 <= digits <= 15 else None
            continue
        normalized = normalize_phone(phone)
        if VIETNAM_PHONE.fullmatch(normalized):
            following = groups[i + 1].group() if i + 1 < len(groups) else ""
            if len(following) > 2 and not following.startswith("0"):
                return None
            # A mobile written without its trunk 0 is stored with it
            return normalized if len(re.sub(r"\D", "", phone)) == 9 else phone
    return None


def _find_phone(value) -> str | None:
    """The first phone number in `value` as written, without parentheses (a mobile without its trunk 0 gets it);
    None when there is none."""
    for run in DIGIT_RUN.findall(re.sub(r"[()]", "", str(value or ""))):
        phone = _phone_in_run(run)
        if phone:
            return phone
    return None


PHONE_MASK = "[SĐT]"


def mask_phones(text: str) -> str:
    """`text` with each DIGIT_RUN holding a phone number (as _find_phone sees it, parentheses read as spaces)
    replaced by PHONE_MASK, so a question can be stored without the parent's number."""
    spaced = re.sub(r"[()]", " ", text)
    parts, end = [], 0
    for run in DIGIT_RUN.finditer(spaced):
        if _phone_in_run(run.group()):
            parts += [text[end : run.start()], PHONE_MASK]
            end = run.end()
    return "".join(parts) + text[end:]


def _staff_reply(echo: dict) -> StaffReply | None:
    """A message echo (sender: the Page, recipient: the parent) of a message the bot did not send; None for the
    bot's own messages."""
    customer_id = (echo.get("recipient") or {}).get("id")
    message = echo["message"]
    if not customer_id or message.get("metadata") == BOT_MESSAGE_METADATA:
        return None
    timestamp = echo.get("timestamp")  # milliseconds
    replied_at = datetime.fromtimestamp(timestamp / 1000, timezone.utc) if timestamp else datetime.now(timezone.utc)
    return StaffReply(customer_id, message.get("mid", ""), replied_at.isoformat())


def parse_messaging_event(event: dict) -> InboundEvent | StaffReply | None:
    """One webhook `messaging` event as what the bot answers or records; None when there is neither."""
    message = event.get("message") or {}
    if message.get("is_echo"):
        return _staff_reply(event)
    sender_id = (event.get("sender") or {}).get("id")
    postback = event.get("postback") or {}
    if not sender_id:
        return None

    referral = event.get("referral") or message.get("referral") or postback.get("referral") or {}
    attribution = _attribution(referral)
    text = None
    phone_from_qr = None
    dedup_key = ""
    if message:
        text = message.get("text")
        dedup_key = message.get("mid", "")
        payload = (message.get("quick_reply") or {}).get("payload", "")
        if payload.startswith(QUICK_REPLY_PREFIX):
            text = quick_reply_meaning(payload) or text
        elif payload and _find_phone(payload):
            # Messenger's phone button: payload and text are both the number from the parent's Facebook account
            phone_from_qr = payload
    elif postback:
        payload = postback.get("payload", "")
        if payload == GET_STARTED_PAYLOAD:
            text = GET_STARTED_TEXT
        else:
            text = ICE_BREAKERS.get(payload) or postback.get("title")
        dedup_key = postback.get("mid") or f"pb:{sender_id}:{event.get('timestamp', '')}"

    if not text and not attribution:
        return None
    return InboundEvent(sender_id, text or None, dedup_key, attribution, phone_from_qr)


async def save_attribution(sender_id: str, attribution: dict):
    """Referral without a message (parent opened the thread from an ad or link): remember the source, no reply."""
    customer_memory.set_fields(sender_id, attribution)
    logger.info(f"Referral for {sender_id}: {list(attribution)}")
    await customer_memory.sync_to_github()


async def save_staff_reply(customer_id: str, replied_at: str):
    """Staff answered the parent by hand in the Page inbox: app/followup.py sends no follow-up after it. No reply."""
    customer_memory.set_fields(customer_id, {"staff_replied_at": replied_at})
    logger.info(f"Staff replied by hand to {customer_id}")
    await customer_memory.sync_to_github()


IMAGES_PATTERN = re.compile(r"\[IMAGES:([^\]]+)\]")
QUICK_PATTERN = re.compile(r"\[QUICK:([^\]]*)\]")


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


def _extract_quick_reply(text: str) -> tuple[str, str]:
    """Strip [QUICK:key] tokens from response text. Returns (clean_text, key of the last token or "")."""
    keys = QUICK_PATTERN.findall(text)
    return QUICK_PATTERN.sub("", text).strip(), (keys[-1].strip() if keys else "")


def _public_image_url(url: str) -> str:
    """Q&A images given as "static/<file>" are served by this app at /static."""
    if url.startswith("static/"):
        return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/{url}"
    return url


def _last_bot_message(history: list[dict]) -> str:
    return history[-1]["content"] if history and history[-1]["role"] == "assistant" else ""


def _clean_extracted(extracted: dict, phone_from_qr: str | None, text: str) -> dict:
    """The model's extraction of the parent's message `text` made safe to store: the phone quick reply wins,
    otherwise phone is the first phone number in what the model gave ("0912345678, 0987654321" keeps the
    first), else the first one in `text` itself, so a number the parent typed is kept even when every model
    fails; it then also drops phone_declined. phone_declined is kept only as JSON true (models also return
    "false"); topics_covered is only ever what the bot replied with (topics_in_reply); topics are statistics of
    one message (app/topics.py), not profile data."""
    extracted = dict(extracted)
    extracted.pop("topics_covered", None)
    extracted.pop("topics", None)
    phone = phone_from_qr or _find_phone(extracted.pop("phone", None))
    if not phone:
        phone = _find_phone(text)
        if phone:
            extracted.pop("phone_declined", None)
    if phone:
        extracted["phone"] = phone
    if extracted.get("phone_declined") is not True:
        extracted.pop("phone_declined", None)
    return extracted


TOPIC_QUESTION_MAX = 300


async def publish_topics(customer_id: str, topics: list[str], escalated: bool, text: str) -> None:
    """One "Chủ đề" Sheet row for the parent message `text` (post_topic_row: only when TOPICS_SHEET_ENABLED), with
    the profile as it is after the message; no Facebook name, the question cut and without phone numbers.
    Never raises; logs carry no message text."""
    try:
        profile = customer_memory.get_profile(customer_id)
        await post_topic_row(
            {
                "customer_id": customer_id,
                "ad_title": str(profile.get("ad_title") or ""),
                "campus": ", ".join(
                    str(v) for v in (profile.get("interested_campus"), profile.get("interested_program")) if v
                ),
                "kid_age": str(profile.get("kid_age") or ""),
                "topics": ", ".join(topics),
                "escalated": "Có" if escalated else "Không",
                "question": mask_phones(text)[:TOPIC_QUESTION_MAX],
            }
        )
    except Exception as e:
        logger.warning(f"Topic row for customer {customer_id} not sent: {type(e).__name__}")


async def process_message(
    sender_id: str, text: str, attribution: dict | None = None, phone_from_qr: str | None = None
):
    """Process an incoming message and respond.

    attribution: ad/link referral fields that came with the message. phone_from_qr: the number the parent sent
    with Messenger's phone quick reply.
    """
    try:
        # Show typing indicator
        await send_typing_indicator(sender_id)

        # Get user profile for personalization
        profile = await get_user_profile(sender_id)
        user_name = profile.get("first_name", "ban")
        full_name = f"{profile.get('first_name', '')} {profile.get('last_name', '')}".strip()

        # Before the prompt is built, so [TRẠNG THÁI TƯ VẤN] already shows the ad source
        if attribution:
            customer_memory.set_fields(sender_id, attribution)

        # Load customer profile (persisted across sessions) + cross-session history
        existing_profile = customer_memory.get_profile(sender_id)
        customer_context = customer_memory.format_profile_for_prompt(existing_profile)
        history = customer_memory.get_conversation_history(sender_id)
        gap_hours = customer_memory.get_last_seen_gap_hours(sender_id)
        had_phone = bool(existing_profile.get("phone"))
        last_bot_message = _last_bot_message(history)

        # Extract customer info alongside the reply, so a phone number sent in this message is known before replying
        response, extracted = await asyncio.gather(
            ai_engine.get_response(
                user_message=text,
                conversation_history=history,
                customer_context=customer_context,
                gap_hours=gap_hours,
            ),
            ai_engine.extract_customer_info(text, existing_profile, last_bot_message=last_bot_message),
        )
        topics_given = extracted.get("topics")
        extracted = _clean_extracted(extracted, phone_from_qr, text)

        logger.info(
            f"User {sender_id} ({user_name}): {len(text)} chars "
            f"-> Model: {response.model_used}, Escalate: {response.should_escalate}, "
            f"HasProfile: {bool(existing_profile)}, GapHours: {gap_hours:.1f}, HistoryLen: {len(history)}"
        )

        escalated = response.should_escalate or not response.text
        topics = clean_topics(topics_given, escalated=escalated)
        covered = []
        if escalated:
            await escalate_to_admin(
                customer_id=sender_id,
                customer_name=full_name,
                question=text,
            )
            if had_phone or extracted.get("phone"):
                reply_text = ESCALATION_MESSAGE_HAS_PHONE
            elif extracted.get("phone_declined") or existing_profile.get("phone_declined"):
                reply_text = ESCALATION_MESSAGE_PHONE_DECLINED
            else:
                reply_text = ESCALATION_MESSAGE_ASK_PHONE
            await send_message(sender_id, reply_text)
        else:
            # History keeps the [IMAGES:] and [QUICK:] tokens so the model knows what it already sent
            reply_text = response.text
            clean_text, image_urls = _extract_images(response.text)
            clean_text, quick_key = _extract_quick_reply(clean_text)
            quick_replies = build_quick_replies(quick_key)
            covered = topics_in_reply(response.text)

            # Messenger shows quick replies only under the latest message: they go on the last one sent
            if clean_text:
                await send_message(sender_id, clean_text, quick_replies=None if image_urls else quick_replies)
            for n, img_url in enumerate(image_urls, 1):
                try:
                    await send_image(
                        sender_id,
                        _public_image_url(img_url),
                        quick_replies=quick_replies if n == len(image_urls) else None,
                    )
                except Exception as img_err:
                    logger.error(f"Failed to send image {img_url}: {img_err}")

        # Log analytics
        try:
            analytics.log_message(
                user_id=sender_id,
                user_name=full_name or user_name,
                question=mask_phones(text),
                model_used=response.model_used,
                escalated=escalated,
                topics=topics,
            )
        except Exception as log_err:
            logger.warning(f"Analytics logging failed: {log_err}")

        # Save customer info (best effort, the reply is already sent). Update even without new info
        # so last_seen and message_count track every message.
        try:
            if full_name and "parent_name" not in extracted and not existing_profile.get("parent_name"):
                extracted["parent_name"] = full_name
            if covered:
                extracted["topics_covered"] = covered
            events = lead_events(existing_profile, extracted)
            updated_profile = await customer_memory.update_profile(sender_id, extracted)
            if extracted:
                logger.info(f"Updated profile for {sender_id}: {list(extracted.keys())}")
            if events:
                await publish_lead_events(events, sender_id, full_name, existing_profile, updated_profile, text)
        except Exception as profile_err:
            logger.warning(f"Customer profile update failed: {profile_err}")

        # Persist conversation history to customer profile (cross-session memory)
        try:
            await customer_memory.append_to_history(sender_id, "user", text)
            await customer_memory.append_to_history(sender_id, "assistant", reply_text)
        except Exception as hist_err:
            logger.warning(f"Failed to persist conversation history: {hist_err}")

        if topics:
            await publish_topics(sender_id, topics, escalated, text)

        await customer_memory.sync_to_github()

    except Exception as e:
        logger.error(f"Error processing message from {sender_id}: {e}", exc_info=True)
        try:
            await send_message(
                sender_id,
                "Dạ, hệ thống của Casa đang gặp sự cố ạ. Ba/Mẹ vui lòng nhắn lại sau ít phút giúp em nhé ạ.",
            )
        except Exception:
            pass


@app.post("/reload-qa")
async def reload_qa(_: None = Depends(require_secret)):
    """Reload Q&A database (call after updating qa_database.json). Requires ?secret=."""
    qa_db.reload()
    _rebuild_ai_context()
    return {"status": "reloaded", "qa_pairs": len(qa_db.qa_pairs)}


@app.get("/qa-database")
async def get_qa_database(_: None = Depends(require_secret)):
    """View all Q&A pairs including learned ones. Requires ?secret=."""
    return {
        "total": len(qa_db.qa_pairs),
        "qa_pairs": qa_db.qa_pairs,
    }


@app.get("/qa-learned")
async def get_qa_learned(_: None = Depends(require_secret)):
    """View only Q&A pairs learned from admin replies. Requires ?secret=."""
    # Cặp cũ không có "source" nhưng từng được lưu với category "Học từ admin".
    learned = [
        p for p in qa_db.qa_pairs if p.get("source") == "admin" or p.get("category") == "Học từ admin"
    ]
    return {
        "total": len(learned),
        "learned_pairs": learned,
    }


@app.post("/import-excel")
async def import_excel(file_path: str, _: None = Depends(require_secret)):
    """Import Q&A from Excel file. Requires ?secret=."""
    try:
        qa_db.import_from_excel(file_path)
        _rebuild_ai_context()
        return {"status": "imported", "qa_pairs": len(qa_db.qa_pairs)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


from pydantic import BaseModel


class TestMessage(BaseModel):
    message: str
    user_id: str = "test_user"


@app.post("/test-chat")
async def test_chat(body: TestMessage, _: None = Depends(require_secret)):
    """Test AI response without Facebook (for development/debugging). Requires ?secret=."""
    # Load profile + persisted history (same as process_message)
    existing_profile = customer_memory.get_profile(body.user_id)
    customer_context = customer_memory.format_profile_for_prompt(existing_profile)
    history = customer_memory.get_conversation_history(body.user_id)
    gap_hours = customer_memory.get_last_seen_gap_hours(body.user_id)

    response = await ai_engine.get_response(
        user_message=body.message,
        conversation_history=history,
        customer_context=customer_context,
        gap_hours=gap_hours,
    )

    # Extract and save profile, cleaned as in process_message
    try:
        extracted = await ai_engine.extract_customer_info(
            body.message, existing_profile, last_bot_message=_last_bot_message(history)
        )
        extracted = _clean_extracted(extracted, None, body.message)
        if response.text and not response.should_escalate:
            covered = topics_in_reply(response.text)
            if covered:
                extracted["topics_covered"] = covered
        if extracted or not existing_profile:
            await customer_memory.update_profile(body.user_id, extracted)
    except Exception as e:
        logger.warning(f"Extract failed in test-chat: {e}")

    # Persist conversation history
    try:
        await customer_memory.append_to_history(body.user_id, "user", body.message)
        if response.text:
            await customer_memory.append_to_history(body.user_id, "assistant", response.text)
    except Exception as e:
        logger.warning(f"Failed to persist history in test-chat: {e}")

    return {
        "response": response.text,
        "model_used": response.model_used,
        "should_escalate": response.should_escalate,
        "gap_hours": round(gap_hours, 2),
        "history_length": len(history),
        "profile": customer_memory.get_profile(body.user_id),
    }


def _rebuild_ai_context():
    """Rebuild AI engine system prompt with updated Q&A context."""
    from app.ai_engine import SYSTEM_PROMPT
    ai_engine.system_prompt = SYSTEM_PROMPT.format(qa_context=qa_db.build_context())
    ai_engine._providers.clear()


@app.post("/telegram-webhook")
async def handle_telegram_webhook(request: Request):
    """Handle admin replies from Telegram group. Telegram sends the secret_token set by /setup-telegram-webhook."""
    if not _secret_matches(request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")):
        raise HTTPException(status_code=403, detail="Invalid secret")

    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return {"status": "ignored"}
    message = data.get("message", {})

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
                for _ in range(MAX_DEDUP_SIZE // 2):
                    _processed_tg_mids.pop()

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
            # Pending escalations live on local disk and are lost on every Render deploy: recover them from
            # the escalation text. Any other message (lead notifications included) has no question to answer.
            original_text = reply.get("text", "")
            if not original_text.startswith(ESCALATION_HEADER):
                return {"status": "no_escalation_found"}
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
        await qa_db.add_qa_pair(category, all_questions, admin_text, keywords, source="admin")

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
async def setup_telegram_webhook(_: None = Depends(require_secret)):
    """Register Telegram webhook URL. Requires ?secret=."""
    import httpx
    webhook_url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}/telegram-webhook"
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/setWebhook"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={
            "url": webhook_url,
            "secret_token": settings.TELEGRAM_WEBHOOK_SECRET,
        })
        return response.json()


@app.post("/setup-messenger-profile")
async def setup_messenger_profile(_: None = Depends(require_secret)):
    """Register the Get Started button and ice breakers on the Page. Requires ?secret=."""
    return await set_messenger_profile()


@app.post("/followup/run")
async def followup_run(dry_run: bool = False, verbose: bool = False, _: None = Depends(require_secret)):
    """Send due follow-ups (app/followup.py); counts only. verbose=1 adds template key + short id per parent,
    never a name, phone number or message. Requires ?secret=."""
    result = await run_followups(dry_run=dry_run)
    if not verbose:
        del result["followups"]
    return result

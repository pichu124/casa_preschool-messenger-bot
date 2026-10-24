import asyncio
import hmac
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

from fastapi import FastAPI, Request, HTTPException, Query, BackgroundTasks, Depends
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.qa_database import QADatabase
from app.ai_engine import AIEngine, ImageNote, media_note
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
    _send_telegram,
    ESCALATION_HEADER,
    ESCALATION_MESSAGE_ASK_PHONE,
    ESCALATION_MESSAGE_HAS_PHONE,
    ESCALATION_MESSAGE_UPSET,
    ESCALATION_MESSAGE_UPSET_AGAIN,
    drop_pending_escalations,
    escalate_to_admin,
    get_pending_escalation,
    has_pending_escalation,
    lead_events,
    normalize_phone,
    publish_lead_events,
)
from app import analytics
from app import customer_memory
from app import media
from app.coverage import topics_in_reply
from app.leads_sheet import VN_TZ, post_topic_row
from app.topics import clean_topics
from app.followup import HANDED_TO_CONSULTANT, run_followups

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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Images from the school's Google Drive: synced in the background, startup does not wait for it.
    media_task = media.start_sync_task()
    yield
    if media_task:
        media_task.cancel()


app = FastAPI(title="Preschool Messenger Bot", version=APP_VERSION, lifespan=lifespan)


class _ImagesOnly(StaticFiles):
    """Serves only the synced .jpg images: MEDIA_DIR also holds catalog.json (Drive paths and ids), kept private."""

    async def get_response(self, path, scope):
        if not path.endswith(".jpg"):
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


# Images synced from Google Drive (app/media.py), wherever MEDIA_DIR is; mounted before /static, which it is under.
Path(settings.MEDIA_DIR).mkdir(parents=True, exist_ok=True)
app.mount("/static/media", _ImagesOnly(directory=settings.MEDIA_DIR), name="media")
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


def mask_phones(text: str, known: tuple = ()) -> str:
    """`text` with each DIGIT_RUN holding a phone number (as _find_phone sees it, parentheses read as spaces)
    replaced by PHONE_MASK, so a question can be stored without the parent's number. `known`: the parent's
    numbers, also masked however they are written ("0912,345,678", "0912345678 125 Trung Kính", "+84 912…")."""
    spaced = re.sub(r"[()]", " ", text)
    parts, end = [], 0
    for run in DIGIT_RUN.finditer(spaced):
        if _phone_in_run(run.group()):
            parts += [text[end : run.start()], PHONE_MASK]
            end = run.end()
    text = "".join(parts) + text[end:]
    for phone in known:
        digits = re.sub(r"\D", "", str(phone or ""))
        if len(digits) < 8:
            continue
        local = digits[1:] if digits.startswith("0") else digits[2:] if digits.startswith("84") else digits
        sep = r"[\s.,/\-–—()]*"
        body = sep.join(local)
        text = re.sub(rf"(?<!\d)(?:(?:\+|00)?84{sep}|0{sep})?{body}(?!\d)", PHONE_MASK, text)
    return text


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
    # Answered outside Telegram: no card of this parent is waiting any more (see _answer_message, upset_again)
    drop_pending_escalations(customer_id)
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
    one message (app/topics.py) and upset is about this message, neither is profile data."""
    extracted = dict(extracted)
    extracted.pop("topics_covered", None)
    extracted.pop("topics", None)
    extracted.pop("upset", None)
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
                "question": mask_phones(text, (profile.get("phone"),))[:TOPIC_QUESTION_MAX],
            }
        )
    except Exception as e:
        logger.warning(f"Topic row for customer {customer_id} not sent: {type(e).__name__}")


# --- Drive images sent after the reply (app/media.py), as docs/quyet-dinh-noi-dung.md decides ("Ảnh gửi phụ huynh") ---

FEE_TOPICS = ("Học phí", "Ưu đãi")
PROGRAMME_TOPIC = "Chương trình/phương pháp"
FACILITIES_TOPIC = "Cơ sở vật chất"
MENU_TOPIC = "Ăn uống/thực đơn"
TOPICS_OF_IMAGE = {"fee": FEE_TOPICS, "timetable": (PROGRAMME_TOPIC,), "facilities": (FACILITIES_TOPIC,), "menu": (MENU_TOPIC,)}
# A message naming the timetable or Cambridge (as media.fold writes it) asks for the timetable whatever its topics:
# the extraction tags Cambridge as "Tiếng Anh/GV nước ngoài" and a timetable as "Giờ học/…". "lịch học thử" is the
# trial week.
# "lịch học thử" (the trial week) is not the timetable; "lịch học thứ 2–6" folds the same, a weekday follows it.
TIMETABLE_NAMES = r"\bthoi (?:khoa|gian) bieu\b|\btkb\b|\blich hoc\b(?! thu\b(?! ?(?:\d|hai|ba|tu|nam|sau|bay)\b))"
TIMETABLE_WORDS = re.compile(rf"\bcambridge\b|{TIMETABLE_NAMES}")
# A message asking for both systems ("2 hệ", "cả hai hệ") or both campuses ("cả 2 cơ sở", "hai bên").
BOTH_WORDS = re.compile(r"\b(?:ca )?(?:2|hai) (he|co so|ben|truong)\b")
# A reply saying the bot itself sends an image (as media.fold writes it: "em gửi", "em xin phép gửi", not "tư vấn
# viên sẽ gửi" nor "em chưa gửi được"), and the words of each kind of image in that sentence.
BOT_SENDS = re.compile(r"\bem(?: (?!chua\b|khong\b)\w+){0,2} gui\b")
# A question or an offer ("Ba/Mẹ có muốn em gửi ảnh … không ạ?", "em gửi Ba/Mẹ … nhé?") does not say the bot sends;
# told apart clause by clause ("em gửi Ba/Mẹ ảnh … ạ, Ba/Mẹ có muốn ghé thăm không ạ?" still does).
OFFERS = re.compile(r"\?\s*$|\bco muon\b|\bkhong a\b\W*$")
IMAGE_WORDS = {
    "fee": re.compile(r"\b(?:hoc phi|bang phi)\b"),
    "timetable": re.compile(TIMETABLE_NAMES),
    "facilities": re.compile(r"\b(?:co so vat chat|anh (?:truong|lop|co so))\b"),
    "menu": re.compile(r"\bthuc don\b"),
}
FACILITY_IMAGES = 4
MAX_IMAGES = 5
# Sent after the reply when it said images follow and every Drive image of the turn failed.
IMAGES_FAILED_MESSAGE = "Dạ ảnh em gửi đang bị lỗi chưa tới được, Ba/Mẹ nhắn lại em sau ít phút để em gửi lại nhé ạ."
IMAGE_FAILURE_ALERT_EVERY = timedelta(hours=1)
# The sample menu of the Q&A (data/qa_database.json): sent only while Drive has no menu image.
QA_MENU_IMAGE = "static/thuc-don-mau.jpg"
# A kid age read from the message text itself, never a fee period ("đóng 12 tháng", "3 tháng").
SAID_AGE_MONTHS = range(15, 85)
ASKS_PHONE = ("sđt", "zalo", "số điện thoại")
ASKS_PHONE_FOLDED = re.compile("|".join(rf"\b{media.fold(word)}\b" for word in ASKS_PHONE))
# What the history tells the model it sent; a model copying it into a reply must not show it to the parent.
SENT_NOTE = re.compile(r"\s*\[đã gửi ảnh[^\]]*\]")


class Offer(NamedTuple):
    kind: str  # a key of TOPICS_OF_IMAGE
    key: str  # its key in the profile's media_sent once sent
    urls: list[str]
    label: str
    stale: media.FeeImage | None = None  # a fee image of an earlier month


def _today_vn() -> date:
    return datetime.now(VN_TZ).date()


def _image_id(url: str) -> str:
    return url.rsplit("/", 1)[-1].removesuffix(".jpg")


def _announced(reply: str) -> set[str]:
    """The kinds of image a sentence of `reply` says the bot sends ("Thời khoá biểu em gửi ngay bên dưới ạ"); not a
    sentence asking for the phone or Zalo ("cho em xin SĐT/Zalo để em gửi bảng học phí"): a consultant sends that."""
    sentences = re.findall(r"[^.!?\n]+[.!?]*", media.fold(reply))
    sentences = [
        s for s in sentences
        if not ASKS_PHONE_FOLDED.search(s) and any(BOT_SENDS.search(c) and not OFFERS.search(c) for c in s.split(","))
    ]
    return {kind for kind, words in IMAGE_WORDS.items() if any(words.search(s) for s in sentences)}


# Profile flag of a question waiting for an image -> the kind of that image.
WAITING_FLAGS = {"fee_asked": "fee", "timetable_asked": "timetable", "facilities_asked": "facilities"}


def _waiting(wanted: bool, missing: bool, offered: bool) -> str:
    """A flag of WAITING_FLAGS: "missing" (waits for what the bot does not know), "offered" (waits until the images
    offered this turn are delivered), "" (does not wait)."""
    return ("missing" if missing else "offered" if offered else "") if wanted else ""


def _campuses_of(system: str) -> list[str]:
    return [c for c, s in media.CAMPUS_SYSTEMS.items() if s == system]


def _campuses(profile: dict, extracted: dict, text: str) -> tuple[list[str], list[str]]:
    """The campuses the reply to `text` is about: those the extraction, else `text`, else the profile names. A
    message asking for both systems or both campuses ("2 hệ", "cả hai cơ sở") gets every campus the parent named in
    the conversation, plus the one campus of a system none of them is in ("2 hệ": Kim Mã for Song ngữ); also returns
    the systems with several campuses none of which is named (asked, not guessed)."""
    campuses = (
        media.campuses_in(extracted.get("interested_campus"))
        or media.campuses_in(text)
        or media.campuses_in(profile.get("interested_campus"))
    )
    both = BOTH_WORDS.search(media.fold(text))
    if not both:
        return campuses, []
    said = [m.get("content", "") for m in profile.get("conversation_history") or [] if m.get("role") == "user"]
    said += [str(v or "") for v in (profile.get("interested_campus"), extracted.get("interested_campus"), text)]
    campuses, unknown = media.campuses_in(". ".join(said)), []
    for system in media.SYSTEM_NAMES if both[1] == "he" else ():
        if any(media.system_of(c) == system for c in campuses):
            continue
        if len(_campuses_of(system)) == 1:
            campuses += _campuses_of(system)
        else:
            unknown.append(system)
    return campuses, unknown


def _plan_images(
    profile: dict,
    extracted: dict,
    text: str,
    topics,
    qa_images: list[str],
    last_bot_message: str,
    today: date,
    announced: set[str] = frozenset(),
) -> tuple[list[str], list[Offer], dict, list[ImageNote]]:
    """Images to send after the reply to `text`: the Q&A ones the model gave (`qa_images`), without the old sample
    menu when Drive has a menu; the Drive offers in sending order (fee and timetable: one per system and campus,
    facilities: one campus a turn); the profile flags of questions waiting for what is missing: fee_asked (the kid's
    age and the campus), timetable_asked (the campus and the kid's age), facilities_asked (the campus); the notes of
    images waiting for what is missing. `extracted`: what the model extracted from `text`, {} before it is known; a
    campus and an age named in `text` count as well. `announced`: the kinds of image the reply says the bot sends,
    taken as asked for, except that only the parent asking the fee lets it go without the kid's age."""
    if not settings.MEDIA_SYNC_ENABLED:
        return qa_images, [], {}, []
    topics, sent = set(topics), profile.get("media_sent") or {}
    parent_asked_fee = bool(topics & set(FEE_TOPICS) or IMAGE_WORDS["fee"].search(media.fold(text)))
    topics |= {topic for kind in announced for topic in TOPICS_OF_IMAGE[kind]}
    campuses, unknown_systems = _campuses(profile, extracted, text)
    if extracted.get("kid_age"):
        age = str(extracted["kid_age"])
    elif media.age_months(text, today) in SAID_AGE_MONTHS:
        age = text
    else:
        age = str(profile.get("kid_age") or "")
    systems = list(dict.fromkeys(s for s in map(media.system_of, campuses) if s))
    program = media.fold(profile.get("interested_program") or "")
    wanted_system = next((s for s, name in media.SYSTEM_NAMES.items() if media.fold(name) in program), None)
    offers, notes = [], []

    # The fee image is the system's: a system asked for without its campus ("2 hệ") still gets it
    fee_systems = list(dict.fromkeys([*systems, *unknown_systems]))
    asked_fee = bool(topics & set(FEE_TOPICS))
    fee_keys = {system: f"fee:{system}:{today:%Y-%m}" for system in fee_systems}
    unsent_fees = [system for system, key in fee_keys.items() if key not in sent]
    wants_fee = bool(asked_fee or profile.get("fee_asked")) and (bool(unsent_fees) or not fee_systems)
    has_phone = profile.get("phone") or extracted.get("phone") or _find_phone(text)
    asked_phone = any(word in last_bot_message.lower() for word in ASKS_PHONE)
    refused = not has_phone and (profile.get("phone_declined") or extracted.get("phone_declined") or asked_phone)
    fee_ready = bool(fee_systems and (age or (refused and parent_asked_fee)))
    fees_offered = False
    for system in unsent_fees if wants_fee and fee_ready else ():
        fee = media.fee_image(system, today)
        if fee:
            names = ", ".join(c for c in campuses if media.system_of(c) == system)
            label = f"học phí hệ {media.SYSTEM_NAMES[system]}" + (f" (cơ sở {names})" if names else "")
            offers.append(Offer("fee", fee_keys[system], [fee.url], label, stale=fee if fee.stale else None))
            fees_offered = True

    asked_timetable = PROGRAMME_TOPIC in topics or bool(TIMETABLE_WORDS.search(media.fold(text)))
    timetable_campuses = [c for c in campuses if media.has_timetables(c)]
    has_timetable = media.has_timetables() if unknown_systems or not campuses else bool(timetable_campuses)
    wants_timetable = (asked_timetable or bool(profile.get("timetable_asked"))) and has_timetable
    months = media.age_months(age, today) if age else None
    timetable_missing = tuple(
        f"cơ sở hệ {media.SYSTEM_NAMES[s]} Ba/Mẹ quan tâm ({' hay '.join(_campuses_of(s))})" for s in unknown_systems
    ) or ("cơ sở Ba/Mẹ quan tâm",) * (not campuses)
    timetable_offered = False
    if wants_timetable and months is None:
        notes.append(ImageNote("timetable", "thời khoá biểu", (*timetable_missing, "tuổi bé"), state="missing"))
    elif wants_timetable:
        already = []
        for campus in timetable_campuses:
            timetable = media.timetable_image(campus, months)
            if timetable and f"timetable:{_image_id(timetable)}" in sent:
                already.append(campus)
            elif timetable:
                label = f"thời khoá biểu cơ sở {campus}"
                offers.append(Offer("timetable", f"timetable:{_image_id(timetable)}", [timetable], label))
                timetable_offered = True
        if already:
            notes.append(ImageNote("timetable", f"thời khoá biểu cơ sở {', '.join(already)}", state="sent"))
        if timetable_missing:
            label = "thời khoá biểu" + "".join(f" hệ {media.SYSTEM_NAMES[s]}" for s in unknown_systems)
            notes.append(ImageNote("timetable", label, timetable_missing, state="missing"))

    menu_system = (systems[0] if systems else None) or wanted_system or "quoc_te"
    menu = media.menu_image(menu_system)
    if menu:
        if QA_MENU_IMAGE in qa_images:
            topics.add(MENU_TOPIC)
            qa_images = [u for u in qa_images if u != QA_MENU_IMAGE]
        if MENU_TOPIC in topics and f"menu:{_image_id(menu)}" not in sent:
            label = f"thực đơn hệ {media.SYSTEM_NAMES[menu_system]}"
            offers.append(Offer("menu", f"menu:{_image_id(menu)}", [menu], label))

    wants_facilities = bool(FACILITIES_TOPIC in topics or profile.get("facilities_asked"))
    unsent = (c for c in campuses if f"facilities:{c}" not in sent and media.facility_images(c, 1))
    facilities_campus = next(unsent, None) if wants_facilities else None
    if facilities_campus:
        facilities = media.facility_images(facilities_campus, FACILITY_IMAGES)
        label = f"cơ sở vật chất cơ sở {facilities_campus}"
        offers.append(Offer("facilities", f"facilities:{facilities_campus}", facilities, label))

    # Waiting only for what is missing, or for an offer not delivered yet: never for an image already sent or absent
    timetable_waits = months is None or bool(timetable_missing)
    waiting = {
        # A reply announcing the fee to a parent who did not ask it waits for nothing (only sent when ready)
        "fee_asked": _waiting(
            wants_fee and (parent_asked_fee or bool(profile.get("fee_asked")) or fee_ready), not fee_ready, fees_offered
        ),
        "timetable_asked": _waiting(wants_timetable, timetable_waits, timetable_offered),
        "facilities_asked": _waiting(wants_facilities, not campuses, bool(facilities_campus)),
    }
    return qa_images, offers, waiting, notes


def _media_note(profile: dict, text: str, last_bot_message: str, today: date) -> str:
    """The [HỆ THỐNG] lines for the reply to `text`, written before its extraction is known: the images sent whatever
    the message asks, and those sent if it asks about their topic (or if the reply says the bot sends them); what an
    image waits for; the images sent before that this message asks for again."""
    if not settings.MEDIA_SYNC_ENABLED:
        return ""
    _, sure, _, sure_notes = _plan_images(profile, {}, text, [], [], last_bot_message, today)
    every_topic = [topic for topics in TOPICS_OF_IMAGE.values() for topic in topics]
    _, offers, _, notes = _plan_images(profile, {}, text, every_topic, [], last_bot_message, today)
    sure_keys = {o.key for o in sure}
    images = [ImageNote(o.kind, o.label, if_asked=o.key not in sure_keys) for o in offers]
    images += [n._replace(if_asked=n not in sure_notes) for n in notes if n.state != "sent" or n in sure_notes]
    campuses = media.campuses_in(text) or media.campuses_in(profile.get("interested_campus"))
    need_campus = not campuses and any(media.facility_images(c, 1) for c in media.CAMPUSES)
    return media_note(images, facilities_need_campus=need_campus)


_stale_fee_reminded: dict[str, date] = {}


async def _remind_stale_fee(system: str, fee: media.FeeImage, today: date) -> None:
    """Tell the admin group, at most once a day per system, that parents get the fee image of an earlier month or
    one last changed over media.FEE_STALE_AFTER (300 days) ago. Kept in memory: a restart may remind once more that day."""
    if _stale_fee_reminded.get(system) == today:
        return
    _stale_fee_reminded[system] = today
    name = media.SYSTEM_NAMES[system]
    await _send_telegram(
        f"⚠️ Chưa có ảnh học phí mới tháng {today.month} hệ {name}: bot đang gửi phụ huynh ảnh {media.fee_in_use(fee)}. "
        f'Trường đặt ảnh tháng này vào thư mục "HỌC PHÍ THÁNG {today.month}" trong "HỆ {name.upper()}" trên Drive '
        f"(thay ảnh cũ nếu có) rồi gõ /capnhatanh."
        + (" Ảnh phải tải lên lại: đổi tên hay chuyển thư mục không tính là ảnh mới." if fee.old_since else "")
    )


_image_failure_alerted_at: datetime | None = None


async def _alert_image_failure(offer: Offer, image_url: str, error: Exception) -> None:
    """Tell the admin group, at most once every IMAGE_FAILURE_ALERT_EVERY, that a Drive image did not reach a parent:
    which image and what Graph said (GraphError carries no access token); nothing of the parent. In memory."""
    global _image_failure_alerted_at
    now = datetime.now(timezone.utc)
    if _image_failure_alerted_at and now - _image_failure_alerted_at < IMAGE_FAILURE_ALERT_EVERY:
        return
    _image_failure_alerted_at = now
    status = getattr(error, "status", None)
    said = f"HTTP {status}: {error.message}" if status else type(error).__name__
    await _send_telegram(
        f"⚠️ Gửi ảnh {offer.label} cho phụ huynh bị lỗi ({said}). Kiểm PUBLIC_BASE_URL trên Render "
        f"({settings.PUBLIC_BASE_URL or 'chưa đặt'}) và mở thử URL ảnh: {image_url} . Báo tối đa 1 lần mỗi giờ."
    )


async def _send_reply_with_images(
    sender_id: str, text: str, quick_replies: list[dict] | None, qa_images: list[str], offers: list[Offer]
) -> list[Offer]:
    """The reply, then the images (at most MAX_IMAGES; an offer that does not fit waits for another turn), the quick
    replies on the last message sent. Returns the offers delivered; an image Messenger refuses is logged and skipped,
    a Drive one also told to the admin group; when the reply said images follow and none of the Drive ones went, the
    parent gets IMAGES_FAILED_MESSAGE."""
    qa_images = qa_images[:MAX_IMAGES]
    chosen, room = [], MAX_IMAGES - len(qa_images)
    for offer in offers:
        if len(offer.urls) <= room:
            chosen.append(offer)
            room -= len(offer.urls)
    images = [(None, _public_image_url(u)) for u in qa_images] + [(o, u) for o in chosen for u in o.urls]
    if text:
        await send_message(sender_id, text, quick_replies=None if images else quick_replies)
    delivered, failed = set(), set()
    for n, (offer, image_url) in enumerate(images, 1):
        try:
            await send_image(sender_id, image_url, quick_replies=quick_replies if n == len(images) else None)
        except Exception as e:
            logger.warning(f"Image {offer.key if offer else image_url} not sent to {sender_id}: {type(e).__name__}")
            if offer:
                failed.add(offer.kind)
                await _alert_image_failure(offer, image_url, e)
            continue
        if offer:
            delivered.add(offer.key)
    if failed and not delivered and failed & _announced(text):
        await send_message(sender_id, IMAGES_FAILED_MESSAGE, quick_replies=quick_replies)
    return [o for o in chosen if o.key in delivered]


def _record_images(sender_id: str, profile: dict, delivered: list[Offer], waiting: dict) -> None:
    """media_sent gets the offers delivered; the WAITING_FLAGS stay true only while still waiting."""
    kinds = {o.kind for o in delivered}
    fields = {
        flag: waiting.get(flag) == "missing" or (waiting.get(flag) == "offered" and kind not in kinds)
        for flag, kind in WAITING_FLAGS.items()
    }
    fields = {k: v for k, v in fields.items() if bool(profile.get(k)) != v}
    if delivered:
        sent_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        fields["media_sent"] = {**(profile.get("media_sent") or {}), **{o.key: sent_at for o in delivered}}
    if fields:
        customer_memory.set_fields(sender_id, fields)


# sender_id -> lock held while one message of that parent is answered. Parents often send two short messages in a
# row and Facebook posts each to /webhook on its own; answered at the same time, both read the history from before
# either, so both got the first-message greeting and the second did not know what the first said.
_sender_locks: dict[str, asyncio.Lock] = {}


async def process_message(
    sender_id: str, text: str, attribution: dict | None = None, phone_from_qr: str | None = None
):
    """Answer one parent message; one parent's messages are answered one at a time, in the order they came."""
    async with _sender_locks.setdefault(sender_id, asyncio.Lock()):
        await _answer_message(sender_id, text, attribution, phone_from_qr)


async def _answer_message(sender_id: str, text: str, attribution: dict | None, phone_from_qr: str | None):
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
        today = _today_vn()

        # Extract customer info alongside the reply, so a phone number sent in this message is known before replying
        response, extracted = await asyncio.gather(
            ai_engine.get_response(
                user_message=text,
                conversation_history=history,
                customer_context=customer_context,
                gap_hours=gap_hours,
                media_note=_media_note(existing_profile, text, last_bot_message, today),
            ),
            ai_engine.extract_customer_info(text, existing_profile, last_bot_message=last_bot_message),
        )
        topics_given = extracted.get("topics")
        # Only JSON true, as phone_declined: models also return "true"/"false"
        upset = extracted.get("upset") is True
        extracted = _clean_extracted(extracted, phone_from_qr, text)

        logger.info(
            f"User {sender_id} ({user_name}): {len(text)} chars "
            f"-> Model: {response.model_used}, Escalate: {response.should_escalate}, Upset: {upset}, "
            f"HasProfile: {bool(existing_profile)}, GapHours: {gap_hours:.1f}, HistoryLen: {len(history)}"
        )

        # Upset again right after a handover a consultant has yet to answer: a short line, not the same apology
        # again nor a second card. Answered (Telegram replies are not in the history) → apology and a new card.
        upset_again = upset and last_bot_message in HANDED_TO_CONSULTANT and has_pending_escalation(sender_id)
        # An upset parent goes to a consultant with an apology, whatever the model replied
        escalated = not upset_again and (response.should_escalate or not response.text or upset)
        topics = clean_topics(topics_given, escalated=escalated)
        covered = []
        if upset_again:
            reply_text = ESCALATION_MESSAGE_UPSET_AGAIN
            await send_message(sender_id, reply_text)
        elif escalated:
            await escalate_to_admin(
                customer_id=sender_id,
                customer_name=full_name,
                question=text,
            )
            if upset:
                reply_text = ESCALATION_MESSAGE_UPSET
            elif had_phone or extracted.get("phone"):
                reply_text = ESCALATION_MESSAGE_HAS_PHONE
            else:
                reply_text = ESCALATION_MESSAGE_ASK_PHONE
            await send_message(sender_id, reply_text)
        else:
            # History keeps the [IMAGES:] and [QUICK:] tokens, and a note per Drive image sent, so the model knows
            # what it already sent
            reply_text = response.text
            clean_text, image_urls = _extract_images(SENT_NOTE.sub("", response.text))
            clean_text, quick_key = _extract_quick_reply(clean_text)
            quick_replies = build_quick_replies(quick_key)
            covered = topics_in_reply(response.text)
            # An image of a "Nếu phụ huynh hỏi …" line goes when the reply says it does, whatever the extraction found
            image_urls, offers, waiting, _ = _plan_images(
                existing_profile, extracted, text, topics, image_urls, last_bot_message, today, _announced(clean_text)
            )

            if settings.MEDIA_SYNC_ENABLED:
                logger.info(f"Drive images planned for {sender_id}: {[o.key for o in offers]}")
            # Messenger shows quick replies only under the latest message: they go on the last one sent
            delivered = await _send_reply_with_images(sender_id, clean_text, quick_replies, image_urls, offers)
            _record_images(sender_id, existing_profile, delivered, waiting)
            if delivered:
                logger.info(f"Drive images sent to {sender_id}: {[o.key for o in delivered]}")
                reply_text += "".join(f" [đã gửi ảnh {o.label}]" for o in delivered)
            for offer in delivered:
                if offer.stale:
                    await _remind_stale_fee(offer.key.split(":")[1], offer.stale, today)

        # Log analytics
        try:
            analytics.log_message(
                user_id=sender_id,
                user_name=full_name or user_name,
                question=mask_phones(text, (existing_profile.get("phone"), extracted.get("phone"), phone_from_qr)),
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

        # Profiles first: a slow Sheet must not hold back the copy that survives a restart.
        await customer_memory.sync_to_github()

        if topics:
            await publish_topics(sender_id, topics, escalated, text)

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
    await asyncio.to_thread(qa_db.reload)  # pulls GitHub main: keep the event loop free
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
    """Test AI response without Facebook (for development/debugging). Requires ?secret=. The model gets the same
    [HỆ THỐNG] image lines as on Messenger; no image is sent."""
    # Load profile + persisted history (same as process_message)
    existing_profile = customer_memory.get_profile(body.user_id)
    customer_context = customer_memory.format_profile_for_prompt(existing_profile)
    history = customer_memory.get_conversation_history(body.user_id)
    gap_hours = customer_memory.get_last_seen_gap_hours(body.user_id)
    last_bot_message = _last_bot_message(history)

    response = await ai_engine.get_response(
        user_message=body.message,
        conversation_history=history,
        customer_context=customer_context,
        gap_hours=gap_hours,
        media_note=_media_note(existing_profile, body.message, last_bot_message, _today_vn()),
    )

    # Extract and save profile, cleaned as in process_message
    try:
        extracted = await ai_engine.extract_customer_info(
            body.message, existing_profile, last_bot_message=last_bot_message
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


def _seen_tg_message(tg_mid) -> bool:
    """True if Telegram already delivered this message (it redelivers when the webhook is slow); records it."""
    if tg_mid and tg_mid in _processed_tg_mids:
        logger.info(f"Skipping duplicate TG message: {tg_mid}")
        return True
    if tg_mid:
        _processed_tg_mids.add(tg_mid)
        if len(_processed_tg_mids) > MAX_DEDUP_SIZE:
            for _ in range(MAX_DEDUP_SIZE // 2):
                _processed_tg_mids.pop()
    return False


MEDIA_COMMAND = "/capnhatanh"


def _is_media_command(message: dict) -> bool:
    """/capnhatanh (or /capnhatanh@<bot>) typed in the admin group, not as a reply."""
    if not isinstance(message, dict) or not isinstance(message.get("text"), str):
        return False
    words = message["text"].split()
    return (
        bool(words)
        and words[0].split("@", 1)[0] == MEDIA_COMMAND
        and not message.get("reply_to_message")
        and bool(settings.TELEGRAM_CHAT_ID)
        and str((message.get("chat") or {}).get("id")) == settings.TELEGRAM_CHAT_ID
    )


async def _sync_media_and_report():
    report = await media.sync_media()
    await _send_telegram(media.sync_summary(report, datetime.now(VN_TZ).date()))


@app.post("/telegram-webhook")
async def handle_telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    """Handle admin replies and /capnhatanh from Telegram group. Telegram sends the secret_token set by
    /setup-telegram-webhook."""
    if not _secret_matches(request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")):
        raise HTTPException(status_code=403, detail="Invalid secret")

    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return {"status": "ignored"}
    message = data.get("message", {})
    if _is_media_command(message):
        if _seen_tg_message(message.get("message_id", 0)):
            return {"status": "duplicate"}
        # A sync downloads images for a while: answer Telegram now (it redelivers slow updates), report when done.
        background_tasks.add_task(_sync_media_and_report)
        return {"status": "media_sync_started"}

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

        if _seen_tg_message(message.get("message_id", 0)):
            return {"status": "duplicate"}

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
        # The parent got a consultant's answer: none of their cards is waiting any more (the answer often covers
        # several; a later upset message must then reach a consultant again, see _answer_message).
        drop_pending_escalations(customer_id)

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

        logger.info(f"Admin replied to escalation for {customer_name}: {admin_text[:100]}")
        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Error handling admin reply: {e}", exc_info=True)
        return {"status": "error", "detail": str(e)}


@app.get("/media")
async def get_media(_: None = Depends(require_secret)):
    """Images synced from Google Drive (app/media.py): counts, each image with its kind and public URL, files
    skipped. Requires ?secret=."""
    return media.catalog()


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

import hashlib
import hmac
import json
import logging
import mimetypes
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Quick reply buttons, the only source: the model ends a reply with [QUICK:<key>] (keys taught in SYSTEM_PROMPT).
# Each button is (title shown, at most 20 characters; meaning the bot processes when the parent taps it).
QUICK_REPLIES: dict[str, list[tuple[str, str]]] = {
    "topics": [
        ("Cơ sở quan tâm", "Trường có những cơ sở nào ạ?"),
        ("Chương trình học", "Trường dạy chương trình gì ạ?"),
        ("Đặt lịch tham quan", "Em muốn đặt lịch tham quan trường ạ"),
        ("Ưu đãi", "Hiện tại Nhà trường có ưu đãi gì ạ?"),
    ],
    "age": [
        ("Dưới 2 tuổi", "Bé nhà em dưới 2 tuổi ạ"),
        ("2-3 tuổi", "Bé nhà em 2-3 tuổi ạ"),
        ("3-5 tuổi", "Bé nhà em 3-5 tuổi ạ"),
        ("5-6 tuổi", "Bé nhà em 5-6 tuổi ạ"),
    ],
    "campus": [
        ("Chùa Láng", "Em quan tâm cơ sở Chùa Láng ạ"),
        ("Mỹ Đình", "Em quan tâm cơ sở Mỹ Đình ạ"),
        ("Kim Mã", "Em quan tâm cơ sở Kim Mã ạ"),
    ],
    # Messenger's own button offering the phone number of the parent's Facebook account (no title).
    "phone": [],
    # Inviting to a trial week or a visit; the time buttons below come only once the parent agrees.
    "trial_invite": [
        ("Đăng ký học thử", "Em muốn đăng ký cho bé học thử 1 tuần ạ"),
        ("Tìm hiểu thêm", "Em muốn tìm hiểu thêm trước ạ"),
    ],
    "visit_invite": [
        ("Đặt lịch tham quan", "Em muốn đặt lịch tham quan trường ạ"),
        ("Tìm hiểu thêm", "Em muốn tìm hiểu thêm trước ạ"),
    ],
    "visit_time": [
        ("Buổi sáng", "Em muốn hẹn tham quan buổi sáng ạ"),
        ("Buổi chiều", "Em muốn hẹn tham quan buổi chiều ạ"),
    ],
    "trial_week": [
        ("Tuần này", "Em muốn cho bé học thử tuần này ạ"),
        ("Tuần sau", "Em muốn cho bé học thử tuần sau ạ"),
    ],
}
QUICK_REPLY_PREFIX = "QR:"
# Sent with every message the bot sends; Facebook returns it in the message echo, so an echo without it is
# a message staff typed in the Page inbox.
BOT_MESSAGE_METADATA = "casa-bot"

GET_STARTED_PAYLOAD = "GET_STARTED"
# Questions offered when a parent opens a new conversation; payload -> question.
ICE_BREAKERS: dict[str, str] = {
    "IB_1": "Học phí của trường là bao nhiêu?",
    "IB_2": "Trường nhận bé từ bao nhiêu tháng?",
    "IB_3": "Hiện tại Nhà trường có ưu đãi gì?",
    "IB_4": "Có chương trình học thử miễn phí cho học sinh mới không?",
}


class GraphError(Exception):
    """The Graph API refused a send: its HTTP status and error message, without the access token."""

    def __init__(self, what: str, status: int, message: str):
        super().__init__(f"Messenger {what} API error: {status} {message}")
        self.status, self.message = status, message


def _graph_error(what: str, response: httpx.Response) -> GraphError:
    try:
        error = response.json()["error"]
        message = f"{error['message']} (code {error.get('code')})"
    except (ValueError, KeyError, TypeError):
        message = response.text[:300]
    token = settings.FB_PAGE_ACCESS_TOKEN
    return GraphError(what, response.status_code, message.replace(token, "***") if token else message)


def _quick_reply_payload(key: str, index: int) -> str:
    return f"{QUICK_REPLY_PREFIX}{key}:{index}"


def build_quick_replies(key: str) -> list[dict] | None:
    """Messenger quick_replies for a QUICK_REPLIES key; None for an unknown key."""
    if key not in QUICK_REPLIES:
        return None
    if key == "phone":
        return [{"content_type": "user_phone_number"}]
    return [
        {"content_type": "text", "title": title, "payload": _quick_reply_payload(key, i)}
        for i, (title, _) in enumerate(QUICK_REPLIES[key])
    ]


def quick_reply_meaning(payload: str) -> str | None:
    """Meaning of the text button whose payload build_quick_replies() made; None for any other payload."""
    for key, buttons in QUICK_REPLIES.items():
        for i, (_, meaning) in enumerate(buttons):
            if payload == _quick_reply_payload(key, i):
                return meaning
    return None


async def send_message(recipient_id: str, text: str, quick_replies: list[dict] | None = None):
    """Send a text message to a user via Facebook Messenger. quick_replies go on the last 2000-char chunk."""
    url = f"{settings.FB_GRAPH_API_URL}/me/messages"

    # Split long messages (Messenger limit is 2000 chars)
    chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)]

    async with httpx.AsyncClient() as client:
        for n, chunk in enumerate(chunks, 1):
            message = {"text": chunk, "metadata": BOT_MESSAGE_METADATA}
            if quick_replies and n == len(chunks):
                message["quick_replies"] = quick_replies
            payload = {
                "recipient": {"id": recipient_id},
                "message": message,
                "messaging_type": "RESPONSE",
            }
            response = await client.post(
                url,
                json=payload,
                params={"access_token": settings.FB_PAGE_ACCESS_TOKEN},
                timeout=30,
            )
            if response.status_code != 200:
                error = _graph_error("message", response)
                logger.error(f"Failed to send message: {error}")
                raise error
            logger.info(f"Message sent to {recipient_id}")


UPLOAD_TIMEOUT = 60
# Image file uploaded -> ((mtime_ns, size) of the file uploaded, the attachment_id Graph gave): the next parent gets
# the same reusable attachment by its id, without uploading the file again. In memory: a restart uploads again.
_attachment_ids: dict[Path, tuple[tuple[int, int], str]] = {}


async def _post_image(
    client: httpx.AsyncClient, recipient_id: str, payload: dict, quick_replies: list[dict] | None, file: Path | None = None
) -> dict:
    """POST one image message with this attachment payload, `file` as multipart `filedata` when given. Returns the
    Graph JSON; raises GraphError when Graph refuses it."""
    message = {"attachment": {"type": "image", "payload": payload}, "metadata": BOT_MESSAGE_METADATA}
    if quick_replies:
        message["quick_replies"] = quick_replies
    url = f"{settings.FB_GRAPH_API_URL}/me/messages"
    params = {"access_token": settings.FB_PAGE_ACCESS_TOKEN}
    if file is None:
        body = {"recipient": {"id": recipient_id}, "message": message, "messaging_type": "RESPONSE"}
        response = await client.post(url, json=body, params=params, timeout=30)
    else:
        fields = {
            "recipient": json.dumps({"id": recipient_id}),
            "message": json.dumps(message),  # ASCII: no charset to agree on for the form field
            "messaging_type": "RESPONSE",
        }
        content_type = mimetypes.guess_type(file.name)[0] or "image/jpeg"
        upload = {"filedata": (file.name, file.read_bytes(), content_type)}
        response = await client.post(url, data=fields, files=upload, params=params, timeout=UPLOAD_TIMEOUT)
    if response.status_code != 200:
        raise _graph_error("image", response)
    return response.json()


async def _send_file(client: httpx.AsyncClient, recipient_id: str, file: Path, quick_replies: list[dict] | None) -> str:
    """Send the image `file`: by the attachment_id of its last upload while the file is unchanged, else (or when
    Graph refuses that id, e.g. expired) uploaded once more. Returns how it went, for the log."""
    stat = file.stat()
    stamp = (stat.st_mtime_ns, stat.st_size)
    cached = _attachment_ids.get(file)
    if cached and cached[0] == stamp:
        try:
            await _post_image(client, recipient_id, {"attachment_id": cached[1]}, quick_replies)
            return f"attachment {cached[1]}"
        except GraphError as e:
            logger.warning(f"Attachment {cached[1]} of {file.name} refused ({e.status} {e.message}): uploading again")
            del _attachment_ids[file]
    sent = await _post_image(client, recipient_id, {"is_reusable": True}, quick_replies, file=file)
    if sent.get("attachment_id"):
        _attachment_ids[file] = (stamp, sent["attachment_id"])
    return f"uploaded, attachment {sent.get('attachment_id')}"


async def send_image(recipient_id: str, image: Path | str, quick_replies: list[dict] | None = None):
    """Send an image via Facebook Messenger: a Path is an image file on disk, uploaded (multipart `filedata`); a str
    is a URL Facebook downloads itself. Raises GraphError (without the access token) when Graph refuses it."""
    async with httpx.AsyncClient() as client:
        try:
            if isinstance(image, Path):
                how = await _send_file(client, recipient_id, image, quick_replies)
            else:
                await _post_image(client, recipient_id, {"url": image, "is_reusable": True}, quick_replies)
                how = "by URL"
        except GraphError as error:
            logger.error(f"Failed to send image: {error}")
            raise
    logger.info(f"Image sent to {recipient_id}: {image.name if isinstance(image, Path) else image} ({how})")


async def send_typing_indicator(recipient_id: str, action: str = "typing_on"):
    """Show typing indicator to user."""
    url = f"{settings.FB_GRAPH_API_URL}/me/messages"
    payload = {
        "recipient": {"id": recipient_id},
        "sender_action": action,
    }
    async with httpx.AsyncClient() as client:
        await client.post(
            url,
            json=payload,
            params={"access_token": settings.FB_PAGE_ACCESS_TOKEN},
            timeout=10,
        )


async def set_messenger_profile() -> dict:
    """Register the Get Started button and the ice breakers on the Page. Returns the Graph API JSON."""
    profile = {
        "get_started": {"payload": GET_STARTED_PAYLOAD},
        "ice_breakers": [
            {
                "locale": "default",
                "call_to_actions": [{"question": q, "payload": p} for p, q in ICE_BREAKERS.items()],
            }
        ],
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{settings.FB_GRAPH_API_URL}/me/messenger_profile",
            json=profile,
            params={"access_token": settings.FB_PAGE_ACCESS_TOKEN},
            timeout=30,
        )
    return response.json()


async def get_user_profile(user_id: str) -> dict:
    """Get user profile info from Facebook."""
    url = f"{settings.FB_GRAPH_API_URL}/{user_id}"
    params = {
        "fields": "first_name,last_name",
        "access_token": settings.FB_PAGE_ACCESS_TOKEN,
    }
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
    return {}


def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify that the webhook request is from Facebook."""
    if not settings.FB_APP_SECRET:
        return True  # Skip verification if no app secret configured
    expected = hmac.new(
        settings.FB_APP_SECRET.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature)

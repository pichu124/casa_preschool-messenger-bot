import hashlib
import hmac
import logging

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
                logger.error(f"Failed to send message: {response.status_code} {response.text}")
                raise Exception(f"Messenger API error: {response.status_code}")
            logger.info(f"Message sent to {recipient_id}")


async def send_image(recipient_id: str, image_url: str, quick_replies: list[dict] | None = None):
    """Send an image attachment via Facebook Messenger."""
    url = f"{settings.FB_GRAPH_API_URL}/me/messages"
    message = {
        "attachment": {
            "type": "image",
            "payload": {"url": image_url, "is_reusable": True},
        },
        "metadata": BOT_MESSAGE_METADATA,
    }
    if quick_replies:
        message["quick_replies"] = quick_replies
    payload = {
        "recipient": {"id": recipient_id},
        "message": message,
        "messaging_type": "RESPONSE",
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json=payload,
            params={"access_token": settings.FB_PAGE_ACCESS_TOKEN},
            timeout=30,
        )
        if response.status_code != 200:
            logger.error(f"Failed to send image: {response.status_code} {response.text}")
            raise Exception(f"Messenger image API error: {response.status_code}")
        logger.info(f"Image sent to {recipient_id}: {image_url}")


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

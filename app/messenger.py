import hashlib
import hmac
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def send_message(recipient_id: str, text: str, access_token: str | None = None):
    """Send a text message to a user via Facebook Messenger."""
    token = access_token or settings.FB_PAGE_ACCESS_TOKEN
    url = f"{settings.FB_GRAPH_API_URL}/me/messages"

    # Split long messages (Messenger limit is 2000 chars)
    chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)]

    async with httpx.AsyncClient() as client:
        for chunk in chunks:
            payload = {
                "recipient": {"id": recipient_id},
                "message": {"text": chunk},
                "messaging_type": "RESPONSE",
            }
            response = await client.post(
                url,
                json=payload,
                params={"access_token": token},
                timeout=30,
            )
            if response.status_code != 200:
                logger.error(f"Failed to send message: {response.status_code} {response.text}")
                raise Exception(f"Messenger API error: {response.status_code}")
            logger.info(f"Message sent to {recipient_id}")


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

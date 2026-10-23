"""Lead events and message topics to Google Sheet through an Apps Script web app, which keeps one Leads row per
parent (customer_id) and updates it on each event, and appends one "Chủ đề" row per message with topics (setup:
docs/google-sheet-leads.md)."""
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))
# "event" sent as its "Sự kiện" text: Apps Script deployed before the event shows an unknown event as is.
SHEET_EVENTS = {"info_update": "Cập nhật thông tin"}


def _now() -> str:
    return datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S")


async def post_lead_row(kind: str, row: dict) -> bool:
    """POST `row` plus token, event (kind, or its SHEET_EVENTS text) and Vietnam time to LEADS_SHEET_WEBHOOK_URL.

    True only when the web app answers {"ok": true}. Empty URL: False without any request. Never raises; logs
    carry neither the URL (whoever has it can post rows) nor the row (it has the parent's phone number).
    """
    body = {**row, "token": settings.LEADS_SHEET_TOKEN, "event": SHEET_EVENTS.get(kind, kind), "time": _now()}
    return await _post(f"Lead {kind}", body)


async def post_topic_row(row: dict) -> bool:
    """POST `row` with type "topic", token and Vietnam time: one row of the "Chủ đề" tab. Only when
    TOPICS_SHEET_ENABLED (a script without that tab writes the body into the Leads tab); as post_lead_row otherwise,
    logs carry no message text."""
    if not settings.TOPICS_SHEET_ENABLED:
        return False
    body = {"type": "topic", **row, "token": settings.LEADS_SHEET_TOKEN, "time": _now()}
    return await _post("Topic row", body)


async def _post(what: str, body: dict) -> bool:
    url = settings.LEADS_SHEET_WEBHOOK_URL
    if not url:
        return False
    try:
        # The web app runs doPost, then answers 302 to script.googleusercontent.com where its output is.
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.post(url, json=body)
        result = resp.json()
    except Exception as e:
        logger.warning(f"{what} not written to Google Sheet: {type(e).__name__}")
        return False
    if isinstance(result, dict) and result.get("ok") is True:
        return True
    logger.warning(f"{what} rejected by Google Sheet web app (HTTP {resp.status_code})")
    return False

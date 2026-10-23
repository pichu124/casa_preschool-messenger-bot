"""Lead events to Google Sheet through an Apps Script web app, which keeps one row per parent (customer_id)
and updates it on each event (setup: docs/google-sheet-leads.md)."""
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

VN_TZ = timezone(timedelta(hours=7))
# "event" sent as its "Sự kiện" text: Apps Script deployed before the event shows an unknown event as is.
SHEET_EVENTS = {"info_update": "Cập nhật thông tin"}


async def post_lead_row(kind: str, row: dict) -> bool:
    """POST `row` plus token, event (kind, or its SHEET_EVENTS text) and Vietnam time to LEADS_SHEET_WEBHOOK_URL.

    True only when the web app answers {"ok": true}. Empty URL: False without any request. Never raises; logs
    carry neither the URL (whoever has it can post rows) nor the row (it has the parent's phone number).
    """
    url = settings.LEADS_SHEET_WEBHOOK_URL
    if not url:
        return False
    body = {
        **row,
        "token": settings.LEADS_SHEET_TOKEN,
        "event": SHEET_EVENTS.get(kind, kind),
        "time": datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        # The web app runs doPost, then answers 302 to script.googleusercontent.com where its output is.
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.post(url, json=body)
        result = resp.json()
    except Exception as e:
        logger.warning(f"Lead {kind} not written to Google Sheet: {type(e).__name__}")
        return False
    if isinstance(result, dict) and result.get("ok") is True:
        return True
    logger.warning(f"Lead {kind} rejected by Google Sheet web app (HTTP {resp.status_code})")
    return False

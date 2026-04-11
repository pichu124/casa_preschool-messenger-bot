"""Customer memory: persist customer profiles across sessions."""
import base64
import json
import logging
from datetime import datetime
from pathlib import Path

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

CUSTOMERS_PATH = "data/customers.json"
REPO = "pichu124/casa_preschool-messenger-bot"
GITHUB_FILE_PATH = "data/customers.json"
BRANCH = "main"

# Conversation history settings
MAX_HISTORY_MESSAGES = 30  # Trim history when exceeds this
KEEP_AFTER_TRIM = 20  # Keep this many messages after trim/summarization
RETURNING_GAP_HOURS = 24  # Gap > 24h = returning customer (special greeting)

# In-memory cache: loaded at startup, persisted to disk + GitHub on updates
_customers: dict[str, dict] = {}
_loaded = False


def _load_from_disk():
    """Load customer profiles from local JSON file, fallback to GitHub."""
    global _customers, _loaded
    path = Path(CUSTOMERS_PATH)
    if path.exists():
        try:
            _customers = json.loads(path.read_text(encoding="utf-8"))
            logger.info(f"Loaded {len(_customers)} customer profiles from disk")
            _loaded = True
            return
        except (json.JSONDecodeError, ValueError):
            _customers = {}

    # File doesn't exist or is corrupt - try pulling from GitHub
    token = settings.GITHUB_TOKEN
    if token:
        try:
            headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github.v3+json",
            }
            api_url = f"https://api.github.com/repos/{REPO}/contents/{GITHUB_FILE_PATH}"
            resp = httpx.get(api_url, headers=headers, params={"ref": BRANCH}, timeout=15)
            if resp.status_code == 200:
                content_b64 = resp.json().get("content", "")
                content = base64.b64decode(content_b64).decode("utf-8")
                _customers = json.loads(content)
                # Save to local disk for faster subsequent loads
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                logger.info(f"Loaded {len(_customers)} customer profiles from GitHub")
            else:
                logger.info(f"No customers file on GitHub ({resp.status_code}), starting empty")
                _customers = {}
        except Exception as e:
            logger.warning(f"Failed to load customers from GitHub: {e}")
            _customers = {}
    else:
        _customers = {}

    _loaded = True


def _save_to_disk():
    """Save customer profiles to local JSON file."""
    path = Path(CUSTOMERS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_customers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def _push_to_github():
    """Push customers.json to GitHub for persistence across deploys."""
    token = settings.GITHUB_TOKEN
    if not token:
        logger.debug("GITHUB_TOKEN not set, skipping GitHub sync for customers")
        return False

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    api_url = f"https://api.github.com/repos/{REPO}/contents/{GITHUB_FILE_PATH}"

    async with httpx.AsyncClient() as client:
        # Get current SHA if file exists
        current_sha = None
        resp = await client.get(api_url, headers=headers, params={"ref": BRANCH}, timeout=15)
        if resp.status_code == 200:
            current_sha = resp.json().get("sha")

        content = json.dumps(_customers, ensure_ascii=False, indent=2)
        encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        payload = {
            "message": "[skip deploy] Auto-update customer profiles",
            "content": encoded,
            "branch": BRANCH,
        }
        if current_sha:
            payload["sha"] = current_sha

        resp = await client.put(api_url, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            logger.info(f"Customer profiles pushed to GitHub ({len(_customers)} customers)")
            return True
        else:
            logger.error(f"Failed to push customers to GitHub: {resp.status_code} {resp.text[:200]}")
            return False


def get_profile(customer_id: str) -> dict:
    """Get customer profile by ID, returns empty dict if not found."""
    if not _loaded:
        _load_from_disk()
    return _customers.get(customer_id, {})


async def update_profile(customer_id: str, updates: dict) -> dict:
    """Merge updates into existing profile, save to disk + GitHub.

    Only updates fields that have meaningful values (non-empty strings).
    Keeps existing values if new value is empty.
    """
    if not _loaded:
        _load_from_disk()

    existing = _customers.get(customer_id, {})

    # Merge: only override if new value is non-empty
    merged = {**existing}
    for key, value in updates.items():
        if value and str(value).strip():
            # For lists, merge and dedup
            if isinstance(value, list):
                existing_list = merged.get(key, [])
                if isinstance(existing_list, list):
                    merged[key] = list(dict.fromkeys(existing_list + value))  # dedup, preserve order
                else:
                    merged[key] = value
            else:
                merged[key] = value

    # Track metadata
    if "first_seen" not in merged:
        merged["first_seen"] = datetime.now().isoformat()
    merged["last_seen"] = datetime.now().isoformat()
    merged["message_count"] = existing.get("message_count", 0) + 1

    _customers[customer_id] = merged
    _save_to_disk()

    # Push to GitHub in background-friendly way (fire and forget)
    try:
        await _push_to_github()
    except Exception as e:
        logger.warning(f"GitHub sync failed but local save succeeded: {e}")

    return merged


def format_profile_for_prompt(profile: dict) -> str:
    """Format customer profile as a context hint for the AI prompt."""
    if not profile:
        return ""

    parts = []
    if profile.get("kid_name"):
        kid_info = f"tên {profile['kid_name']}"
        if profile.get("kid_age"):
            kid_info += f", {profile['kid_age']} tuổi"
        if profile.get("kid_gender"):
            kid_info += f" ({profile['kid_gender']})"
        parts.append(f"Bé: {kid_info}")
    elif profile.get("kid_age"):
        parts.append(f"Bé: {profile['kid_age']} tuổi")

    if profile.get("parent_name"):
        parts.append(f"Phụ huynh: {profile['parent_name']}")
    if profile.get("interested_program"):
        parts.append(f"Quan tâm hệ: {profile['interested_program']}")
    if profile.get("interested_campus"):
        parts.append(f"Cơ sở quan tâm: {profile['interested_campus']}")
    if profile.get("address"):
        parts.append(f"Địa chỉ: {profile['address']}")
    if profile.get("phone"):
        parts.append(f"SĐT: {profile['phone']}")
    if profile.get("concerns"):
        concerns = profile["concerns"]
        if isinstance(concerns, list) and concerns:
            parts.append(f"Mối quan tâm: {', '.join(concerns)}")
    if profile.get("kid_traits"):
        traits = profile["kid_traits"]
        if isinstance(traits, list) and traits:
            parts.append(f"Tính cách bé: {', '.join(traits)}")

    result = ""
    if parts:
        result = "[THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT]:\n" + "\n".join(f"- {p}" for p in parts)

    # Append session summaries if available (background context from past conversations)
    summaries = profile.get("session_summaries", [])
    if summaries:
        summary_section = "\n\n[TÓM TẮT CÁC LẦN TRÒ CHUYỆN TRƯỚC ĐÂY]:\n"
        # Show last 5 summaries to avoid prompt bloat
        for s in summaries[-5:]:
            date = s.get("date", "")
            text = s.get("summary", "")
            if text:
                summary_section += f"- [{date}] {text}\n"
        result += summary_section

    return result


def get_conversation_history(customer_id: str) -> list[dict]:
    """Get conversation history from customer profile.

    Returns list of {role, content} dicts, stripped of timestamps for AI compat.
    """
    if not _loaded:
        _load_from_disk()
    profile = _customers.get(customer_id, {})
    history_raw = profile.get("conversation_history", [])
    # Return only role + content for AI compatibility
    return [{"role": m["role"], "content": m["content"]} for m in history_raw if "role" in m and "content" in m]


async def append_to_history(customer_id: str, role: str, content: str):
    """Append a message to conversation history. Auto-trim and summarize when needed.

    Returns True if a summarization was triggered (caller may want to log).
    """
    if not _loaded:
        _load_from_disk()

    profile = _customers.get(customer_id, {})
    history = profile.get("conversation_history", [])

    history.append({
        "role": role,
        "content": content,
        "timestamp": datetime.now().isoformat(),
    })

    summarized = False
    # Trigger summarization if too many messages
    if len(history) > MAX_HISTORY_MESSAGES:
        try:
            from app.ai_engine import ai_engine_instance
            # Summarize older messages, keep recent ones
            to_summarize = history[:-KEEP_AFTER_TRIM]
            keep = history[-KEEP_AFTER_TRIM:]

            summary_text = await ai_engine_instance.summarize_conversation(to_summarize)
            if summary_text:
                summaries = profile.get("session_summaries", [])
                summaries.append({
                    "date": datetime.now().strftime("%Y-%m-%d"),
                    "summary": summary_text,
                })
                profile["session_summaries"] = summaries
                history = keep
                summarized = True
                logger.info(f"Summarized {len(to_summarize)} messages for {customer_id}")
        except Exception as e:
            logger.warning(f"Summarization failed for {customer_id}, just trimming: {e}")
            history = history[-KEEP_AFTER_TRIM:]

    profile["conversation_history"] = history
    _customers[customer_id] = profile
    _save_to_disk()

    # Push to GitHub (best effort)
    try:
        await _push_to_github()
    except Exception as e:
        logger.warning(f"GitHub sync failed for history append: {e}")

    return summarized


def get_session_summaries(customer_id: str) -> list[dict]:
    """Get list of session summaries for a customer."""
    if not _loaded:
        _load_from_disk()
    profile = _customers.get(customer_id, {})
    return profile.get("session_summaries", [])


def get_last_seen_gap_hours(customer_id: str) -> float:
    """Calculate hours since last_seen. Returns 0 if no profile or first contact."""
    if not _loaded:
        _load_from_disk()
    profile = _customers.get(customer_id, {})
    last_seen_str = profile.get("last_seen")
    if not last_seen_str:
        return 0.0
    try:
        last_seen = datetime.fromisoformat(last_seen_str)
        delta = datetime.now() - last_seen
        return delta.total_seconds() / 3600
    except (ValueError, TypeError):
        return 0.0


def get_all_profiles() -> dict:
    """Return all customer profiles (for admin/dashboard)."""
    if not _loaded:
        _load_from_disk()
    return _customers

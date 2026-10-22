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
GITHUB_FILE_PATH = "data/customers.json"
BRANCH = "main"

# Conversation history settings
MAX_HISTORY_MESSAGES = 30  # Trim history when exceeds this
KEEP_AFTER_TRIM = 20  # Keep this many messages after trim/summarization
RETURNING_GAP_HOURS = 24  # Gap > 24h = returning customer (special greeting)

# In-memory cache: loaded at startup, persisted to disk on updates; sync_to_github() pushes it to CUSTOMERS_GITHUB_REPO
_customers: dict[str, dict] = {}
_loaded = False
# Set when the startup pull from CUSTOMERS_GITHUB_REPO failed: pushing the disk copy would overwrite the repo.
_pull_failed = False


def _read_disk() -> dict:
    path = Path(CUSTOMERS_PATH)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _pull_from_github(token: str, repo: str) -> dict | None:
    """customers.json from `repo`, or None if the repo has no such file yet. Raises on any other outcome."""
    # Raw media type: the file body itself, up to 100 MB (the default JSON one has empty `content` above 1 MB).
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.raw+json",
    }
    api_url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_FILE_PATH}"
    resp = httpx.get(api_url, headers=headers, params={"ref": BRANCH}, timeout=15)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise RuntimeError(f"GitHub returned {resp.status_code}")
    customers = json.loads(resp.content)
    if not isinstance(customers, dict):
        raise ValueError("customers.json is not a JSON object")
    return customers


def _load_from_disk():
    """Load customer profiles. With CUSTOMERS_GITHUB_REPO set, that repo wins over the disk copy (which may be
    stale, e.g. baked into the image); disk is used when the repo has no file yet, or read-only if the pull fails."""
    global _customers, _loaded, _pull_failed
    token = settings.GITHUB_TOKEN
    repo = settings.CUSTOMERS_GITHUB_REPO
    remote = None
    if token and repo:
        try:
            remote = _pull_from_github(token, repo)
        except Exception as e:
            _pull_failed = True
            logger.error(
                f"Failed to load customers from {repo} ({type(e).__name__}: {e}): using the disk copy, "
                "GitHub sync for customers is OFF until restart so the repo is not overwritten"
            )

    if remote is not None:
        _customers = remote
        _save_to_disk()
        logger.info(f"Loaded {len(_customers)} customer profiles from GitHub")
    else:
        _customers = _read_disk()
        logger.info(f"Loaded {len(_customers)} customer profiles from disk")
    _loaded = True


def _save_to_disk():
    """Save customer profiles to local JSON file."""
    path = Path(CUSTOMERS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_customers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def sync_to_github() -> bool:
    """Push customers.json to CUSTOMERS_GITHUB_REPO for persistence across deploys. Call once per message.

    Never raises: on failure logs a warning and returns False (the local save is kept).
    """
    token = settings.GITHUB_TOKEN
    repo = settings.CUSTOMERS_GITHUB_REPO
    if not token or not repo:
        logger.debug("GITHUB_TOKEN or CUSTOMERS_GITHUB_REPO not set, skipping GitHub sync for customers")
        return False
    if not _loaded:
        _load_from_disk()
    if _pull_failed:
        logger.error(f"Skipping GitHub sync for customers: startup load from {repo} failed (restart to retry)")
        return False

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    api_url = f"https://api.github.com/repos/{repo}/contents/{GITHUB_FILE_PATH}"

    try:
        async with httpx.AsyncClient() as client:
            # Get current SHA if file exists. Object media type: sha up to 100 MB (`content` empty above 1 MB);
            # the default one does not support files above 1 MB.
            current_sha = None
            sha_headers = {**headers, "Accept": "application/vnd.github.object+json"}
            resp = await client.get(api_url, headers=sha_headers, params={"ref": BRANCH}, timeout=15)
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
            logger.error(f"Failed to push customers to GitHub: {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        logger.warning(f"GitHub sync failed but local save succeeded: {e}")
        return False


def get_profile(customer_id: str) -> dict:
    """Get customer profile by ID, returns empty dict if not found."""
    if not _loaded:
        _load_from_disk()
    return _customers.get(customer_id, {})


async def update_profile(customer_id: str, updates: dict) -> dict:
    """Merge updates into existing profile and save to disk (sync_to_github() pushes it).

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
    return merged


def set_fields(customer_id: str, fields: dict) -> dict:
    """Overwrite `fields` in the profile and save to disk (sync_to_github() pushes it), without touching
    last_seen/message_count: for data that is not a parent message (ad referral, follow-up timestamp)."""
    if not _loaded:
        _load_from_disk()
    profile = {**_customers.get(customer_id, {}), **fields}
    _customers[customer_id] = profile
    _save_to_disk()
    return profile


def reset_customer(customer_id: str) -> bool:
    """Forget everything about one customer (profile, history, summaries, lead card, follow-up) and save to disk
    (sync_to_github() pushes it), so their next message is a first message. False if there was no profile."""
    if not _loaded:
        _load_from_disk()
    if _customers.pop(customer_id, None) is None:
        return False
    _save_to_disk()
    return True


# Consulting funnel stages, in order; lead_stage() returns the furthest one reached.
STAGES = ("Mới", "Đã biết tuổi/cơ sở", "Đã có SĐT", "Đã hẹn tham quan/học thử")


def _knows_place(profile: dict) -> bool:
    return bool(profile.get("interested_campus") or profile.get("area") or profile.get("address"))


def lead_stage(profile: dict) -> str:
    if profile.get("visit_request"):
        return STAGES[3]
    if profile.get("phone"):
        return STAGES[2]
    if profile.get("kid_age") or _knows_place(profile):
        return STAGES[1]
    return STAGES[0]


def missing_fields(profile: dict) -> list[str]:
    """What the bot still needs to ask for. No phone once the parent declined to leave one."""
    missing = []
    if not profile.get("kid_age"):
        missing.append("tuổi bé")
    if not _knows_place(profile):
        missing.append("cơ sở/khu vực")
    if not profile.get("phone") and not profile.get("phone_declined"):
        missing.append("SĐT/Zalo")
    return missing


def _consulting_state(profile: dict) -> str:
    lines = [f"Giai đoạn: {lead_stage(profile)}"]
    missing = missing_fields(profile)
    if missing:
        lines.append(f"Còn thiếu: {', '.join(missing)}")
    if profile.get("phone_declined") and not profile.get("phone"):
        lines.append("Phụ huynh đã từ chối để lại SĐT: có")
    if profile.get("lead_source") == "ads":
        ad_title = profile.get("ad_title")
        lines.append(f'Nguồn: quảng cáo "{ad_title}"' if ad_title else "Nguồn: quảng cáo")
    if profile.get("visit_request"):
        booked = f"Đã hẹn: {profile['visit_request']}"
        if not profile.get("phone") and not profile.get("phone_declined"):
            booked += (
                "; chưa có SĐT → sau câu xác nhận ngắn, xin SĐT/Zalo mềm 1 lần (\"nếu tiện…\") để tư vấn viên gọi "
                "xác nhận giờ, kèm [QUICK:phone]; từ lúc hẹn em đã xin rồi thì không xin lại"
            )
        lines.append(booked)
    return "[TRẠNG THÁI TƯ VẤN]:\n" + "\n".join(f"- {line}" for line in lines)


def format_profile_for_prompt(profile: dict) -> str:
    """Format customer profile as a context hint for the AI prompt."""
    if not profile:
        return ""

    parts = []
    age = str(profile.get("kid_age") or "")
    # kid_age thường đã có đơn vị ("3 tuổi", "20 tháng"); chỉ thêm "tuổi" cho số trơn.
    if age and not any(unit in age.lower() for unit in ("tuổi", "tháng")):
        age += " tuổi"
    if profile.get("kid_name"):
        kid_info = f"tên {profile['kid_name']}"
        if age:
            kid_info += f", {age}"
        if profile.get("kid_gender"):
            kid_info += f" ({profile['kid_gender']})"
        parts.append(f"Bé: {kid_info}")
    elif age:
        parts.append(f"Bé: {age}")

    # parent_name (thường là tên Facebook) cố ý không đưa vào: model dễ đoán giới tính để xưng "anh/chị".
    if profile.get("interested_program"):
        parts.append(f"Quan tâm hệ: {profile['interested_program']}")
    if profile.get("interested_campus"):
        parts.append(f"Cơ sở quan tâm: {profile['interested_campus']}")
    if profile.get("area"):
        parts.append(f"Khu vực: {profile['area']}")
    if profile.get("address"):
        parts.append(f"Địa chỉ: {profile['address']}")
    if profile.get("expected_start"):
        parts.append(f"Dự kiến nhập học: {profile['expected_start']}")
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
        result = "[THÔNG TIN KHÁCH HÀNG ĐÃ BIẾT]:\n" + "\n".join(f"- {p}" for p in parts) + "\n\n"
    result += _consulting_state(profile)

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

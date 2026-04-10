"""Analytics module: log messages and compute stats for dashboard."""
import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

ANALYTICS_PATH = "data/analytics.jsonl"
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def log_message(
    user_id: str,
    user_name: str,
    question: str,
    model_used: str,
    escalated: bool,
    category: str = "",
):
    """Append a message record to analytics log (JSONL format)."""
    path = Path(ANALYTICS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Rotate file if too large (keep recent data only)
    try:
        if path.exists() and path.stat().st_size > MAX_FILE_SIZE:
            _rotate_log(path)
    except Exception as e:
        logger.warning(f"Failed to rotate analytics log: {e}")

    record = {
        "timestamp": datetime.now().isoformat(),
        "user_id": user_id,
        "user_name": user_name,
        "question": question[:500],  # Truncate long questions
        "model_used": model_used,
        "escalated": escalated,
        "category": category,
    }

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"Failed to write analytics log: {e}")


def _rotate_log(path: Path):
    """Keep only last 30 days of data when file gets too big."""
    cutoff = datetime.now() - timedelta(days=30)
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
                ts = datetime.fromisoformat(r["timestamp"])
                if ts >= cutoff:
                    records.append(line)
            except Exception:
                continue

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(records)


def _read_records() -> list[dict]:
    """Read all analytics records from JSONL file."""
    path = Path(ANALYTICS_PATH)
    if not path.exists():
        return []

    records = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        logger.error(f"Failed to read analytics log: {e}")

    return records


def get_stats() -> dict:
    """Compute analytics stats for dashboard."""
    records = _read_records()
    now = datetime.now()
    today = now.date()
    week_ago = now - timedelta(days=7)

    total_messages = len(records)
    total_escalations = sum(1 for r in records if r.get("escalated"))
    escalation_rate = round(total_escalations / total_messages * 100, 1) if total_messages else 0

    unique_users = len(set(r.get("user_id", "") for r in records))
    today_records = [
        r for r in records
        if datetime.fromisoformat(r["timestamp"]).date() == today
    ]
    today_messages = len(today_records)
    today_users = len(set(r.get("user_id", "") for r in today_records))

    # Top categories (excluding empty and escalated)
    categories = Counter(
        r.get("category", "Khác") for r in records
        if r.get("category") and not r.get("escalated")
    )
    top_categories = [
        {"category": cat, "count": count}
        for cat, count in categories.most_common(10)
    ]

    # Messages per day (last 7 days)
    daily_counts: dict[str, int] = defaultdict(int)
    for r in records:
        try:
            ts = datetime.fromisoformat(r["timestamp"])
            if ts >= week_ago:
                date_str = ts.date().isoformat()
                daily_counts[date_str] += 1
        except Exception:
            continue

    # Fill in missing days with 0
    daily_series = []
    for i in range(6, -1, -1):
        date = (now - timedelta(days=i)).date().isoformat()
        daily_series.append({"date": date, "count": daily_counts.get(date, 0)})

    # Model usage
    models = Counter(r.get("model_used", "unknown") for r in records)

    return {
        "total_messages": total_messages,
        "total_escalations": total_escalations,
        "escalation_rate": escalation_rate,
        "unique_users": unique_users,
        "today_messages": today_messages,
        "today_users": today_users,
        "top_categories": top_categories,
        "daily_series": daily_series,
        "models": dict(models),
    }


def get_recent_messages(limit: int = 20) -> list[dict]:
    """Get most recent messages."""
    records = _read_records()
    return list(reversed(records[-limit:]))

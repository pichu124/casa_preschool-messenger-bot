"""What a parent asks about in one message, for the school's content and ads: the extraction model tags each message
with TOPICS (prompt in app/ai_engine.py), the dashboard and the "Chủ đề" Sheet tab count them. Not the profile, and
not app/coverage.py (what the bot has told a parent)."""
import unicodedata

TOPICS = (
    "Học phí",
    "Ưu đãi",
    "Chương trình/phương pháp",
    "Tiếng Anh/GV nước ngoài",
    "Giáo viên/tỷ lệ cô trò",
    "Cơ sở vật chất",
    "Ăn uống/thực đơn",
    "An toàn/sức khoẻ/camera",
    "Giờ học/đón trả/trông muộn",
    "Xe đưa đón",
    "Độ tuổi/nhập học/hồ sơ",
    "Học thử/tham quan",
    "Thích nghi/tâm lý bé",
    "So sánh trường khác",
    "Khác",
)
OTHER = "Khác"


def _key(text: str) -> str:
    """Ignoring case and every space; "khỏe" and "tỉ lệ" are "khoẻ" and "tỷ lệ" (both spellings are in use)."""
    key = "".join(unicodedata.normalize("NFC", text).casefold().split())
    return key.replace("ỏe", "oẻ").replace("tỉ", "tỷ")


_BY_KEY = {_key(topic): topic for topic in TOPICS}


def clean_topics(value, escalated: bool = False) -> list[str]:
    """The TOPICS in `value` (the model's "topics"), as written in TOPICS, without repeats, in the model's order;
    anything else is dropped. A message escalated to a consultant has at least OTHER."""
    items = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    keys = [_key(item) for item in items if isinstance(item, str)]
    topics = list(dict.fromkeys(_BY_KEY[key] for key in keys if key in _BY_KEY))
    return topics or ([OTHER] if escalated else [])

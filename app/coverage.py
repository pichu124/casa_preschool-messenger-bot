"""What the bot has told a parent, for the school's "fairly full consultation" (feedback round 4).

The school's six conditions: 1. the child's age and the campus the parent is interested in are known; the bot has
given information on 2. the school and its campuses, 3. the programme and the extracurricular activities, 4. the menu
and nutrition, 5. the free one-week trial, 6. the facilities and classrooms, and invited the parent to book a visit.
Conditions 2-6 are read off the replies the bot sent (tokens included), the same whichever model wrote them.
"""
import re

TOPICS = ("school", "program", "extracurricular", "menu", "trial", "facilities", "visit_invite")

# Vietnamese words below are written in both tone placements models use ("khóa"/"khoá").
_SIGNALS = {
    # A bare list of campus names (Chùa Láng, Mỹ Đình, Kim Mã) is a question, not information about the school,
    # and so is "3 cơ sở" leading up to "which campus?" ("Casa có 3 cơ sở: … Nhà mình gần cơ sở nào ạ?")
    "school": r"huỳnh thúc kháng|hong\s?kong|phạm hùng|\bflc\b|ngõ 294|3 cơ sở(?![^?]*cơ sở nào)",
    "program": r"cambridge|montessori|\blet['’]?s explore\b|understanding the world|phonics|mathematics",
    "extracurricular": (
        r"ngoại kh(?:óa|oá)|dã ngoại|\bscience\b|\bcooking\b|\bart\b|\bmusic\b|robotics|\bsteam\b|năng khiếu"
        r"|tạo hình|thủ công|family day|chuyến (?:đi|trải nghiệm)"
    ),
    "menu": r"thực đơn|dinh dưỡng|bữa (?:ăn|sáng|trưa|phụ|chiều|nhẹ)|nhóm chất|nhà bếp|khu bếp|bếp ăn",
    "trial": r"học thử[^.?!]*(?:1|một) tuần|(?:1|một) tuần học thử|\[QUICK:\s*trial_week\s*\]",
    # "giáo cụ" (Montessori materials) is the programme, not the facilities
    "facilities": (
        r"cơ sở vật chất|m²|\d\s*m2\b|phòng gym|thư viện|sân chơi|điều h(?:òa|oà)|diện tích"
        r"|không gian (?:lớp|học|vận động|đọc)"
    ),
    # A bare "tham quan" is also a field trip ("dã ngoại tham quan nông trại")
    "visit_invite": (
        r"(?:đến|ghé|hẹn|đặt lịch|mời|sắp xếp)[^.?!]{0,20}tham quan|tham quan (?:trường|lớp|cơ sở|trực tiếp)"
        r"|\[QUICK:\s*visit_time\s*\]"
    ),
}
_PATTERNS = {topic: re.compile(_SIGNALS[topic], re.IGNORECASE) for topic in TOPICS}
# A sentence naming a fee tells what the money pays for ("Phí phát triển trường dùng để … cơ sở vật chất")
_FEE_SENTENCE = r"[^.?!]*phí (?:phát triển trường|học liệu)[^.?!]*"
# Text blanked out before a topic's signals are searched: it names the topic without giving information on it
_NOT_INFORMATION = {
    "extracurricular": re.compile(_FEE_SENTENCE, re.IGNORECASE),
    # What the parent is invited to see ("mời Ba/Mẹ tham quan cơ sở vật chất") is the invitation, not facilities
    "facilities": re.compile(_FEE_SENTENCE + r"|tham quan (?:cơ sở vật chất|không gian)", re.IGNORECASE),
}
# The first-message question "which information are you interested in?" names topics without giving them
_TOPICS_QUESTION = re.compile(r"\[QUICK:\s*topics\s*\]")


def topics_in_reply(reply: str) -> list[str]:
    """Topics (in TOPICS order) a reply the bot sent gives information on; `reply` keeps its [QUICK:] tokens."""
    if _TOPICS_QUESTION.search(reply):
        return []
    return [
        topic
        for topic in TOPICS
        if _PATTERNS[topic].search(_NOT_INFORMATION[topic].sub(" ", reply) if topic in _NOT_INFORMATION else reply)
    ]


def fully_consulted(profile: dict) -> bool:
    """The school's six conditions: age and campus known (area or address is not a campus), every topic given."""
    covered = profile.get("topics_covered")
    return bool(
        profile.get("kid_age")
        and profile.get("interested_campus")
        and isinstance(covered, list)
        and set(TOPICS) <= set(covered)
    )

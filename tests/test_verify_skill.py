"""Skill verify-casa-bot (kịch bản model giả, feature map, docstring harness) khớp nút và ice breaker trong
app/messenger.py: đổi chữ ở đó mà quên skill thì test này đỏ."""

import json
import re
from pathlib import Path

from app.followup import TEMPLATES
from app.messenger import ICE_BREAKERS, QUICK_REPLIES, build_quick_replies

SKILL = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "verify-casa-bot"
SCENARIO = json.loads((SKILL / "harness" / "scenario.default.json").read_text(encoding="utf-8"))
RULES = [r for r in SCENARIO["rules"] if r["kind"] in ("chat", "extract")]
TOKEN = re.compile(r"[A-Z_]+")
FILES = sorted(p for p in SKILL.rglob("*") if p.suffix in (".md", ".py", ".json") and "__pycache__" not in p.parts)
LINES = [(p.relative_to(SKILL), n, line) for p in FILES for n, line in enumerate(p.read_text("utf-8").splitlines(), 1)]


def where(path, n):
    return f"{path}:{n}"


def test_skill_files_are_found():
    names = {p.name for p in FILES}
    assert {"SKILL.md", "webhook-messaging.md", "followup.md", "send_event.py", "scenario.default.json"} <= names


def test_every_quick_reply_payload_in_the_skill_is_a_real_button():
    for path, n, line in LINES:
        for key, i in re.findall(r"QR:(\w+):(\d+)", line):
            assert key in QUICK_REPLIES and int(i) < len(QUICK_REPLIES[key]), where(path, n)


def test_button_text_sent_with_a_quick_reply_is_the_button_title():
    found = 0
    for path, n, line in LINES:
        for key, i, text in re.findall(r'QR:(\w+):(\d+)\s+\[?--text\s+"([^"]*)"', line):
            found += 1
            assert text == QUICK_REPLIES[key][int(i)][0], where(path, n)
    assert found >= 4


def test_full_quick_reply_lists_match_the_buttons_of_their_key():
    for path, n, line in LINES:
        for listed in re.findall(r"QUICK=\[([^\]]*)\]", line):
            payloads = re.findall(r'"(QR:(\w+):\d+)"', listed)
            if not payloads or "..." in listed:
                continue
            key = payloads[0][1]
            expected = [q["payload"] for q in build_quick_replies(key)]
            assert [p for p, _ in payloads] == expected, where(path, n)


def test_ice_breaker_questions_quoted_in_the_skill_are_the_registered_ones():
    found = 0
    for path, n, line in LINES:
        ice_breakers = set(re.findall(r"\bIB_\d+\b", line))
        assert ice_breakers <= set(ICE_BREAKERS), where(path, n)
        questions = re.findall(r'"([^"]+\?)"', line)
        if len(ice_breakers) == 1 and questions:
            found += 1
            assert questions == [ICE_BREAKERS[ice_breakers.pop()]], where(path, n)
    assert found >= 2


def test_scenario_rules_for_parent_text_match_a_button_meaning_or_ice_breaker():
    said = [meaning for buttons in QUICK_REPLIES.values() for _, meaning in buttons] + list(ICE_BREAKERS.values())
    worded = [r for r in RULES if not TOKEN.fullmatch(r["contains"])]
    assert worded
    for rule in worded:
        assert any(rule["contains"] in s for s in said), rule


def test_scenario_extracts_the_age_button_title_as_kid_age():
    ages = [r for r in RULES if r["kind"] == "extract" and "kid_age" in r["reply"]]
    assert ages
    for rule in ages:
        (title,) = [t for t, meaning in QUICK_REPLIES["age"] if rule["contains"] in meaning]
        assert rule["reply"]["kid_age"] == title


def test_rules_named_in_the_skill_exist_in_the_default_scenario():
    contains = {r["contains"] for r in RULES}
    for path, n, line in LINES:
        for name in re.findall(r"rule='([^']*)'", line):
            assert name in contains, where(path, n)


def test_kid_age_expected_by_the_skill_is_what_the_scenario_extracts():
    extracted = {r["reply"]["kid_age"] for r in RULES if "kid_age" in r["reply"]}
    found = 0
    for path, n, line in LINES:
        for value in re.findall(r'--fields kid_age`\s*→\s*`"([^"]*)"`', line):
            found += 1
            assert value in extracted, where(path, n)
    assert found >= 1


def test_skill_md_scenario_table_lists_rules_of_the_default_scenario():
    text = (SKILL / "SKILL.md").read_text("utf-8")
    table = text.split("| Phụ huynh viết chứa |", 1)[1].split("\n\n", 1)[0]
    contains = {r["contains"] for r in RULES}
    cells = [row.split("|")[1] for row in table.splitlines()[2:]]
    names = [name for cell in cells for name in re.findall(r"`([^`]*)`", cell)]
    assert len(names) >= 10
    for name in names:
        assert name in contains, name



def test_followup_text_expected_by_the_skill_starts_every_template():
    text = (SKILL / "features" / "followup.md").read_text("utf-8")
    starts = re.findall(r'TEXT "([^"…]*)…"', text)
    assert starts
    for start in starts:
        assert all(t.startswith(start.rstrip()) for t in TEMPLATES.values()), start

"""Skill verify-casa-bot (kịch bản model giả, feature map, docstring harness) khớp nút và ice breaker trong
app/messenger.py: đổi chữ ở đó mà quên skill thì test này đỏ. Harness không cho app chạy với biến proxy hay key
Gemini thật; fake trả lời SDK google-genai thật theo kịch bản."""

import asyncio
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.followup import TEMPLATES
from app.messenger import ICE_BREAKERS, QUICK_REPLIES, build_quick_replies

SKILL = Path(__file__).resolve().parent.parent / ".claude" / "skills" / "verify-casa-bot"
SCENARIO = json.loads((SKILL / "harness" / "scenario.default.json").read_text(encoding="utf-8"))
RULES = [r for r in SCENARIO["rules"] if r["kind"] in ("chat", "extract")]
TOKEN = re.compile(r"[A-Z_]+")
FILES = sorted(p for p in SKILL.rglob("*") if p.suffix in (".md", ".py", ".json") and "__pycache__" not in p.parts)
LINES = [(p.relative_to(SKILL), n, line) for p in FILES for n, line in enumerate(p.read_text("utf-8").splitlines(), 1)]

sys.path.insert(0, str(SKILL / "harness"))  # ctl.py imports _common from its own directory
_spec = importlib.util.spec_from_file_location("casa_verify_ctl", SKILL / "harness" / "ctl.py")
ctl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ctl)


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


CTL_STATE = {
    "run_id": "r1",
    "run_dir": "/nonexistent/run",
    "fake_port": 1,
    "app_port": 2,
    "netlog": "/nonexistent/netlog.txt",
    "scenario": "/nonexistent/scenario.json",
    "verify_token": "fake-verify-r1",
    "app_secret": "fake-app-secret-r1",
    "secret": "fake-admin-r1",
    "app_url": "http://127.0.0.1:2",
}


def run_launcher(tmp_path, **env):
    base = {
        "PATH": "/usr/bin:/bin",
        "CASA_VERIFY_FAKE_PORT": "1",
        "CASA_VERIFY_APP_PORT": "2",
        "CASA_VERIFY_NETLOG": str(tmp_path / "netlog.txt"),
        "CASA_VERIFY_SCENARIO": str(tmp_path / "scenario.json"),
    }
    launcher = SKILL / "harness" / "launcher.py"
    return subprocess.run(
        [sys.executable, str(launcher)], env=base | env, cwd=tmp_path, capture_output=True, text=True, timeout=30
    )


@pytest.mark.parametrize("name", ["HTTPS_PROXY", "http_proxy", "ALL_PROXY", "GLOBAL_AGENT_HTTPS_PROXY"])
def test_launcher_refuses_to_start_with_a_proxy_variable(tmp_path, name):
    result = run_launcher(tmp_path, **{name: "http://127.0.0.1:9", "GITHUB_TOKEN": "fake-token"})

    assert result.returncode == 1
    assert f"launcher: refusing to start: {name} set" in result.stderr
    assert "REFUSED START" in (tmp_path / "netlog.txt").read_text()


def test_launcher_does_not_count_no_proxy_as_a_proxy(tmp_path):
    result = run_launcher(tmp_path, NO_PROXY="localhost", no_proxy="localhost")

    assert result.returncode == 1
    assert "refusing to start: GITHUB_TOKEN must be a fake-" in result.stderr


@pytest.mark.parametrize("name", ["HTTPS_PROXY", "https_proxy", "ALL_PROXY"])
def test_ctl_up_refuses_a_proxy_in_env_overrides(name):
    with pytest.raises(SystemExit, match=f"--env {name} is not allowed"):
        ctl.app_env(CTL_STATE, {name: "http://127.0.0.1:9"})


def test_ctl_up_accepts_no_proxy_in_env_overrides():
    assert ctl.app_env(CTL_STATE, {"NO_PROXY": "localhost"})["NO_PROXY"] == "localhost"


def test_ctl_up_accepts_a_fake_gemini_key():
    env = ctl.app_env(CTL_STATE, {"GEMINI_API_KEY": "fake", "AI_MODEL_ORDER": "gemini"})

    assert (env["GEMINI_API_KEY"], env["AI_MODEL_ORDER"]) == ("fake", "gemini")


def test_ctl_up_refuses_a_real_looking_gemini_key():
    with pytest.raises(SystemExit, match="--env GEMINI_API_KEY must start with fake"):
        ctl.app_env(CTL_STATE, {"GEMINI_API_KEY": "AIzaSyNotFake"})


def test_launcher_refuses_a_real_looking_gemini_key(tmp_path):
    result = run_launcher(tmp_path, GITHUB_TOKEN="fake-token", GEMINI_API_KEY="AIzaSyNotFake")

    assert result.returncode == 1
    assert "refusing to start: GEMINI_API_KEY must be a fake" in result.stderr


_fake_spec = importlib.util.spec_from_file_location("casa_verify_fake", SKILL / "harness" / "fake_server.py")
fake = importlib.util.module_from_spec(_fake_spec)
_fake_spec.loader.exec_module(fake)


@pytest.fixture
def gemini_via_fake(monkeypatch):
    """Engine thật + SDK google-genai thật; transport httpx trả lời bằng fake_server.route (như launcher viết lại)."""
    from app import ai_engine
    from app.config import settings

    monkeypatch.setattr(fake, "args", SimpleNamespace(scenario=str(SKILL / "harness" / "scenario.default.json")))
    records = []

    async def transport(self, request):
        body = json.loads(await request.aread())
        code, out, extra = fake.route(request.method, request.url.host, request.url.path, dict(request.headers), body)
        records.append({"host": request.url.host, "path": request.url.path, "body": body, **extra})
        return httpx.Response(code, json=out, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", transport)
    monkeypatch.setattr(settings, "AI_MODEL_ORDER", ["gemini"])
    monkeypatch.setattr(settings, "GEMINI_MODEL", "verify-gem-x")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake")
    monkeypatch.setitem(ai_engine.API_KEY_MAP, "gemini", "fake")
    monkeypatch.setattr(ai_engine, "ai_engine_instance", ai_engine.ai_engine_instance)
    return ai_engine.AIEngine("Q: trường ở đâu\nA: Hà Nội"), records


def test_fake_gemini_answers_a_parent_message_by_the_scenario(gemini_via_fake):
    engine, records = gemini_via_fake

    response = asyncio.run(engine.get_response("ASK_AGE Cho em hỏi về trường ạ"))

    assert response.model_used == "gemini"
    assert response.text == next(r["reply"] for r in RULES if r["contains"] == "ASK_AGE")
    (rec,) = records
    assert rec["host"] == "generativelanguage.googleapis.com"
    assert rec["path"] == "/v1beta/models/verify-gem-x:generateContent"
    assert (rec["kind"], rec["rule"], rec["model"]) == ("chat", "ASK_AGE", "verify-gem-x")
    assert rec["body"]["systemInstruction"]["parts"][0]["text"].startswith("Em là tư vấn viên tuyển sinh")


def test_fake_gemini_extracts_by_the_scenario(gemini_via_fake):
    engine, records = gemini_via_fake

    assert asyncio.run(engine.extract_customer_info("PHONE_A số em đây ạ")) == {"phone": "0912345678"}
    assert (records[0]["kind"], records[0]["rule"]) == ("extract", "PHONE_A")


def test_outbox_cuts_the_gemini_system_instruction():
    body = {"systemInstruction": {"parts": [{"text": "x" * 5000}]}, "contents": [{"role": "user", "parts": [{"text": "hi"}]}]}

    cut = fake._for_outbox(body)

    assert cut["systemInstruction"]["parts"][0]["text"] == "x" * 200 + "…(5000 chars)"
    assert cut["contents"] == body["contents"]

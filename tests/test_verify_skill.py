"""Skill verify-casa-bot (kịch bản model giả, feature map, docstring harness) khớp nút và ice breaker trong
app/messenger.py: đổi chữ ở đó mà quên skill thì test này đỏ. Harness không cho app chạy với biến proxy hay key
Gemini thật; fake trả lời SDK google-genai thật theo kịch bản."""

import asyncio
import importlib.util
import json
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.coverage import TOPICS, topics_in_reply
from app.followup import TEMPLATES, due_followups
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


def chat_reply(contains):
    return next(r["reply"] for r in RULES if r["kind"] == "chat" and r["contains"] == contains)


def test_tour_replies_of_the_scenario_together_give_every_topic_of_a_full_consultation():
    tour = [chat_reply(name) for name in ("TOUR_CAMPUS", "TOUR_MENU", "TOUR_EXTRA")]

    assert {topic for reply in tour for topic in topics_in_reply(reply)} == set(TOPICS)
    # …0049 in features/followup.md stops before TOUR_EXTRA, so only TOUR_EXTRA may give the extracurricular topic
    path_0049 = [chat_reply("Bé nhà em 2-3 tuổi"), chat_reply("TOUR_CAMPUS"), chat_reply("TOUR_MENU")]
    assert "extracurricular" not in {topic for reply in path_0049 for topic in topics_in_reply(reply)}


@pytest.mark.parametrize("name", ["TOUR_CAMPUS", "TOUR_MENU", "TOUR_EXTRA"])
def test_tour_replies_carry_no_token_but_quick_replies_of_real_buttons(name):
    reply = chat_reply(name)

    rest = re.sub(r"\[QUICK:\w+\]", "", reply)
    assert "[" not in rest and "]" not in rest, rest
    for key in re.findall(r"\[QUICK:(\w+)\]", reply):
        assert QUICK_REPLIES.get(key), key


def test_scenario_extracts_a_campus_button_title_as_interested_campus():
    campuses = [r["reply"]["interested_campus"] for r in RULES if r["kind"] == "extract" and "interested_campus" in r["reply"]]
    assert campuses
    assert set(campuses) <= {title for title, _ in QUICK_REPLIES["campus"]}


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


# Đồng hồ của đoạn script dừng ở tin cuối của phụ huynh (tham số đầu tiên của script).
FROZEN_NOW = """import datetime as _d, sys as _s
_at = _d.datetime.fromisoformat(_s.argv.pop(1))
class _Frozen(_d.datetime):
    @classmethod
    def now(cls, tz=None):
        return _at.astimezone(tz)
_d.datetime = _Frozen
"""
VN_TZ = timezone(timedelta(hours=7))
# Mỗi 30 phút trong ngày theo giờ VN, cộng các biên của quy tắc latest_send
PARENT_TIMES_VN = sorted({(h, m) for h in range(24) for m in (0, 30)} | {(9, 16), (10, 59), (11, 29), (21, 59)})


@pytest.mark.parametrize(("hour", "minute"), PARENT_TIMES_VN, ids=[f"{h:02}:{m:02}" for h, m in PARENT_TIMES_VN])
def test_followup_scenario_times_of_the_skill_fall_before_in_and_after_the_slot(tmp_path, hour, minute):
    """Đoạn script trong features/followup.md tạo now_utc trước slot, trong slot và sau latest_send của app/followup.py."""
    text = (SKILL / "features" / "followup.md").read_text("utf-8")
    [script] = re.findall(r"python3 - <slug> <<'EOF'\n(.*?)\n *EOF\n", text, re.S)
    harness = tmp_path / ".claude" / "skills" / "verify-casa-bot" / "harness"
    harness.mkdir(parents=True)
    (harness / "scenario.default.json").write_text(json.dumps(SCENARIO), "utf-8")
    (tmp_path / "artifacts" / "verify" / "s").mkdir(parents=True)
    parent_at = datetime(2026, 10, 20, hour, minute, tzinfo=VN_TZ).astimezone(timezone.utc)

    out = subprocess.run(
        [sys.executable, "-I", "-", parent_at.isoformat(), "s"],
        input=FROZEN_NOW + textwrap.dedent(script),
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert out.returncode == 0, out.stderr
    history = [
        {"role": "user", "content": "Xin chào", "timestamp": parent_at.replace(tzinfo=None).isoformat()},
        {"role": "assistant", "content": "Dạ Casa chào Ba/Mẹ ạ", "timestamp": parent_at.replace(tzinfo=None).isoformat()},
    ]
    customers = {"9000000000000041": {"conversation_history": history}}
    for name, due in (("before", []), ("in", [("9000000000000041", "ask_age")]), ("after", [])):
        scenario = json.loads((tmp_path / "artifacts" / "verify" / "s" / f"scenario-{name}.json").read_text("utf-8"))
        assert scenario["rules"] == SCENARIO["rules"]
        assert due_followups(customers, datetime.fromisoformat(scenario["now_utc"])) == due, name


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


def test_fake_apps_script_lists_the_school_drive_tree_and_every_file_is_classified(monkeypatch):
    from app import media

    monkeypatch.setattr(fake, "args", SimpleNamespace(scenario=str(SKILL / "harness" / "scenario.default.json"), port=1))

    code, out, _ = fake.route("POST", "script.google.com", "/macros/s/FAKE/exec", {}, {"type": "media", "token": "t"})

    assert (code, out["ok"], len(out["files"])) == (200, True, 30)
    kinds = [media.classify(f["path"], f["name"])["kind"] for f in out["files"]]
    assert sorted(set(kinds)) == ["facilities", "fee", "menu", "timetable"]


def test_fake_drive_redirects_like_drive_then_serves_an_image(monkeypatch):
    from io import BytesIO

    from PIL import Image

    monkeypatch.setattr(fake, "args", SimpleNamespace(scenario=str(SKILL / "harness" / "scenario.default.json"), port=1))

    code, _, extra = fake.route("GET", "drive.google.com", "/uc", {}, None, {"export": "download", "id": "qt-menu"})
    assert (code, extra["location"]) == (303, "http://127.0.0.1:1/drive.usercontent.google.com/download?id=qt-menu&export=download")
    code, data, _ = fake.route("GET", "drive.usercontent.google.com", "/download", {}, None, {"id": "qt-menu"})
    assert code == 200
    with Image.open(BytesIO(data)) as img:
        assert (img.format, img.size) == ("PNG", (64, 48))


def test_fake_graph_refuses_only_images_when_graph_image_fails(monkeypatch, tmp_path):
    scenario = {**SCENARIO, "fail": {**SCENARIO["fail"], "graph_image": True}}
    (tmp_path / "scenario.json").write_text(json.dumps(scenario), "utf-8")
    monkeypatch.setattr(fake, "args", SimpleNamespace(scenario=str(tmp_path / "scenario.json"), port=1))
    image = {"recipient": {"id": "1"}, "message": {"attachment": {"type": "image", "payload": {"url": "u"}}}}
    text = {"recipient": {"id": "1"}, "message": {"text": "Dạ"}}

    code, out, _ = fake.route("POST", "graph.facebook.com", "/v21.0/me/messages", {}, image)
    assert (code, out["error"]["code"]) == (400, 100)
    assert fake.route("POST", "graph.facebook.com", "/v21.0/me/messages", {}, text)[0] == 200

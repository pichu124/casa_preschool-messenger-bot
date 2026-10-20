"""Tin nhắc lại phụ huynh còn dở cuộc tư vấn, trong cửa sổ 24 giờ của Messenger (mặc định TẮT).

due_followups là hàm thuần: bảng ca biên dưới đây gọi thẳng với giờ cố định. run_followups và /followup/run
dùng Messenger giả (patch trên app.followup) và giờ cố định (followup._now_utc). Workflow GitHub Actions được
đọc từ YAML, bước curl chạy thật bằng bash với curl giả.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

import app.main as main
from app import customer_memory, followup
from app.config import settings
from app.escalation import (
    ESCALATION_MESSAGE_ASK_PHONE,
    ESCALATION_MESSAGE_HAS_PHONE,
    ESCALATION_MESSAGE_PHONE_DECLINED,
)

client = TestClient(main.app)

VN = timezone(timedelta(hours=7))
H = timedelta(hours=1)
M = timedelta(minutes=1)
NOW = datetime(2026, 10, 20, 10, 0, tzinfo=VN).astimezone(timezone.utc)
CID = "9000000000000201"
WEBHOOK_SECRET = "tg-secret_followup"
FB_NAME = "Lan Thử"
KID_NAME = "Bin"
PHONE = "0900000201"
PARENT_TEXT = "Trường mình có cơ sở nào gần Cầu Giấy không ạ?"
BOT_TEXT = "Dạ Casa có cơ sở Chùa Láng, Mỹ Đình và Kim Mã ạ. Bé nhà mình năm nay mấy tuổi ạ?"
ASK_PHONE_WORDS = ("SĐT", "Zalo", "số điện thoại")


def server_time(dt: datetime) -> str:
    """Timestamp như append_to_history ghi trên Render: datetime.now() của máy chủ UTC, không có múi giờ."""
    return dt.astimezone(timezone.utc).replace(tzinfo=None).isoformat()


def vn(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 20, hour, minute, tzinfo=VN).astimezone(timezone.utc)


def profile(silence=5 * H, now=NOW, last="assistant", bot_text=BOT_TEXT, **fields) -> dict:
    """Hồ sơ có tin cuối của phụ huynh cách `now` một khoảng `silence`; tin cuối của history là của `last`."""
    parent_at = now - silence
    parent = {"role": "user", "content": PARENT_TEXT, "timestamp": server_time(parent_at)}
    if last == "assistant":
        bot_at = parent_at + timedelta(seconds=5)
        history = [parent, {"role": "assistant", "content": bot_text, "timestamp": server_time(bot_at)}]
    else:
        history = [{"role": "assistant", "content": bot_text, "timestamp": server_time(parent_at - H)}, parent]
    return {"parent_name": FB_NAME, "message_count": 2, "conversation_history": history, **fields}


DUE_CASES = [
    ("2h59 sau tin phụ huynh", profile(silence=3 * H - M), NOW, None),
    ("3h00 sau tin phụ huynh", profile(silence=3 * H), NOW, "ask_age"),
    ("23h00 sau tin phụ huynh", profile(silence=23 * H), NOW, "ask_age"),
    ("23h01 sau tin phụ huynh", profile(silence=23 * H + M), NOW, None),
    ("7h59 giờ VN", profile(now=vn(7, 59)), vn(7, 59), None),
    ("8h00 giờ VN", profile(now=vn(8)), vn(8), "ask_age"),
    ("20h59 giờ VN", profile(now=vn(20, 59)), vn(20, 59), "ask_age"),
    ("21h00 giờ VN", profile(now=vn(21)), vn(21), None),
    ("đã nhắc sau tin cuối", profile(followup_sent_at=(NOW - 4 * H).isoformat()), NOW, None),
    ("nhắc đúng lúc tin cuối", profile(followup_sent_at=(NOW - 5 * H).isoformat()), NOW, None),
    ("nhắc trước tin cuối mới hơn", profile(followup_sent_at=(NOW - 30 * H).isoformat()), NOW, "ask_age"),
    ("tin cuối: chuyển tư vấn viên, xin SĐT", profile(bot_text=ESCALATION_MESSAGE_ASK_PHONE), NOW, None),
    ("tin cuối: chuyển tư vấn viên, có SĐT", profile(bot_text=ESCALATION_MESSAGE_HAS_PHONE), NOW, None),
    ("tin cuối: chuyển tư vấn viên, từ chối SĐT", profile(bot_text=ESCALATION_MESSAGE_PHONE_DECLINED), NOW, None),
    ("tin cuối là của phụ huynh", profile(last="user"), NOW, None),
    ("có phone", profile(kid_age="3 tuổi", phone=PHONE), NOW, None),
    ("có visit_request", profile(kid_age="3 tuổi", visit_request="tham quan sáng thứ 7"), NOW, None),
    ("chưa biết tuổi bé", profile(interested_campus="Mỹ Đình"), NOW, "ask_age"),
    ("biết tuổi, chưa có SĐT", profile(kid_age="3 tuổi"), NOW, "ask_phone"),
    ("phone_declined", profile(kid_age="3 tuổi", phone_declined=True), NOW, "invite_visit"),
    ("phone_declined, chưa biết tuổi", profile(phone_declined=True), NOW, "invite_visit"),
    ("chỉ có referral, không history", {"lead_source": "ads", "ad_title": "Học thử 1 tuần"}, NOW, None),
]


@pytest.mark.parametrize(("customer", "now", "template_key"), [c[1:] for c in DUE_CASES], ids=[c[0] for c in DUE_CASES])
def test_due_followups_edge_cases(customer, now, template_key):
    expected = [(CID, template_key)] if template_key else []

    assert followup.due_followups({CID: customer}, now) == expected


def test_history_timestamp_without_timezone_is_read_as_utc():
    """2h59 trước theo UTC; đọc nhầm là giờ VN thì thành 9h59 trước và bị nhắc."""
    customer = profile(silence=3 * H - M)
    assert "+" not in customer["conversation_history"][0]["timestamp"]

    assert followup.due_followups({CID: customer}, NOW) == []


def test_unreadable_timestamp_is_not_due_and_does_not_break_others():
    broken = profile()
    broken["conversation_history"][0]["timestamp"] = "không phải ngày"
    del broken["conversation_history"][1]["timestamp"]
    other = "9000000000000202"

    assert followup.due_followups({CID: broken, other: profile()}, NOW) == [(other, "ask_age")]


def test_phone_declined_template_invites_visit_without_asking_for_phone():
    text = followup.TEMPLATES["invite_visit"]

    assert not [word for word in ASK_PHONE_WORDS if word in text]
    assert "học thử" in text and "miễn phí" in text and "tham quan" in text


def test_templates_ask_for_the_missing_step():
    assert "tuổi" in followup.TEMPLATES["ask_age"]
    assert "SĐT" in followup.TEMPLATES["ask_phone"]
    for text in followup.TEMPLATES.values():
        assert "Ba/Mẹ" in text and "em" in text.split()


# --- run_followups ---


class Outbox:
    """Messenger giả: ghi tin gửi đi; khách trong `failing` bị Graph từ chối (ngoài cửa sổ, đã chặn trang)."""

    def __init__(self):
        self.sent = []
        self.failing = set()

    async def send_message(self, recipient_id, text, quick_replies=None):
        await asyncio.sleep(0)
        if recipient_id in self.failing:
            raise Exception("Messenger API error: 400")
        self.sent.append((recipient_id, text))


@pytest.fixture
def outbox(monkeypatch):
    box = Outbox()
    monkeypatch.setattr(followup, "send_message", box.send_message)
    monkeypatch.setattr(followup, "_now_utc", lambda: NOW)
    return box


@pytest.fixture
def synced(monkeypatch):
    calls = []

    async def sync_to_github():
        calls.append(1)
        return True

    monkeypatch.setattr(customer_memory, "sync_to_github", sync_to_github)
    return calls


ASK_AGE_ID, INVITE_ID, HAS_PHONE_ID = "9000000000000211", "9000000000000212", "9000000000000213"


def seed_customers():
    customer_memory._customers.update(
        {
            ASK_AGE_ID: profile(kid_name=KID_NAME),
            INVITE_ID: profile(kid_age="3 tuổi", phone_declined=True),
            HAS_PHONE_ID: profile(kid_age="4 tuổi", phone=PHONE),
        }
    )


def test_disabled_sends_nothing_and_only_counts(outbox):
    """conftest đặt FOLLOWUP_ENABLED=False và cấm sync_to_github."""
    seed_customers()
    before = json.loads(json.dumps(customer_memory._customers))

    result = asyncio.run(followup.run_followups(dry_run=False))

    assert (result["due"], result["sent"], result["enabled"]) == (2, 0, False)
    assert outbox.sent == []
    assert customer_memory._customers == before


def test_conftest_keeps_followup_disabled():
    assert settings.FOLLOWUP_ENABLED is False


def test_enabled_sends_once_to_due_customers_and_records_it(monkeypatch, outbox, synced):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()

    result = asyncio.run(followup.run_followups(dry_run=False))

    assert (result["due"], result["sent"], result["enabled"]) == (2, 2, True)
    assert outbox.sent == [
        (ASK_AGE_ID, followup.TEMPLATES["ask_age"]),
        (INVITE_ID, followup.TEMPLATES["invite_visit"]),
    ]
    for customer_id, text in outbox.sent:
        saved = customer_memory.get_profile(customer_id)
        assert saved["followup_sent_at"] == NOW.isoformat()
        assert saved["message_count"] == 2
        assert "last_seen" not in saved
        assert saved["conversation_history"][-1]["role"] == "assistant"
        assert saved["conversation_history"][-1]["content"] == text
        assert len(saved["conversation_history"]) == 3
    assert "followup_sent_at" not in customer_memory.get_profile(HAS_PHONE_ID)
    assert synced == [1]

    again = asyncio.run(followup.run_followups(dry_run=False))

    assert (again["due"], again["sent"]) == (0, 0)
    assert len(outbox.sent) == 2
    assert synced == [1]


def test_send_error_skips_that_customer_only(monkeypatch, outbox, synced, caplog):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()
    outbox.failing.add(ASK_AGE_ID)

    with caplog.at_level(logging.WARNING, logger=followup.logger.name):
        result = asyncio.run(followup.run_followups(dry_run=False))

    assert (result["due"], result["sent"]) == (2, 1)
    assert outbox.sent == [(INVITE_ID, followup.TEMPLATES["invite_visit"])]
    failed = customer_memory.get_profile(ASK_AGE_ID)
    assert "followup_sent_at" not in failed and len(failed["conversation_history"]) == 2
    assert customer_memory.get_profile(INVITE_ID)["followup_sent_at"] == NOW.isoformat()
    assert synced == [1]
    assert [r for r in caplog.records if ASK_AGE_ID[-4:] in r.getMessage()], "không log khách gửi lỗi"


def test_dry_run_sends_nothing_even_when_enabled(monkeypatch, outbox):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()

    result = asyncio.run(followup.run_followups(dry_run=True))

    assert (result["due"], result["sent"], result["enabled"]) == (2, 0, True)
    assert outbox.sent == []
    assert "followup_sent_at" not in customer_memory.get_profile(ASK_AGE_ID)


def test_overlapping_runs_do_not_send_twice(monkeypatch, outbox, synced):
    """curl --retry gửi lại khi lần đầu quá giờ mà máy chủ vẫn đang gửi: hai lần chạy chồng nhau."""
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()

    async def two_runs():
        return await asyncio.gather(followup.run_followups(dry_run=False), followup.run_followups(dry_run=False))

    first, second = asyncio.run(two_runs())

    assert sorted(recipient for recipient, _ in outbox.sent) == [ASK_AGE_ID, INVITE_ID]
    assert first["sent"] + second["sent"] == 2
    assert synced == [1]


def test_no_due_customer_does_not_sync(monkeypatch, outbox):
    """conftest cấm sync_to_github: không có gì thay đổi thì không đẩy customers.json."""
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    customer_memory._customers[HAS_PHONE_ID] = profile(phone=PHONE)

    result = asyncio.run(followup.run_followups(dry_run=False))

    assert (result["due"], result["sent"]) == (0, 0)


# --- /followup/run ---


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", WEBHOOK_SECRET)


def run_endpoint(**params):
    return client.post("/followup/run", params={"secret": WEBHOOK_SECRET, **params})


def test_endpoint_without_secret_is_forbidden(admin, outbox):
    seed_customers()

    assert client.post("/followup/run").status_code == 403
    assert client.post("/followup/run", params={"secret": "sai"}).status_code == 403
    assert outbox.sent == []


def test_endpoint_returns_counts_only(monkeypatch, admin, outbox, synced):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()

    resp = run_endpoint()

    assert resp.status_code == 200
    assert resp.json() == {"due": 2, "sent": 2, "enabled": True}


def test_endpoint_dry_run_sends_nothing(monkeypatch, admin, outbox):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", True)
    seed_customers()

    resp = run_endpoint(dry_run=1)

    assert resp.json() == {"due": 2, "sent": 0, "enabled": True}
    assert outbox.sent == []


@pytest.mark.parametrize("enabled", [False, True], ids=["tắt", "bật"])
def test_endpoint_verbose_and_logs_carry_no_personal_data(monkeypatch, admin, outbox, synced, caplog, enabled):
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", enabled)
    seed_customers()

    with caplog.at_level(logging.DEBUG):
        resp = run_endpoint(verbose=1)

    body = resp.json()
    assert body["due"] == 2 and body["enabled"] is enabled
    assert body["followups"] == [
        {"template_key": "ask_age", "customer_id": ASK_AGE_ID[-4:]},
        {"template_key": "invite_visit", "customer_id": INVITE_ID[-4:]},
    ]
    private = (FB_NAME, KID_NAME, PHONE, PARENT_TEXT, BOT_TEXT, ASK_AGE_ID, INVITE_ID, *followup.TEMPLATES.values())
    assert [p for p in private if p in resp.text] == []
    logs = [r.getMessage() for r in caplog.records]
    assert [m for m in logs if any(p in m for p in (FB_NAME, KID_NAME, PHONE, PARENT_TEXT, BOT_TEXT))] == []
    assert [m for m in logs if any(t in m for t in followup.TEMPLATES.values())] == []


# --- .github/workflows/followup.yml ---

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "followup.yml"
SECRETS = {"BOT_BASE_URL": "https://casa.example", "BOT_ADMIN_SECRET": "s3cret-actions"}


def load_workflow():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # YAML 1.1 đọc khoá `on` thành True
    return workflow, workflow.get("on", workflow.get(True))


def test_workflow_runs_hourly_or_by_hand_never_on_push_or_pr():
    _, triggers = load_workflow()

    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["schedule"] == [{"cron": "17 * * * *"}]


def test_workflow_jobs_run_only_when_repo_variable_enabled():
    workflow, _ = load_workflow()

    assert workflow["jobs"]
    for job in workflow["jobs"].values():
        assert job["if"] == "vars.FOLLOWUP_ENABLED == 'true'"


def with_secrets(value: str) -> str:
    return re.sub(r"\$\{\{\s*secrets\.(\w+)\s*\}\}", lambda m: SECRETS[m.group(1)], value)


@pytest.mark.parametrize(("http_code", "ok"), [("200", True), ("403", False), ("500", False), ("000", False)])
def test_workflow_step_fails_unless_200_without_printing_body(tmp_path, http_code, ok):
    """Repo public nên log Actions công khai: curl bỏ body (-o /dev/null), chỉ in mã HTTP."""
    workflow, _ = load_workflow()
    steps = [step for job in workflow["jobs"].values() for step in job["steps"] if "run" in step]
    assert len(steps) == 1
    step = steps[0]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "curl-args"
    fake_curl = bin_dir / "curl"
    fake_curl.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > "{args_file}"\nprintf "{http_code}"\n')
    fake_curl.chmod(0o755)
    env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    env.update({name: with_secrets(str(value)) for name, value in step.get("env", {}).items()})

    out = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", with_secrets(step["run"])],
        env=env,
        capture_output=True,
        text=True,
    )

    assert (out.returncode == 0) is ok
    args = args_file.read_text().splitlines()
    pairs = list(zip(args, args[1:]))
    for pair in [("-o", "/dev/null"), ("-w", "%{http_code}"), ("-X", "POST"), ("--max-time", "120"), ("--retry", "2")]:
        assert pair in pairs
    assert args[-1] == "https://casa.example/followup/run?secret=s3cret-actions"
    assert SECRETS["BOT_ADMIN_SECRET"] not in out.stdout + out.stderr

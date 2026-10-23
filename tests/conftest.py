"""Cô lập mọi test khỏi data/ thật và mạng thật (GitHub main của repo public, Facebook, Telegram, AI).

Môi trường có thể có GITHUB_TOKEN thật, và nhiều giá trị bị chốt lúc import app.main,
nên fixture autouse dưới đây vá lại từng test. Test nào cần một lời gọi ra ngoài thì tự
monkeypatch bằng fake ghi lại lời gọi; tên được import trong app.main thì patch trên app.main.
"""

import asyncio
import base64
import hashlib
import json
import os

import httpx
import pytest

# app.main nạp Q&A lúc import, và có GITHUB_TOKEN thì kéo từ GitHub thật; load_dotenv() không đè biến đã có.
os.environ["GITHUB_TOKEN"] = ""

import app.main as main
from app import analytics, customer_memory, escalation, github_sync
from app.config import settings

# isolate() thay hàm này bằng stub cấm gọi; fixture github_main dùng lại bản thật trước GitHub giả.
REAL_PUSH_QA_TO_GITHUB = github_sync.push_qa_to_github


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    for name in (
        "GITHUB_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "FB_PAGE_ACCESS_TOKEN",
        "LEADS_SHEET_WEBHOOK_URL",
        "LEADS_SHEET_TOKEN",
    ):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(settings, "FOLLOWUP_ENABLED", False)
    monkeypatch.setattr(settings, "AI_MODEL_ORDER", [])
    monkeypatch.setattr(settings, "ANALYTICS_LOG_PATH", str(tmp_path / "analytics.jsonl"))

    # Code app nuốt Exception ở nhiều chỗ (vd update_profile), nên ngoài raise còn ghi lại
    # để fail ở teardown: chạm vào đây là lọt lưới cô lập.
    forbidden_calls = []

    def forbid(target):
        def stub(*args, **kwargs):
            forbidden_calls.append(target)
            raise AssertionError(f"test không được gọi {target}")

        return stub

    monkeypatch.setattr(github_sync, "push_qa_to_github", forbid("github_sync.push_qa_to_github"))
    monkeypatch.setattr(customer_memory, "sync_to_github", forbid("customer_memory.sync_to_github"))
    # Chặn mạng thật qua httpx; TestClient dùng transport riêng nên không bị ảnh hưởng.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbid("mạng thật qua httpx"))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbid("mạng thật qua httpx"))

    monkeypatch.setattr(main.qa_db, "path", str(tmp_path / "qa_database.json"))
    monkeypatch.setattr(main.qa_db, "qa_pairs", list(main.qa_db.qa_pairs))
    # Như sau một lần kéo main thành công: cặp admin dạy được đẩy lên (tới push_qa_to_github giả của test).
    monkeypatch.setattr(main.qa_db, "_base_sha", "sha-of-main-at-start")
    monkeypatch.setattr(main.qa_db, "_unpushed", [])
    monkeypatch.setattr(main.ai_engine, "system_prompt", main.ai_engine.system_prompt)
    monkeypatch.setattr(main, "_processed_fb_mids", set())
    monkeypatch.setattr(main, "_processed_tg_mids", set())

    monkeypatch.setattr(analytics, "ANALYTICS_PATH", str(tmp_path / "analytics.jsonl"))
    monkeypatch.setattr(escalation, "PENDING_ESCALATIONS_PATH", str(tmp_path / "pending_escalations.json"))
    monkeypatch.setattr(escalation, "ESCALATION_LOG_PATH", str(tmp_path / "escalation_log.json"))
    monkeypatch.setattr(escalation, "_pending", {})
    monkeypatch.setattr(customer_memory, "CUSTOMERS_PATH", str(tmp_path / "customers.json"))
    monkeypatch.setattr(customer_memory, "_customers", {})
    monkeypatch.setattr(customer_memory, "_loaded", True)
    monkeypatch.setattr(customer_memory, "_pull_failed", False)

    yield

    assert not forbidden_calls, f"test đã chạm vào: {forbidden_calls}"


QA_TOKEN = "ghp_fake_token_qa"
QA_API = "https://api.github.com/repos/pichu124/casa_preschool-messenger-bot/contents/data/qa_database.json"


class FakeGitHubMain:
    """data/qa_database.json trên nhánh main của GitHub, sau httpx (transport đồng bộ và bất đồng bộ).

    GET trả bản raw hoặc JSON (sha + content base64 xuống dòng như GitHub), PUT phải nêu đúng sha hiện tại,
    sai thì 409 như GitHub. `down = True`: mọi request nhận 503. `commit()`: một commit khác lên main
    (sửa tay, instance khác)."""

    def __init__(self):
        self.down = False
        self.requests = []
        self.content = b""
        self.sha = None

    def commit(self, qa_pairs):
        self.content = json.dumps({"qa_pairs": qa_pairs}, ensure_ascii=False, indent=2).encode()
        self.sha = hashlib.sha1(self.content).hexdigest()

    @property
    def qa_pairs(self) -> list[dict]:
        return json.loads(self.content)["qa_pairs"]

    def puts(self) -> list:
        return [r for r in self.requests if r["method"] == "PUT"]

    def respond(self, request) -> httpx.Response:
        assert str(request.url).split("?")[0] == QA_API, request.url
        try:
            asyncio.get_running_loop()
            in_event_loop = True
        except RuntimeError:
            in_event_loop = False
        rec = {
            "method": request.method,
            "url": str(request.url),
            "authorization": request.headers.get("Authorization"),
            "read_timeout": request.extensions["timeout"]["read"],
            "in_event_loop": in_event_loop,
        }
        self.requests.append(rec)
        if self.down:
            rec["status"] = 503
            return httpx.Response(503, json={"message": "Service Unavailable"})
        if request.method == "GET":
            rec["status"] = 200
            if "raw" in request.headers.get("Accept", ""):
                return httpx.Response(200, content=self.content)
            encoded = base64.encodebytes(self.content).decode()
            return httpx.Response(200, json={"sha": self.sha, "encoding": "base64", "content": encoded})
        assert request.method == "PUT", request.method
        body = json.loads(request.content)
        if body.get("sha") != self.sha:
            rec["status"] = 409
            return httpx.Response(409, json={"message": f"data/qa_database.json does not match {body.get('sha')}"})
        self.content = base64.b64decode(body["content"])
        self.sha = hashlib.sha1(self.content).hexdigest()
        rec["status"] = 200
        return httpx.Response(200, json={"content": {"sha": self.sha}, "commit": {"sha": "c0ffee"}})


@pytest.fixture
def github_main(monkeypatch):
    """GITHUB_TOKEN đặt sẵn và GitHub giả trả lời mọi request httpx; test gọi `commit()` để có file trên main."""
    fake = FakeGitHubMain()

    def handle(self, request):
        return fake.respond(request)

    async def handle_async(self, request):
        return fake.respond(request)

    monkeypatch.setattr(settings, "GITHUB_TOKEN", QA_TOKEN)
    monkeypatch.setattr(github_sync, "push_qa_to_github", REAL_PUSH_QA_TO_GITHUB)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle_async)
    return fake

"""Endpoint admin và Telegram webhook chỉ mở khi có secret cấu hình và gửi đúng secret đó.
customers.json chỉ lên GitHub khi đặt CUSTOMERS_GITHUB_REPO; khi đặt thì lúc nạp repo đó thắng bản trên đĩa,
và nạp lỗi thì không đẩy lên (để không đè repo bằng dữ liệu thiếu)."""

import asyncio
import base64
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import customer_memory, escalation, messenger
from app.config import settings

client = TestClient(main.app)
# conftest thay hàm này bằng stub cấm gọi; giữ bản thật để kiểm nó không ra mạng khi chưa đặt repo.
REAL_SYNC_CUSTOMERS = customer_memory.sync_to_github

# (method, path, kwargs) cho mọi endpoint admin; kwargs là input hợp lệ để chỉ secret quyết định 403.
ADMIN_ENDPOINTS = [
    ("GET", "/dashboard", {}),
    ("GET", "/analytics/stats", {}),
    ("GET", "/analytics/messages", {}),
    ("GET", "/customers", {}),
    ("GET", "/customers/export", {}),
    ("POST", "/analytics/reset", {}),
    ("POST", "/customers/9000000000000002/reset", {}),
    ("GET", "/qa-database", {}),
    ("GET", "/qa-learned", {}),
    ("POST", "/reload-qa", {}),
    ("POST", "/import-excel", {"params": {"file_path": "khong-ton-tai.xlsx"}}),
    ("POST", "/test-chat", {"json": {"message": "Học phí bao nhiêu ạ?"}}),
    ("POST", "/setup-telegram-webhook", {}),
    ("POST", "/setup-messenger-profile", {}),
    ("POST", "/followup/run", {}),
]
ADMIN_IDS = [f"{method} {path}" for method, path, _ in ADMIN_ENDPOINTS]
WRONG_SECRETS = [None, "", "sai", "casa-bot-secret-2024", "s3cret ", "bí-mật"]

TG_HEADER = "X-Telegram-Bot-Api-Secret-Token"
ESCALATION_MSG_ID = 5151
CUSTOMER_ID = "9000000000000002"

PRIVATE_REPO = "casa-owner/casa-private-data"
CUSTOMERS_API = f"https://api.github.com/repos/{PRIVATE_REPO}/contents/data/customers.json"
OBJECT_MEDIA_TYPE = "application/vnd.github.object+json"
# Bản cũ trên đĩa: data/customers.json được track trong repo code nên có sẵn trong image Render.
DISK_PROFILES = {"9000000000000006": {"kid_age": "2"}}
REMOTE_PROFILES = {"9000000000000007": {"kid_age": "4"}, "9000000000000008": {"kid_age": "5"}}
NEW_CUSTOMER = "9000000000000009"


def call(method, path, kwargs, secret):
    kwargs = {**kwargs, "params": dict(kwargs.get("params", {}))}
    if secret is not None:
        kwargs["params"]["secret"] = secret
    return client.request(method, path, **kwargs)


@pytest.mark.parametrize("secret", [None, "", "bất-kỳ", "casa-bot-secret-2024"])
@pytest.mark.parametrize(("method", "path", "kwargs"), ADMIN_ENDPOINTS, ids=ADMIN_IDS)
def test_admin_endpoints_locked_when_no_secret_configured(monkeypatch, method, path, kwargs, secret):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")

    assert call(method, path, kwargs, secret).status_code == 403


@pytest.mark.parametrize("secret", WRONG_SECRETS)
@pytest.mark.parametrize(("method", "path", "kwargs"), ADMIN_ENDPOINTS, ids=ADMIN_IDS)
def test_admin_endpoints_reject_wrong_secret(monkeypatch, method, path, kwargs, secret):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s3cret")

    assert call(method, path, kwargs, secret).status_code == 403


def test_admin_endpoints_accept_configured_secret(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s3cret")

    resp = client.get("/qa-database", params={"secret": "s3cret"})
    assert resp.status_code == 200
    assert resp.json()["total"] == len(main.qa_db.qa_pairs) > 0

    resp = client.post("/reload-qa", params={"secret": "s3cret"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "reloaded"


def test_default_config_has_no_public_secret():
    """Không đặt biến môi trường thì không có secret nào mở được endpoint (secret trong code là công khai)."""
    env = {k: v for k, v in os.environ.items() if k != "TELEGRAM_WEBHOOK_SECRET"}
    code = (
        "import dotenv; dotenv.load_dotenv = lambda *a, **k: False\n"
        "from app.config import settings; print(repr(settings.TELEGRAM_WEBHOOK_SECRET))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "''"


def test_startup_warns_about_missing_secrets(monkeypatch, caplog):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "")
    monkeypatch.setattr(settings, "FB_APP_SECRET", "")

    with caplog.at_level(logging.WARNING, logger=main.logger.name):
        main._warn_insecure_config()

    warnings = " ".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)
    assert "TELEGRAM_WEBHOOK_SECRET" in warnings
    assert "FB_APP_SECRET" in warnings


def test_request_logs_do_not_carry_tokens_from_urls(monkeypatch, caplog):
    """Token bot Telegram nằm trong path URL, token trang Facebook trong query: không record log nào chứa chúng."""
    telegram_token = "123456:telegram-token-test"
    page_token = "EAAB-page-token-test"
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", telegram_token)
    monkeypatch.setattr(settings, "TELEGRAM_CHAT_ID", "-1001")
    monkeypatch.setattr(settings, "FB_PAGE_ACCESS_TOKEN", page_token)
    hosts = []

    async def fake_api(self, request):
        hosts.append(request.url.host)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_api)

    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(escalation.escalate_to_admin(CUSTOMER_ID, "Lan Thử", "Có xe đưa đón không?")) is True
        asyncio.run(messenger.send_message(CUSTOMER_ID, "Dạ em chào Ba/Mẹ ạ"))

    assert hosts == ["api.telegram.org", "graph.facebook.com"]
    assert [r for r in caplog.records if CUSTOMER_ID in r.getMessage()], "không bắt được log nào"
    tokens = (telegram_token, page_token)
    assert [r.getMessage() for r in caplog.records if any(t in r.getMessage() for t in tokens)] == []


def admin_reply_update() -> dict:
    return {
        "update_id": 2,
        "message": {
            "message_id": ESCALATION_MSG_ID + 1,
            "chat": {"id": -1001234567890, "type": "supergroup"},
            "text": "Có xe đưa đón ạ",
            "reply_to_message": {
                "message_id": ESCALATION_MSG_ID,
                "text": f"⚠️ CẦN TRỢ GIÚP ⚠️\n\n🆔 ID: {CUSTOMER_ID}\n\n❓ Câu hỏi:\nCó xe đưa đón không?",
            },
        },
    }


@pytest.mark.parametrize(
    ("configured", "header"),
    [
        ("s3cret", None),
        ("s3cret", "sai"),
        ("s3cret", ""),
        ("s3cret", "bí-mật".encode()),
        ("", None),
        ("", ""),
        ("", "casa-bot-secret-2024"),
    ],
    ids=["thiếu header", "header sai", "header rỗng", "header non-ASCII", "chưa cấu hình", "chưa cấu hình, header rỗng", "secret mặc định cũ"],
)
def test_telegram_webhook_rejects_without_valid_secret_token(monkeypatch, configured, header):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", configured)
    escalation._pending[ESCALATION_MSG_ID] = {"customer_id": CUSTOMER_ID, "question": "Có xe đưa đón không?"}
    sent = []

    async def fake_send_message(recipient_id, text, **kwargs):
        sent.append((recipient_id, text))

    monkeypatch.setattr(main, "send_message", fake_send_message)
    headers = {} if header is None else {TG_HEADER: header}

    resp = client.post("/telegram-webhook", json=admin_reply_update(), headers=headers)

    assert resp.status_code == 403
    assert sent == []
    assert escalation.get_pending_escalation(ESCALATION_MSG_ID) is not None
    assert ESCALATION_MSG_ID + 1 not in main._processed_tg_mids


def test_telegram_webhook_accepts_correct_secret_token(monkeypatch):
    """Luồng admin reply đầy đủ với header đúng nằm ở tests/test_admin_reply.py."""
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s3cret")
    update = {"update_id": 3, "message": {"message_id": 1, "chat": {"id": 1}, "text": "chào"}}

    resp = client.post("/telegram-webhook", json=update, headers={TG_HEADER: "s3cret"})

    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}


@pytest.mark.parametrize(
    "body",
    [b"", b"khong phai json", b"\xff\xfe{", b"[]", b"null"],
    ids=["body rỗng", "không phải JSON", "không phải UTF-8", "JSON mảng", "JSON null"],
)
def test_telegram_webhook_ignores_unparseable_body(monkeypatch, body):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "s3cret")

    resp = client.post(
        "/telegram-webhook", content=body, headers={TG_HEADER: "s3cret", "Content-Type": "application/json"}
    )

    assert resp.status_code == 200
    assert resp.json() == {"status": "ignored"}


@pytest.fixture
def github_token(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "ghp_fake_token")


def test_customers_not_pushed_without_repo(monkeypatch, github_token):
    monkeypatch.setattr(settings, "CUSTOMERS_GITHUB_REPO", "")
    monkeypatch.setattr(customer_memory, "sync_to_github", REAL_SYNC_CUSTOMERS)

    assert asyncio.run(REAL_SYNC_CUSTOMERS()) is False
    profile = asyncio.run(customer_memory.update_profile("9000000000000003", {"kid_age": "3"}))

    assert profile["kid_age"] == "3"
    saved = json.loads(Path(customer_memory.CUSTOMERS_PATH).read_text(encoding="utf-8"))
    assert saved["9000000000000003"]["kid_age"] == "3"
    # conftest fail ở teardown nếu có request mạng nào (kể cả khi code nuốt exception).


@pytest.mark.parametrize("disk", [None, DISK_PROFILES], ids=["đĩa trống", "có bản trên đĩa"])
def test_customers_not_pulled_without_repo(monkeypatch, github_token, disk):
    monkeypatch.setattr(settings, "CUSTOMERS_GITHUB_REPO", "")
    monkeypatch.setattr(customer_memory, "_loaded", False)
    if disk is not None:
        Path(customer_memory.CUSTOMERS_PATH).write_text(json.dumps(disk), encoding="utf-8")

    assert customer_memory.get_all_profiles() == (disk or {})


def test_customers_pushed_only_to_configured_repo(monkeypatch, github_token):
    monkeypatch.setattr(settings, "CUSTOMERS_GITHUB_REPO", "casa-owner/casa-private-data")
    monkeypatch.setattr(customer_memory, "_customers", {"9000000000000004": {"kid_age": "4"}})
    requests = []
    sha_accept = []

    async def fake_github(self, request):
        requests.append((request.method, str(request.url)))
        if request.method == "GET":
            sha_accept.append(request.headers.get("Accept"))
        return httpx.Response(404 if request.method == "GET" else 201)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_github)

    assert asyncio.run(REAL_SYNC_CUSTOMERS()) is True
    url = "https://api.github.com/repos/casa-owner/casa-private-data/contents/data/customers.json"
    assert requests == [("GET", f"{url}?ref=main"), ("PUT", url)]
    assert sha_accept == [OBJECT_MEDIA_TYPE]


def test_customers_pulled_only_from_configured_repo(monkeypatch, github_token):
    monkeypatch.setattr(settings, "CUSTOMERS_GITHUB_REPO", "casa-owner/casa-private-data")
    monkeypatch.setattr(customer_memory, "_loaded", False)
    remote = {"9000000000000005": {"kid_age": "5"}}
    requests = []
    respond = github_file(remote)

    def fake_github(self, request):
        requests.append(str(request.url))
        return respond(request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_github)

    assert customer_memory.get_all_profiles() == remote
    assert requests == [
        "https://api.github.com/repos/casa-owner/casa-private-data/contents/data/customers.json?ref=main"
    ]


def github_file(profiles):
    """Contents API trả customers.json như GitHub: body thô khi xin media type raw; metadata JSON có `sha` và
    `content` base64 khi xin media type object hoặc mặc định. File 1–100 MB: media type object trả `content` rỗng
    và `encoding` "none", media type mặc định bị 403."""
    body = json.dumps(profiles).encode()

    def respond(request) -> httpx.Response:
        accept = request.headers.get("Accept")
        if accept == "application/vnd.github.raw+json":
            return httpx.Response(200, content=body)
        if len(body) > 1024 * 1024:
            if accept == OBJECT_MEDIA_TYPE:
                return httpx.Response(200, json={"sha": "abc123", "content": "", "encoding": "none"})
            return github_too_large(request)
        return httpx.Response(200, json={"sha": "abc123", "content": base64.b64encode(body).decode()})

    return respond


def github_too_large(request) -> httpx.Response:
    return httpx.Response(403, json={"message": "This API returns blobs up to 1 MB in size.", "errors": [{"code": "too_large"}]})


def github_timeout(request):
    raise httpx.ConnectTimeout("timed out")


@pytest.fixture
def private_repo(monkeypatch, github_token):
    """CUSTOMERS_GITHUB_REPO đặt, bot vừa khởi động lại với bản cũ trên đĩa; trả về các bản đã PUT lên GitHub."""
    monkeypatch.setattr(settings, "CUSTOMERS_GITHUB_REPO", PRIVATE_REPO)
    monkeypatch.setattr(customer_memory, "sync_to_github", REAL_SYNC_CUSTOMERS)
    monkeypatch.setattr(customer_memory, "_loaded", False)
    Path(customer_memory.CUSTOMERS_PATH).write_text(json.dumps(DISK_PROFILES), encoding="utf-8")
    pushed = []

    async def fake_github(self, request):
        assert str(request.url).startswith(CUSTOMERS_API)
        if request.method == "PUT":
            payload = json.loads(request.content)
            if payload.get("sha") != "abc123":
                return httpx.Response(422, json={"message": '"sha" wasn\'t supplied.'})
            pushed.append(json.loads(base64.b64decode(payload["content"])))
            return httpx.Response(200)
        # File trong repo private đã trên 1 MB: chỉ media type object trả metadata (sha, không có nội dung).
        if request.headers.get("Accept") != OBJECT_MEDIA_TYPE:
            return github_too_large(request)
        return httpx.Response(200, json={"sha": "abc123", "content": "", "encoding": "none"})

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_github)
    return pushed


def serve_pull(monkeypatch, respond):
    """GitHub trả lời lời kéo lúc nạp (httpx đồng bộ) bằng `respond(request)`; trả về các request đã gọi."""
    pulled = []

    def fake_github(self, request):
        pulled.append((request.method, str(request.url)))
        return respond(request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_github)
    return pulled


def new_message_then_sync() -> bool:
    asyncio.run(customer_memory.update_profile(NEW_CUSTOMER, {"kid_age": "3"}))
    return asyncio.run(customer_memory.sync_to_github())


def test_restart_loads_private_repo_over_stale_disk_copy(monkeypatch, private_repo):
    pulled = serve_pull(monkeypatch, github_file(REMOTE_PROFILES))

    assert customer_memory.get_all_profiles() == REMOTE_PROFILES
    assert pulled == [("GET", f"{CUSTOMERS_API}?ref=main")]
    assert json.loads(Path(customer_memory.CUSTOMERS_PATH).read_text(encoding="utf-8")) == REMOTE_PROFILES

    assert new_message_then_sync() is True
    assert len(private_repo) == 1
    assert set(private_repo[0]) == {*REMOTE_PROFILES, NEW_CUSTOMER}
    assert {key: private_repo[0][key] for key in REMOTE_PROFILES} == REMOTE_PROFILES


def test_restart_loads_private_repo_file_over_1mb_and_syncs(monkeypatch, private_repo):
    # ~150 khách, mỗi khách 30 tin history: customers.json vượt 1 MB.
    history = [{"role": "user", "content": "Cho mình hỏi học phí hệ song ngữ ạ " * 8}] * 30
    remote = {f"9100000000{i:06d}": {"kid_age": "4", "conversation_history": history} for i in range(150)}
    assert len(json.dumps(remote).encode()) > 1024 * 1024
    pulled = serve_pull(monkeypatch, github_file(remote))

    assert customer_memory.get_all_profiles() == remote
    assert pulled == [("GET", f"{CUSTOMERS_API}?ref=main")]

    assert new_message_then_sync() is True
    assert len(private_repo) == 1
    assert set(private_repo[0]) == {*remote, NEW_CUSTOMER}
    assert {key: private_repo[0][key] for key in remote} == remote


@pytest.mark.parametrize(
    "respond",
    [
        lambda request: httpx.Response(500),
        lambda request: httpx.Response(403),
        github_timeout,
        lambda request: httpx.Response(200, content=b'{"9000'),
        lambda request: httpx.Response(200, content=b""),
        lambda request: httpx.Response(200, json=list(REMOTE_PROFILES)),
    ],
    ids=["GitHub 500", "GitHub 403", "timeout", "JSON hỏng", "body rỗng", "không phải object"],
)
def test_failed_pull_keeps_bot_running_but_never_pushes(monkeypatch, caplog, private_repo, respond):
    serve_pull(monkeypatch, respond)

    with caplog.at_level(logging.ERROR, logger=customer_memory.logger.name):
        assert customer_memory.get_all_profiles() == DISK_PROFILES

    assert new_message_then_sync() is False
    assert private_repo == []
    assert customer_memory.get_profile(NEW_CUSTOMER)["kid_age"] == "3"
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert [m for m in errors if PRIVATE_REPO in m], errors


@pytest.mark.parametrize("disk", [DISK_PROFILES, None], ids=["có bản trên đĩa", "đĩa trống"])
def test_private_repo_without_file_starts_from_disk_and_syncs(monkeypatch, private_repo, disk):
    if disk is None:
        Path(customer_memory.CUSTOMERS_PATH).unlink()
    pulled = serve_pull(monkeypatch, lambda request: httpx.Response(404))

    assert customer_memory.get_all_profiles() == (disk or {})
    assert pulled == [("GET", f"{CUSTOMERS_API}?ref=main")]

    assert new_message_then_sync() is True
    assert len(private_repo) == 1
    assert set(private_repo[0]) == {*(disk or {}), NEW_CUSTOMER}

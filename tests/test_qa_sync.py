"""Q&A admin dạy bot nằm trên GitHub main (commit [skip deploy], không deploy lại), còn đĩa là bản trong image
của lần deploy gần nhất. Nạp Q&A (khởi động, /reload-qa) vì vậy kéo bản trên main; kéo lỗi thì dùng đĩa và
không đẩy lên, để bản trên đĩa không đè mất các cặp đã học trên main."""

import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import github_sync
from app.config import settings
from app.qa_database import QADatabase

client = TestClient(main.app)

TOKEN = "ghp_fake_token_qa"
QA_API = "https://api.github.com/repos/pichu124/casa_preschool-messenger-bot/contents/data/qa_database.json"
DISK_PAIRS = [{"category": "Học phí", "questions": ["Học phí bao nhiêu?"], "answer": "Dạ từ 5 triệu ạ.", "keywords": []}]
LEARNED_PAIR = {
    "category": "Xe đưa đón",
    "questions": ["Có xe đưa đón Long Biên không?"],
    "answer": "Có xe tuyến Long Biên, đón 7h15 tại cổng Aeon Mall",
    "keywords": ["xe đưa đón"],
    "source": "admin",
    "learned_at": "2026-10-20T01:00:00+00:00",
}
REMOTE_PAIRS = DISK_PAIRS + [LEARNED_PAIR]


@pytest.fixture
def disk(tmp_path):
    """Bản trên đĩa (trong image), cũ hơn bản trên main."""
    path = tmp_path / "qa_database.json"
    path.write_text(json.dumps({"qa_pairs": DISK_PAIRS}, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", TOKEN)


def serve_pull(monkeypatch, respond):
    """GitHub trả lời lời kéo lúc nạp (httpx đồng bộ) bằng `respond(request)`; trả về các request đã gọi."""
    pulled = []

    def fake_github(self, request):
        pulled.append(request)
        return respond(request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_github)
    return pulled


def raw_file(qa_pairs):
    body = json.dumps({"qa_pairs": qa_pairs}, ensure_ascii=False).encode()

    def respond(request):
        if request.headers.get("Accept") != "application/vnd.github.raw+json":
            return httpx.Response(415)
        return httpx.Response(200, content=body)

    return respond


def disk_pairs(path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["qa_pairs"]


def test_load_uses_github_main_over_stale_disk_and_rewrites_disk(monkeypatch, caplog, disk, token):
    pulled = serve_pull(monkeypatch, raw_file(REMOTE_PAIRS))

    with caplog.at_level(logging.INFO):
        db = QADatabase(str(disk))

    assert db.qa_pairs == REMOTE_PAIRS
    assert LEARNED_PAIR["answer"] in db.build_context()
    assert disk_pairs(disk) == REMOTE_PAIRS
    assert [(r.method, str(r.url)) for r in pulled] == [("GET", f"{QA_API}?ref=main")]
    assert pulled[0].headers["Authorization"] == f"token {TOKEN}"
    assert pulled[0].extensions["timeout"]["read"] == 10
    logs = " ".join(r.getMessage() for r in caplog.records)
    assert "Loaded 2 Q&A pairs from GitHub" in logs
    assert TOKEN not in logs
    assert LEARNED_PAIR["answer"] not in logs


def github_timeout(request):
    raise httpx.ReadTimeout("timed out")


def github_unreachable(request):
    raise httpx.ConnectError("[Errno -3] Temporary failure in name resolution")


@pytest.mark.parametrize(
    "respond",
    [
        lambda request: httpx.Response(404, json={"message": "Not Found"}),
        lambda request: httpx.Response(401, json={"message": "Bad credentials"}),
        lambda request: httpx.Response(403, json={"message": "Resource not accessible"}),
        lambda request: httpx.Response(500),
        lambda request: httpx.Response(503),
        github_timeout,
        github_unreachable,
        lambda request: httpx.Response(200, content=b'{"qa_pairs": [{"categ'),
        lambda request: httpx.Response(200, content=b""),
        lambda request: httpx.Response(200, json=REMOTE_PAIRS),
        lambda request: httpx.Response(200, json={"pairs": REMOTE_PAIRS}),
        lambda request: httpx.Response(200, json={"qa_pairs": {"0": LEARNED_PAIR}}),
        lambda request: httpx.Response(200, json={"qa_pairs": []}),
        lambda request: httpx.Response(200, json={"qa_pairs": ["Học phí bao nhiêu?"]}),
    ],
    ids=[
        "404", "401", "403", "500", "503", "timeout", "mất mạng", "JSON hỏng", "body rỗng", "không phải object",
        "thiếu qa_pairs", "qa_pairs không phải list", "qa_pairs rỗng", "cặp không phải object",
    ],
)
def test_failed_pull_uses_disk_logs_error_and_never_pushes(monkeypatch, caplog, disk, token, respond):
    serve_pull(monkeypatch, respond)
    pushed = []

    async def fake_push_qa_to_github(qa_pairs):
        pushed.append(qa_pairs)
        return True

    monkeypatch.setattr(github_sync, "push_qa_to_github", fake_push_qa_to_github)

    with caplog.at_level(logging.INFO):
        db = QADatabase(str(disk))
        assert db.qa_pairs == DISK_PAIRS
        asyncio.run(db.add_qa_pair("Khác", "Câu mới?", "Dạ câu trả lời mới ạ.", source="admin"))

    assert pushed == []
    assert disk_pairs(disk)[-1]["answer"] == "Dạ câu trả lời mới ạ."
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert any("GitHub" in m for m in errors), errors
    logs = " ".join(r.getMessage() for r in caplog.records)
    assert "Loaded 1 Q&A pairs from disk" in logs
    assert TOKEN not in logs


def test_without_token_reads_disk_and_never_calls_github(monkeypatch, disk):
    pulled = serve_pull(monkeypatch, raw_file(REMOTE_PAIRS))

    db = QADatabase(str(disk))

    assert db.qa_pairs == DISK_PAIRS
    assert pulled == []


def test_reload_qa_pulls_latest_from_github(monkeypatch, token):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "tg-secret_123")
    Path(main.qa_db.path).write_text(json.dumps({"qa_pairs": DISK_PAIRS}), encoding="utf-8")
    serve_pull(monkeypatch, raw_file(REMOTE_PAIRS))

    resp = client.post("/reload-qa", params={"secret": "tg-secret_123"})

    assert resp.json() == {"status": "reloaded", "qa_pairs": 2}
    assert LEARNED_PAIR["answer"] in main.ai_engine.system_prompt
    assert disk_pairs(main.qa_db.path) == REMOTE_PAIRS

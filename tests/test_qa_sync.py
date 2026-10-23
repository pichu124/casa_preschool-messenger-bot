"""Q&A admin dạy bot nằm trên GitHub main (commit [skip deploy], không deploy lại), còn đĩa là bản trong image
của lần deploy gần nhất. Nạp Q&A (khởi động, /reload-qa) vì vậy kéo bản trên main; chưa từng kéo được thì dùng đĩa
và không đẩy lên, để bản trên đĩa không đè mất các cặp đã học trên main. Cặp dạy thêm chưa đẩy được thì được giữ
và gộp vào mỗi lần kéo, tới khi đẩy được."""

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
from app import github_sync
from app.config import settings
from app.qa_database import QADatabase

client = TestClient(main.app)

ROOT = Path(__file__).resolve().parent.parent
TOKEN = "ghp_fake_token_qa"  # = conftest.QA_TOKEN, mà fixture github_main đặt
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


def file_response(content: bytes) -> httpx.Response:
    """GitHub trả file `content` (JSON media type: base64 kèm sha)."""
    return httpx.Response(200, json={"sha": "abc123", "encoding": "base64", "content": base64.b64encode(content).decode()})


def file_of(data) -> httpx.Response:
    return file_response(json.dumps(data, ensure_ascii=False).encode())


def disk_pairs(path) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["qa_pairs"]


def test_load_uses_github_main_over_stale_disk_and_rewrites_disk(caplog, disk, github_main):
    github_main.commit(REMOTE_PAIRS)

    with caplog.at_level(logging.INFO):
        db = QADatabase(str(disk))

    assert db.qa_pairs == REMOTE_PAIRS
    assert LEARNED_PAIR["answer"] in db.build_context()
    assert disk_pairs(disk) == REMOTE_PAIRS
    assert [(r["method"], r["url"], r["authorization"]) for r in github_main.requests] == [
        ("GET", f"{QA_API}?ref=main", f"token {TOKEN}")
    ]
    assert github_main.requests[0]["read_timeout"] == 10
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
        lambda request: httpx.Response(200, content=b""),
        lambda request: httpx.Response(200, json={"sha": "abc123", "encoding": "none", "content": ""}),
        lambda request: file_response(b'{"qa_pairs": [{"categ'),
        lambda request: file_response(b""),
        lambda request: file_of(REMOTE_PAIRS),
        lambda request: file_of({"pairs": REMOTE_PAIRS}),
        lambda request: file_of({"qa_pairs": {"0": LEARNED_PAIR}}),
        lambda request: file_of({"qa_pairs": []}),
        lambda request: file_of({"qa_pairs": ["Học phí bao nhiêu?"]}),
    ],
    ids=[
        "404", "401", "403", "500", "503", "timeout", "mất mạng", "body rỗng", "file trên 1 MB", "JSON hỏng",
        "file rỗng", "không phải object", "thiếu qa_pairs", "qa_pairs không phải list", "qa_pairs rỗng",
        "cặp không phải object",
    ],
)
def test_failed_pull_uses_disk_logs_error_and_never_pushes(monkeypatch, caplog, disk, token, respond):
    serve_pull(monkeypatch, respond)
    pushed = []

    def fake_push_qa_to_github(qa_pairs, sha):
        pushed.append(qa_pairs)
        return "sha-after-push"

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
    pulled = serve_pull(monkeypatch, lambda request: file_of({"qa_pairs": REMOTE_PAIRS}))

    db = QADatabase(str(disk))

    assert db.qa_pairs == DISK_PAIRS
    assert pulled == []


def test_reload_qa_pulls_latest_from_github(monkeypatch, github_main):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "tg-secret_123")
    Path(main.qa_db.path).write_text(json.dumps({"qa_pairs": DISK_PAIRS}), encoding="utf-8")
    github_main.commit(REMOTE_PAIRS)

    resp = client.post("/reload-qa", params={"secret": "tg-secret_123"})

    assert resp.json() == {"status": "reloaded", "qa_pairs": 2}
    assert LEARNED_PAIR["answer"] in main.ai_engine.system_prompt
    assert disk_pairs(main.qa_db.path) == REMOTE_PAIRS


# --- Không mất cặp nào: cặp dạy thêm, bản sửa tay trên main, cặp bị xoá trên main ---

TAUGHT_ANSWER = "Dạ trường có bể bơi trong nhà, bé học bơi mỗi thứ Sáu ạ."
EDITED_PAIR = {"category": "Giờ học", "questions": ["Mấy giờ đón bé?"], "answer": "Dạ đón bé từ 16h30 ạ.", "keywords": []}


def teach(db):
    asyncio.run(db.add_qa_pair("Cơ sở vật chất", "Trường có bể bơi không?", TAUGHT_ANSWER, source="admin"))


def answers(qa_pairs) -> list[str]:
    return [p["answer"] for p in qa_pairs]


def test_pair_taught_after_failed_reload_is_still_pushed(disk, github_main):
    """Kéo OK lúc khởi động thì bộ nhớ đã mới; một /reload-qa lỗi sau đó không được tắt việc đẩy."""
    github_main.commit(REMOTE_PAIRS)
    db = QADatabase(str(disk))
    github_main.down = True
    db.reload()
    assert db.qa_pairs == REMOTE_PAIRS
    github_main.down = False

    teach(db)

    assert answers(github_main.qa_pairs) == answers(REMOTE_PAIRS) + [TAUGHT_ANSWER]


def test_pair_taught_while_github_down_survives_reload_and_is_pushed(disk, github_main):
    """Khởi động kéo lỗi, admin dạy P (chỉ trên đĩa), rồi /reload-qa kéo được: P không bị bản trên main xoá."""
    github_main.commit(REMOTE_PAIRS)
    github_main.down = True
    db = QADatabase(str(disk))
    teach(db)
    assert answers(github_main.qa_pairs) == answers(REMOTE_PAIRS)
    github_main.down = False

    db.reload()

    assert answers(db.qa_pairs) == answers(REMOTE_PAIRS) + [TAUGHT_ANSWER]
    assert answers(disk_pairs(disk)) == answers(REMOTE_PAIRS) + [TAUGHT_ANSWER]
    assert answers(github_main.qa_pairs) == answers(REMOTE_PAIRS) + [TAUGHT_ANSWER]


def test_push_after_main_moved_on_keeps_the_manual_edit(disk, github_main):
    """Main có commit mới sau lần kéo (sửa tay, hay instance khác lúc deploy): PUT 409, kéo lại, gộp, đẩy lại."""
    github_main.commit(REMOTE_PAIRS)
    db = QADatabase(str(disk))
    github_main.commit(REMOTE_PAIRS + [EDITED_PAIR])

    teach(db)

    expected = answers(REMOTE_PAIRS) + [EDITED_PAIR["answer"], TAUGHT_ANSWER]
    assert answers(github_main.qa_pairs) == expected
    assert answers(db.qa_pairs) == expected
    assert [r["status"] for r in github_main.puts()] == [409, 200]


def test_pair_whose_push_failed_goes_up_with_the_next_one(disk, github_main):
    github_main.commit(REMOTE_PAIRS)
    db = QADatabase(str(disk))
    github_main.down = True
    teach(db)
    github_main.down = False

    asyncio.run(db.add_qa_pair("Khác", "Có học bù không?", "Dạ có học bù ạ.", source="admin"))

    assert answers(github_main.qa_pairs) == answers(REMOTE_PAIRS) + [TAUGHT_ANSWER, "Dạ có học bù ạ."]


def test_pair_deleted_on_main_does_not_come_back(disk, github_main):
    """Chỉ cặp chưa đẩy được gộp vào bản trên main, không phải cả bộ nhớ: cặp xoá tay trên main không sống lại."""
    github_main.commit(REMOTE_PAIRS)
    db = QADatabase(str(disk))
    github_main.commit(DISK_PAIRS)

    teach(db)
    db.reload()

    assert answers(github_main.qa_pairs) == answers(DISK_PAIRS) + [TAUGHT_ANSWER]
    assert answers(db.qa_pairs) == answers(DISK_PAIRS) + [TAUGHT_ANSWER]


def test_reload_qa_does_not_block_the_event_loop(monkeypatch, github_main):
    monkeypatch.setattr(settings, "TELEGRAM_WEBHOOK_SECRET", "tg-secret_123")
    github_main.commit(REMOTE_PAIRS)

    resp = client.post("/reload-qa", params={"secret": "tg-secret_123"})

    assert resp.json() == {"status": "reloaded", "qa_pairs": 2}
    assert [(r["method"], r["in_event_loop"]) for r in github_main.requests] == [("GET", False)]


def test_github_token_is_stripped_when_read_from_env():
    """Token dán kèm xuống dòng: h11 từ chối header, và lỗi của nó chứa nguyên token."""
    env = {**os.environ, "GITHUB_TOKEN": "ghp_fake_token_env\n"}
    out = subprocess.run(
        [sys.executable, "-c", "from app.config import settings; print(repr(settings.GITHUB_TOKEN))"],
        env=env, cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout

    assert out.strip() == repr("ghp_fake_token_env")


def leaky_github(request):
    raise httpx.LocalProtocolError(f"Illegal header value b'token {TOKEN} '")


def test_github_errors_never_log_the_token(monkeypatch, caplog, disk, github_main):
    github_main.commit(REMOTE_PAIRS)

    def push_leaks(request):
        return leaky_github(request) if request.method == "PUT" else github_main.respond(request)

    async def push_leaks_async(self, request):
        return push_leaks(request)

    with caplog.at_level(logging.INFO):
        serve_pull(monkeypatch, leaky_github)
        db = QADatabase(str(disk))
        serve_pull(monkeypatch, push_leaks)
        monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", push_leaks_async)
        db.reload()
        teach(db)

    problems = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Failed to load" in m for m in problems) and any("push" in m for m in problems), problems
    assert TOKEN not in " ".join(r.getMessage() for r in caplog.records)


def test_eval_chat_never_syncs_qa_with_github():
    """scripts/eval_chat.py chấm bản data/qa_database.json đang sửa: không kéo main về đè lên nó."""
    env = {**os.environ, "GITHUB_TOKEN": "ghp_fake_token_env"}
    code = (
        "import importlib.util, sys; "
        "spec = importlib.util.spec_from_file_location('eval_chat', 'scripts/eval_chat.py'); "
        "spec.loader.exec_module(importlib.util.module_from_spec(spec)); "
        "from app.config import settings; print(repr(settings.GITHUB_TOKEN))"
    )
    out = subprocess.run([sys.executable, "-c", code], env=env, cwd=ROOT, capture_output=True, text=True, check=True).stdout

    assert out.strip() == repr("")

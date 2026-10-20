"""Cô lập mọi test khỏi data/ thật và mạng thật (GitHub main của repo public, Facebook, Telegram, AI).

Môi trường có thể có GITHUB_TOKEN thật, và nhiều giá trị bị chốt lúc import app.main,
nên fixture autouse dưới đây vá lại từng test. Test nào cần một lời gọi ra ngoài thì tự
monkeypatch bằng fake ghi lại lời gọi; tên được import trong app.main thì patch trên app.main.
"""

import httpx
import pytest

import app.main as main
from app import analytics, customer_memory, escalation, github_sync
from app.config import settings


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    for name in ("GITHUB_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "FB_PAGE_ACCESS_TOKEN"):
        monkeypatch.setattr(settings, name, "")
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
    monkeypatch.setattr(customer_memory, "_push_to_github", forbid("customer_memory._push_to_github"))
    # Chặn mạng thật qua httpx; TestClient dùng transport riêng nên không bị ảnh hưởng.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbid("mạng thật qua httpx"))
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbid("mạng thật qua httpx"))

    monkeypatch.setattr(main.qa_db, "path", str(tmp_path / "qa_database.json"))
    monkeypatch.setattr(main.qa_db, "qa_pairs", list(main.qa_db.qa_pairs))
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

    yield

    assert not forbidden_calls, f"test đã chạm vào: {forbidden_calls}"

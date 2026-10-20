"""Endpoint admin và Telegram webhook chỉ mở khi có secret cấu hình và gửi đúng secret đó."""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import escalation
from app.config import settings

client = TestClient(main.app)

# (method, path, kwargs) cho mọi endpoint admin; kwargs là input hợp lệ để chỉ secret quyết định 403.
ADMIN_ENDPOINTS = [
    ("GET", "/dashboard", {}),
    ("GET", "/analytics/stats", {}),
    ("GET", "/analytics/messages", {}),
    ("GET", "/customers", {}),
    ("GET", "/customers/export", {}),
    ("POST", "/analytics/reset", {}),
    ("GET", "/qa-database", {}),
    ("GET", "/qa-learned", {}),
    ("POST", "/reload-qa", {}),
    ("POST", "/import-excel", {"params": {"file_path": "khong-ton-tai.xlsx"}}),
    ("POST", "/test-chat", {"json": {"message": "Học phí bao nhiêu ạ?"}}),
    ("POST", "/setup-telegram-webhook", {}),
]
ADMIN_IDS = [f"{method} {path}" for method, path, _ in ADMIN_ENDPOINTS]
WRONG_SECRETS = [None, "", "sai", "casa-bot-secret-2024", "s3cret ", "bí-mật"]

TG_HEADER = "X-Telegram-Bot-Api-Secret-Token"
ESCALATION_MSG_ID = 5151
CUSTOMER_ID = "9000000000000002"


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

    async def fake_send_message(recipient_id, text):
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

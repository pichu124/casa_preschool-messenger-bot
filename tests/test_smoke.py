"""Smoke test: app import được và endpoint cơ bản trả đúng, không cần mạng hay API key."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check_reports_loaded_qa():
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["qa_pairs"] > 0


def test_webhook_verification_rejects_wrong_token():
    resp = client.get(
        "/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "sai-token", "hub.challenge": "123"},
    )
    assert resp.status_code == 403

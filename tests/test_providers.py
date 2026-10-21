"""Mỗi provider gửi đúng tên model lấy từ settings (đặt qua biến môi trường), không gọi API thật."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from app import ai_engine
from app.config import settings

HISTORY = [
    {"role": "user", "content": "trường ở đâu"},
    {"role": "assistant", "content": "Dạ Casa có 3 cơ sở tại Hà Nội ạ."},
]


class Recorder:
    def __init__(self, response):
        self.response = response
        self.calls: list[dict] = []

    async def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def chat_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def fake_client(provider_name: str, text: str) -> tuple[SimpleNamespace, Recorder]:
    if provider_name == "gemini":
        recorder = Recorder(SimpleNamespace(text=text))
        return SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=recorder))), recorder
    recorder = Recorder(chat_response(text))
    if provider_name == "mistral":
        return SimpleNamespace(chat=SimpleNamespace(complete_async=recorder)), recorder
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=recorder))), recorder


def make_provider(monkeypatch, name: str) -> ai_engine.AIProvider:
    for key in ("OPENAI_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setattr(settings, key, "test-key")
    return ai_engine.PROVIDER_MAP[name]()


def test_gemini_puts_system_prompt_in_system_instruction_and_history_in_roles(monkeypatch):
    provider = make_provider(monkeypatch, "gemini")
    provider.client, recorder = fake_client("gemini", "Dạ ạ.")

    asyncio.run(provider.generate("Em là tư vấn viên Casa.", "học phí bao nhiêu", HISTORY))

    (call,) = recorder.calls
    config = call["config"]
    assert config.system_instruction == "Em là tư vấn viên Casa."
    assert (config.max_output_tokens, config.temperature) == (1024, 0.3)
    assert [(c.role, [p.text for p in c.parts]) for c in call["contents"]] == [
        ("user", ["trường ở đâu"]),
        ("model", ["Dạ Casa có 3 cơ sở tại Hà Nội ạ."]),
        ("user", ["học phí bao nhiêu"]),
    ]


def test_gemini_request_on_the_wire_matches_rest_api(monkeypatch):
    """SDK thật dựng request REST; chỉ transport httpx bị thay bằng fake cục bộ."""
    sent: list[httpx.Request] = []

    async def fake_transport(self, request):
        await request.aread()
        sent.append(request)
        body = {"candidates": [{"content": {"role": "model", "parts": [{"text": "Dạ Casa nhận bé từ 15 tháng ạ."}]}}]}
        return httpx.Response(200, json=body, request=request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_transport)
    provider = make_provider(monkeypatch, "gemini")

    text = asyncio.run(provider.generate("Em là tư vấn viên Casa.", "bé mấy tuổi thì nhận", HISTORY))

    assert text == "Dạ Casa nhận bé từ 15 tháng ạ."
    (request,) = sent
    assert request.url.path.endswith("/models/gemini-2.0-flash:generateContent")
    body = json.loads(request.content)
    assert body["systemInstruction"]["parts"] == [{"text": "Em là tư vấn viên Casa."}]
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["contents"][-1]["parts"] == [{"text": "bé mấy tuổi thì nhận"}]
    assert body["generationConfig"] == {"maxOutputTokens": 1024, "temperature": 0.3}

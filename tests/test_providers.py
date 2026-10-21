"""Mỗi provider gửi đúng tên model lấy từ settings (đặt qua biến môi trường), không gọi API thật."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import ai_engine
from app.config import settings

REPO_ROOT = Path(__file__).resolve().parent.parent

MODEL_ENV = {
    "OPENAI_MODEL": "gpt-4o-mini",
    "GROQ_MODEL": "openai/gpt-oss-120b",
    "GROQ_SECOND_MODEL": "qwen/qwen3.8-27b",
    "MISTRAL_MODEL": "mistral-small-latest",
    "DEEPSEEK_MODEL": "deepseek-flash",
    "GEMINI_MODEL": "gemini-3.5-flash",
}

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


@pytest.mark.parametrize(
    "provider_name, setting_name",
    [
        ("openai", "OPENAI_MODEL"),
        ("groq", "GROQ_MODEL"),
        ("groq_llama", "GROQ_SECOND_MODEL"),
        ("mistral", "MISTRAL_MODEL"),
        ("deepseek", "DEEPSEEK_MODEL"),
        ("gemini", "GEMINI_MODEL"),
    ],
)
def test_provider_sends_model_from_settings(monkeypatch, provider_name, setting_name):
    monkeypatch.setattr(settings, setting_name, f"model-dat-qua-env-{provider_name}")
    provider = make_provider(monkeypatch, provider_name)
    provider.client, recorder = fake_client(provider_name, "Dạ em chào Ba/Mẹ ạ.")

    text = asyncio.run(provider.generate("system", "học phí bao nhiêu", HISTORY))

    assert text == "Dạ em chào Ba/Mẹ ạ."
    assert [call["model"] for call in recorder.calls] == [f"model-dat-qua-env-{provider_name}"]


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
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-test-model")
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
    assert request.url.path.endswith("/models/gemini-test-model:generateContent")
    body = json.loads(request.content)
    assert body["systemInstruction"]["parts"] == [{"text": "Em là tư vấn viên Casa."}]
    assert [c["role"] for c in body["contents"]] == ["user", "model", "user"]
    assert body["contents"][-1]["parts"] == [{"text": "bé mấy tuổi thì nhận"}]
    assert body["generationConfig"] == {"maxOutputTokens": 1024, "temperature": 0.3}


def read_model_settings(env: dict[str, str]) -> dict[str, str]:
    """Đọc settings trong tiến trình mới (Settings chốt giá trị lúc import), bỏ qua .env cục bộ."""
    code = (
        "import json, dotenv\n"
        "dotenv.load_dotenv = lambda *a, **k: False\n"
        "from app.config import settings\n"
        f"print(json.dumps({{k: getattr(settings, k) for k in {list(MODEL_ENV)!r}}}))\n"
    )
    clean = {k: v for k, v in os.environ.items() if k not in MODEL_ENV}
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, env={**clean, **env}, capture_output=True, text=True, check=True
    )
    return json.loads(out.stdout)


def test_model_defaults_replace_retired_models():
    assert read_model_settings({}) == MODEL_ENV


def test_model_names_come_from_environment():
    env = {name: f"{name.lower()}-tu-env" for name in MODEL_ENV}
    assert read_model_settings(env) == env


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_model_variable_falls_back_to_default(blank):
    assert read_model_settings({name: blank for name in MODEL_ENV}) == MODEL_ENV

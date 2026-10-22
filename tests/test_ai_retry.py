"""Gói miễn phí của provider AI: thử lại khi quá tải tạm thời, chuyển model khi vượt hạn mức, max_tokens theo provider.

SDK thật dựng request và đọc lỗi; chỉ transport httpx bị thay bằng fake cục bộ trả lời như API của từng hãng.
asyncio.sleep bị thay để ghi lại thời gian chờ thay vì chờ thật.
"""

import asyncio
import json

import httpx
import pytest

import app.main as main
from app import ai_engine, customer_memory
from app.ai_engine import AIEngine, AIProvider
from app.config import settings

REPLY = "Dạ Casa nhận bé từ 15 tháng ạ."
HOSTS = {
    "mistral": "api.mistral.ai",
    "groq_llama": "api.groq.com",
    "deepseek": "api.deepseek.com",
    "openai": "api.openai.com",
    "gemini": "generativelanguage.googleapis.com",
}
PROVIDERS = list(HOSTS)
# "groq" dùng chung host với "groq_llama"; chỉ các test không cần thân lỗi theo từng hãng mới chạy nó.
ALL_HOSTS = {**HOSTS, "groq": "api.groq.com"}

# Thân lỗi 429 "quá nhiều request", đúng dạng mỗi hãng trả.
RATE_LIMITED = {
    "mistral": {"message": "Rate limit exceeded", "type": "rate_limited", "code": "1300"},
    "groq_llama": {
        "error": {
            "message": "Rate limit reached for model `qwen/qwen3.8-27b` in organization `org_test` service tier "
            "`on_demand` on requests per minute (RPM): Limit 30, Used 30, Requested 1. Please try again in 1.2s.",
            "type": "requests",
            "code": "rate_limit_exceeded",
        }
    },
    "deepseek": {"error": {"message": "Rate limit reached", "type": "rate_limit_error", "code": "rate_limit_exceeded"}},
    "openai": {
        "error": {
            "message": "Rate limit reached for gpt-4o-mini on requests per min (RPM): Limit 3, Used 3, Requested 1.",
            "type": "requests",
            "code": "rate_limit_exceeded",
        }
    },
    "gemini": {"error": {"code": 429, "message": "Resource has been exhausted (e.g. check quota).", "status": "RESOURCE_EXHAUSTED"}},
}

GROQ_OTPM_TOO_LARGE = {
    "error": {
        "message": "Request too large for model `qwen/qwen3.8-27b` in organization `org_test` service tier `on_demand` "
        "on output tokens per minute (OTPM): Limit 1000, Requested 1024, please reduce your message size and try again.",
        "type": "tokens",
        "code": "rate_limit_exceeded",
    }
}
GROQ_ITPM_TOO_LARGE = {
    "error": {
        "message": "Request too large for model `qwen/qwen3.8-27b` in organization `org_test` service tier `on_demand` "
        "on input tokens per minute (ITPM): Limit 7000, Requested 18565, please reduce your message size and try again.",
        "type": "tokens",
        "code": "rate_limit_exceeded",
    }
}


# Thân lỗi máy chủ quá tải (5xx), đúng dạng mỗi hãng trả.
OVERLOADED = {
    "mistral": (503, {"object": "error", "message": "Service unavailable", "type": "service_unavailable", "code": "1000"}),
    "groq_llama": (503, {"error": {"message": "Service Unavailable", "type": "internal_server_error"}}),
    "deepseek": (503, {"error": {"message": "Server overloaded, please try again later.", "type": "server_error"}}),
    "openai": (500, {"error": {"message": "The server had an error while processing your request.", "type": "server_error"}}),
    "gemini": (503, {"error": {"code": 503, "message": "The model is overloaded.", "status": "UNAVAILABLE"}}),
}


# Lý do dừng khi model chạm max_tokens, đúng giá trị mỗi hãng trả (Mistral còn "model_length": chạm ngữ cảnh).
TRUNCATED = {"gemini": "MAX_TOKENS", "mistral": "length", "groq_llama": "length", "deepseek": "length", "openai": "length"}


def ok_body(provider: str, text: str, finish_reason: str | None = None) -> dict:
    if provider == "gemini":
        candidate = {"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": finish_reason or "STOP"}
        return {"candidates": [candidate]}
    return {
        "id": "cmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "test-model",
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": finish_reason or "stop"}
        ],
    }


class Wire:
    """API giả của các hãng: mỗi host trả lần lượt theo kịch bản, câu cuối lặp lại mãi; ghi body từng request.

    Một bước là (status, body[, headers]) hoặc một lỗi httpx mà transport ném ra (mất kết nối, hết giờ).
    """

    def __init__(self):
        self.script: dict[str, list] = {}
        self.bodies: dict[str, list[dict]] = {host: [] for host in HOSTS.values()}
        self.timeouts: dict[str, list[dict]] = {host: [] for host in HOSTS.values()}

    def reply(self, provider: str, *steps: tuple[int, dict, dict] | tuple[int, dict] | httpx.TransportError):
        self.script[ALL_HOSTS[provider]] = [
            s if isinstance(s, Exception) else (s[0], s[1], s[2] if len(s) > 2 else {}) for s in steps
        ]

    def hits(self, provider: str) -> int:
        return len(self.bodies[ALL_HOSTS[provider]])

    async def handle(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        host = request.url.host
        self.bodies[host].append(json.loads(request.content))
        self.timeouts[host].append(request.extensions.get("timeout"))
        steps = self.script[host]
        step = steps.pop(0) if len(steps) > 1 else steps[0]
        if isinstance(step, Exception):
            raise step
        status, body, headers = step
        return httpx.Response(status, json=body, headers=headers, request=request)


class Backup(AIProvider):
    """Model kế trong AI_MODEL_ORDER."""

    def __init__(self):
        self.calls = 0

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024):
        self.calls += 1
        return "Dạ em là model dự phòng ạ."


@pytest.fixture
def sleeps(monkeypatch):
    waited: list[float] = []

    async def no_wait(delay, result=None):
        waited.append(delay)
        return result

    monkeypatch.setattr(asyncio, "sleep", no_wait)
    return waited


@pytest.fixture
def wire(monkeypatch):
    fake = Wire()

    async def handle_async_request(self, request):
        return await fake.handle(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle_async_request)
    return fake


@pytest.fixture
def engine_with(monkeypatch):
    """AIEngine với provider SDK thật `name` đứng đầu, Backup đứng sau."""
    for key in ("OPENAI_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY", "DEEPSEEK_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setattr(settings, key, "test-key")
    monkeypatch.setattr(ai_engine, "ai_engine_instance", ai_engine.ai_engine_instance)

    def build(name: str) -> tuple[AIEngine, Backup]:
        monkeypatch.setattr(settings, "AI_MODEL_ORDER", [name, "backup"])
        engine = AIEngine(qa_context="Q&A giả")
        backup = Backup()
        engine._providers = {name: ai_engine.PROVIDER_MAP[name](), "backup": backup}
        return engine, backup

    return build


def ask(engine: AIEngine):
    return asyncio.run(engine.get_response("bé mấy tuổi thì nhận"))


# --- Quá tải tạm thời (429 do rate): chờ rồi thử lại cùng model ---


@pytest.mark.parametrize("provider", PROVIDERS)
def test_rate_limited_once_then_answers_from_same_model(engine_with, wire, sleeps, provider):
    engine, backup = engine_with(provider)
    wire.reply(provider, (429, RATE_LIMITED[provider]), (200, ok_body(provider, REPLY)))

    resp = ask(engine)

    assert (resp.text, resp.model_used, resp.should_escalate) == (REPLY, provider, False)
    assert wire.hits(provider) == 2
    assert sleeps == [1.5]
    assert backup.calls == 0


@pytest.mark.parametrize("provider", PROVIDERS)
def test_rate_limited_every_time_moves_on_after_two_retries(engine_with, wire, sleeps, provider):
    engine, backup = engine_with(provider)
    wire.reply(provider, (429, RATE_LIMITED[provider]))

    resp = ask(engine)

    assert resp.model_used == "backup"
    assert wire.hits(provider) == 3
    assert sleeps == [1.5, 3.0]
    assert backup.calls == 1


def test_retry_logs_one_short_warning_per_retry(engine_with, wire, sleeps, caplog):
    engine, _ = engine_with("mistral")
    wire.reply("mistral", (429, RATE_LIMITED["mistral"]), (200, ok_body("mistral", REPLY)))

    with caplog.at_level("WARNING", logger="app.ai_engine"):
        asyncio.run(engine.get_response("số em là 0912345678, bé tên Bông"))

    (record,) = [r for r in caplog.records if r.levelname == "WARNING"]
    line = record.getMessage()
    # Không chứa nội dung tin nhắn hay key.
    assert line == "MistralProvider lỗi tạm thời (SDKError 429), thử lại lần 1 sau 1.5s"


# --- Lỗi máy chủ (5xx, 408, 409) hoặc mất kết nối/hết giờ: thử lại cùng model 1 lần sau 1s ---


@pytest.mark.parametrize("provider", PROVIDERS)
def test_server_error_once_then_answers_from_same_model(engine_with, wire, sleeps, provider):
    engine, backup = engine_with(provider)
    wire.reply(provider, OVERLOADED[provider], (200, ok_body(provider, REPLY)))

    resp = ask(engine)

    assert (resp.text, resp.model_used, resp.should_escalate) == (REPLY, provider, False)
    assert wire.hits(provider) == 2
    assert sleeps == [1.0]
    assert backup.calls == 0


@pytest.mark.parametrize("provider", PROVIDERS)
def test_server_error_twice_moves_on_after_one_retry(engine_with, wire, sleeps, provider):
    engine, backup = engine_with(provider)
    wire.reply(provider, OVERLOADED[provider])

    resp = ask(engine)

    assert resp.model_used == "backup"
    assert wire.hits(provider) == 2
    assert sleeps == [1.0]
    assert backup.calls == 1


@pytest.mark.parametrize(
    "lost",
    [httpx.ConnectError("Connection reset by peer"), httpx.ReadTimeout("timed out")],
    ids=["connect-error", "read-timeout"],
)
@pytest.mark.parametrize("provider", PROVIDERS)
def test_connection_lost_once_then_answers_from_same_model(engine_with, wire, sleeps, provider, lost):
    engine, backup = engine_with(provider)
    wire.reply(provider, lost, (200, ok_body(provider, REPLY)))

    resp = ask(engine)

    assert (resp.text, resp.model_used) == (REPLY, provider)
    assert wire.hits(provider) == 2
    assert sleeps == [1.0]
    assert backup.calls == 0


def test_connection_lost_twice_moves_on(engine_with, wire, sleeps):
    engine, backup = engine_with("deepseek")
    wire.reply("deepseek", httpx.ConnectError("Connection reset by peer"))

    assert ask(engine).model_used == "backup"
    assert wire.hits("deepseek") == 2
    assert sleeps == [1.0]


@pytest.mark.parametrize("status", [408, 409])
def test_request_timeout_and_conflict_status_are_retried(engine_with, wire, sleeps, status):
    engine, _ = engine_with("deepseek")
    wire.reply("deepseek", (status, {"error": {"message": "Please retry"}}), (200, ok_body("deepseek", REPLY)))

    assert ask(engine).model_used == "deepseek"
    assert sleeps == [1.0]


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        (OVERLOADED["deepseek"], "DeepSeekProvider lỗi tạm thời (InternalServerError 503), thử lại lần 1 sau 1s"),
        (httpx.ConnectError("reset"), "DeepSeekProvider lỗi tạm thời (APIConnectionError), thử lại lần 1 sau 1s"),
    ],
    ids=["503", "connect-error"],
)
def test_transient_retry_logs_one_short_warning(engine_with, wire, sleeps, caplog, step, expected):
    engine, _ = engine_with("deepseek")
    wire.reply("deepseek", step, (200, ok_body("deepseek", REPLY)))

    with caplog.at_level("WARNING", logger="app.ai_engine"):
        asyncio.run(engine.get_response("số em là 0912345678, bé tên Bông"))

    assert [r.getMessage() for r in caplog.records if r.levelname == "WARNING"] == [expected]


# --- Timeout: lời gọi treo không giữ phụ huynh chờ tới mặc định của SDK (openai: 600s, mistral/genai: không giới hạn) ---


@pytest.mark.parametrize("provider", PROVIDERS)
def test_requests_carry_a_short_timeout(engine_with, wire, provider):
    engine, _ = engine_with(provider)
    wire.reply(provider, (200, ok_body(provider, REPLY)))

    ask(engine)

    (timeout,) = wire.timeouts[HOSTS[provider]]
    assert timeout["read"] == ai_engine.AI_TIMEOUT
    assert 20 <= ai_engine.AI_TIMEOUT <= 45


# --- Không thử lại: vượt hạn mức token/phút (gửi lại y nguyên vẫn bị từ chối) và các 4xx khác ---


@pytest.mark.parametrize(
    ("provider", "status", "body"),
    [
        ("groq_llama", 429, GROQ_OTPM_TOO_LARGE),
        ("groq_llama", 413, GROQ_ITPM_TOO_LARGE),
        ("mistral", 401, {"message": "Unauthorized", "request_id": "x"}),
        ("deepseek", 400, {"error": {"message": "Model Not Exist", "type": "invalid_request_error"}}),
        ("openai", 404, {"error": {"message": "The model `gpt-ten-sai` does not exist", "code": "model_not_found"}}),
        ("gemini", 400, {"error": {"code": 400, "message": "API key not valid.", "status": "INVALID_ARGUMENT"}}),
    ],
    ids=["groq-429-otpm", "groq-413-itpm", "mistral-401", "deepseek-400", "openai-404", "gemini-400"],
)
def test_non_transient_errors_move_on_immediately(engine_with, wire, sleeps, provider, status, body):
    engine, backup = engine_with(provider)
    wire.reply(provider, (status, body), (200, ok_body(provider, REPLY)))

    resp = ask(engine)

    assert resp.model_used == "backup"
    assert wire.hits(provider) == 1
    assert sleeps == []


# --- Retry-After và trần thời gian chờ ---


def test_retry_after_within_limit_is_respected(engine_with, wire, sleeps):
    engine, _ = engine_with("groq_llama")
    wire.reply(
        "groq_llama", (429, RATE_LIMITED["groq_llama"], {"retry-after": "2"}), (200, ok_body("groq_llama", REPLY))
    )

    assert ask(engine).model_used == "groq_llama"
    assert sleeps == [2.0]


def test_retry_after_too_long_moves_on_without_waiting(engine_with, wire, sleeps):
    engine, backup = engine_with("mistral")
    wire.reply("mistral", (429, RATE_LIMITED["mistral"], {"retry-after": "30"}), (200, ok_body("mistral", REPLY)))

    assert ask(engine).model_used == "backup"
    assert wire.hits("mistral") == 1
    assert sleeps == []


def test_total_wait_per_call_is_capped(engine_with, wire, sleeps):
    engine, _ = engine_with("deepseek")
    wire.reply("deepseek", (429, RATE_LIMITED["deepseek"], {"retry-after": "5"}))

    assert ask(engine).model_used == "backup"
    assert sum(sleeps) <= ai_engine.MAX_RETRY_WAIT <= 10
    assert sleeps == [5.0]
    assert wire.hits("deepseek") == 2


# --- max_tokens theo provider: model suy luận cần chỗ nghĩ; Groq miễn phí bị chặn ở 1000 token đầu ra/phút ---


def max_tokens_sent(provider: str, body: dict) -> int:
    return body["generationConfig"]["maxOutputTokens"] if provider == "gemini" else body["max_tokens"]


CALLS = {
    "extract": lambda e: e.extract_customer_info("bé nhà mình 3 tuổi"),
    "classify": lambda e: e.classify_qa("Có xe bus không?", "Dạ chưa có ạ"),
    "summarize": lambda e: e.summarize_conversation([{"role": "user", "content": "học phí bao nhiêu"}]),
    "format": lambda e: e.format_admin_reply("thang 9 mo lop", "khi nào mở lớp"),
}
GROQ_LIMITS = {"extract": (100, 300), "classify": (100, 300), "summarize": (200, 600), "format": (900, 999)}
# deepseek-flash (effort mặc định high) tính cả phần nghĩ vào max_tokens: với 300 nó nghĩ hết chỗ trước khi ra JSON,
# lời gọi phụ bị cắt rồi sang Mistral miễn phí mỗi tin, tranh 1 request/giây với câu trả lời chính.
REASONING_ROOM = 2048


@pytest.mark.parametrize("call", list(CALLS))
@pytest.mark.parametrize("provider", ["mistral", "deepseek", "openai", "gemini"])
def test_aux_calls_leave_room_for_reasoning(engine_with, wire, provider, call):
    engine, backup = engine_with(provider)
    wire.reply(provider, (200, ok_body(provider, '{"kid_age": "3 tuổi"}')))

    asyncio.run(CALLS[call](engine))

    (body,) = wire.bodies[HOSTS[provider]]
    assert max_tokens_sent(provider, body) >= REASONING_ROOM
    assert backup.calls == 0


@pytest.mark.parametrize("call", list(CALLS))
@pytest.mark.parametrize("provider", ["groq", "groq_llama"])
def test_aux_calls_on_groq_stay_within_free_tier(engine_with, wire, provider, call):
    engine, _ = engine_with(provider)
    wire.reply(provider, (200, ok_body(provider, '{"kid_age": "3 tuổi"}')))

    asyncio.run(CALLS[call](engine))

    (body,) = wire.bodies[ALL_HOSTS[provider]]
    low, high = GROQ_LIMITS[call]
    assert low <= max_tokens_sent(provider, body) <= high


@pytest.mark.parametrize("provider", ["groq", "groq_llama"])
def test_groq_reply_and_profile_extract_together_fit_output_tokens_per_minute(engine_with, wire, provider):
    engine, _ = engine_with(provider)
    wire.reply(provider, (200, ok_body(provider, '{"kid_age": "3 tuổi"}')))

    ask(engine)
    asyncio.run(CALLS["extract"](engine))

    assert sum(body["max_tokens"] for body in wire.bodies[ALL_HOSTS[provider]]) <= 1000


# DeepSeek thật 2026-10-22: deepseek-flash (model suy luận) nghĩ gần hết 1024 token, câu gửi phụ huynh cụt giữa chữ
# "…để lại SĐ". Groq miễn phí giới hạn 1000 token đầu ra/phút và tính cả max_tokens xin: 1024 bị từ chối ngay; câu
# trả lời và lời trích hồ sơ (300) chạy cùng lúc nên câu trả lời xin 700.
CHAT_MAX_TOKENS = {"mistral": 4096, "deepseek": 4096, "openai": 4096, "gemini": 4096, "groq": 700, "groq_llama": 700}


@pytest.mark.parametrize("provider", list(CHAT_MAX_TOKENS))
def test_chat_max_tokens_leave_room_for_reasoning_within_free_tier(engine_with, wire, provider):
    engine, _ = engine_with(provider)
    wire.reply(provider, (200, ok_body(provider, REPLY)))

    assert ask(engine).model_used == provider

    (body,) = wire.bodies[ALL_HOSTS[provider]]
    assert max_tokens_sent(provider, body) == CHAT_MAX_TOKENS[provider]


# --- Câu bị cắt vì chạm max_tokens: không bao giờ gửi cho phụ huynh, sang model kế ---

CUT = "Vâng ạ, em báo tư vấn viên sắp xếp cho bé một tuần học thử. Nếu tiện, Ba/Mẹ để lại SĐ"


@pytest.mark.parametrize("provider", PROVIDERS)
def test_truncated_chat_reply_is_never_sent_next_model_answers(engine_with, wire, sleeps, provider):
    engine, backup = engine_with(provider)
    wire.reply(provider, (200, ok_body(provider, CUT, TRUNCATED[provider])), (200, ok_body(provider, REPLY)))

    resp = ask(engine)

    assert (resp.text, resp.model_used, resp.should_escalate) == ("Dạ em là model dự phòng ạ.", "backup", False)
    # Gửi lại y nguyên thì model vẫn nghĩ hết chỗ đó: sang model kế ngay, không chờ.
    assert wire.hits(provider) == 1
    assert sleeps == []


def test_mistral_reply_cut_at_context_length_is_never_sent(engine_with, wire, sleeps):
    engine, backup = engine_with("mistral")
    wire.reply("mistral", (200, ok_body("mistral", CUT, "model_length")))

    assert ask(engine).model_used == "backup"
    assert backup.calls == 1


@pytest.mark.parametrize("provider", ["groq", "groq_llama"])
def test_truncated_groq_reply_is_never_sent(engine_with, wire, sleeps, provider):
    engine, backup = engine_with(provider)
    wire.reply(provider, (200, ok_body(provider, CUT, "length")))

    assert ask(engine).model_used == "backup"
    assert backup.calls == 1


@pytest.mark.parametrize("provider", PROVIDERS)
def test_complete_reply_is_sent_as_is(engine_with, wire, provider):
    engine, backup = engine_with(provider)
    wire.reply(provider, (200, ok_body(provider, REPLY)))

    assert (ask(engine).text, backup.calls) == (REPLY, 0)


def test_truncated_admin_reply_moves_on_to_next_model(engine_with, wire, sleeps):
    engine, backup = engine_with("deepseek")
    wire.reply("deepseek", (200, ok_body("deepseek", "Dạ lớp mới mở vào tháng 9, Ba/Mẹ đăng ký trước", "length")))

    text = asyncio.run(engine.format_admin_reply("thang 9 mo lop, dang ky truoc 15/8", "khi nào mở lớp"))

    assert text == "Dạ em là model dự phòng ạ."
    assert backup.calls == 1


def test_truncated_summary_is_not_kept(engine_with, wire, sleeps):
    # Tóm tắt cụt thiếu quyết định của phụ huynh; không có tóm tắt thì lịch sử được giữ nguyên để tóm tắt lần sau.
    engine, backup = engine_with("deepseek")
    wire.reply("deepseek", (200, ok_body("deepseek", "Phụ huynh hỏi học phí cho bé 3 tuổi, đã", "length")))

    summary = asyncio.run(engine.summarize_conversation([{"role": "user", "content": "học phí bao nhiêu"}]))

    assert summary == "Dạ em là model dự phòng ạ."
    assert backup.calls == 1


def test_truncated_json_is_not_trusted_even_when_it_parses(engine_with, wire, sleeps):
    # JSON cụt thường hỏng; nếu tình cờ vẫn đọc được thì có thể đã mất trường cuối: hỏi model kế.
    engine, backup = engine_with("deepseek")
    wire.reply("deepseek", (200, ok_body("deepseek", '{"kid_age": "3 tuổi"}', "length")))

    assert asyncio.run(engine.extract_customer_info("bé nhà mình 3 tuổi, số em 0912")) == {}
    assert backup.calls == 1


# --- Trả lời và trích hồ sơ cùng lúc trên provider chỉ nhận 1 request đồng thời (Mistral miễn phí) ---


class OneAtATime(AIProvider):
    """Như Mistral gói miễn phí: request thứ hai trong lúc request trước còn chạy bị 429 rate_limited."""

    def __init__(self):
        self.busy = False
        self.rejected = 0

    async def generate(self, system_prompt, user_message, conversation_history, max_tokens=1024):
        from mistralai.models import SDKError

        if self.busy:
            self.rejected += 1
            body = json.dumps(RATE_LIMITED["mistral"])
            raise SDKError("API error occurred", 429, body, httpx.Response(429, text=body))
        self.busy = True
        try:
            await REAL_SLEEP(0.01)
        finally:
            self.busy = False
        if system_prompt.startswith("Bạn là hệ thống trích xuất"):
            return '{"kid_age": "3 tuổi"}'
        return REPLY


REAL_SLEEP = asyncio.sleep


def test_reply_and_extract_both_succeed_on_one_request_at_a_time_provider(monkeypatch):
    customer_id = "9000000000000901"
    sent: list[str] = []
    waited: list[float] = []

    async def backoff(delay, result=None):
        waited.append(delay)
        await REAL_SLEEP(0.03)
        return result

    async def send_message(recipient_id, text, **kwargs):
        sent.append(text)

    async def nothing(*args, **kwargs):
        return {}

    provider = OneAtATime()
    monkeypatch.setattr(asyncio, "sleep", backoff)
    monkeypatch.setattr(main, "send_message", send_message)
    monkeypatch.setattr(main, "send_typing_indicator", nothing)
    monkeypatch.setattr(main, "get_user_profile", nothing)
    monkeypatch.setattr(customer_memory, "sync_to_github", nothing)
    monkeypatch.setattr(settings, "AI_MODEL_ORDER", ["mistral"])
    monkeypatch.setattr(main.ai_engine, "_providers", {"mistral": provider})

    asyncio.run(main.process_message(customer_id, "Bé nhà mình 3 tuổi, trường nhận chưa ạ?"))

    assert provider.rejected == 1
    assert waited == [1.5]
    assert sent == [REPLY]
    assert customer_memory.get_profile(customer_id)["kid_age"] == "3 tuổi"

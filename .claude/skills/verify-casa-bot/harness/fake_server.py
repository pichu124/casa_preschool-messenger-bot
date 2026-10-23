"""Local stand-in for every outside service the bot calls (stdlib only).

launcher.py rewrites https://<host>/<path> to http://127.0.0.1:<port>/<host>/<path>, so the first path segment
here is the real host. Every request is appended to the outbox (JSONL) with the response it got. Answers follow
the scenario file, re-read on every request (edit it or run `ctl.py scenario` while the app runs).

    python3 fake_server.py --port N --outbox FILE --scenario FILE --github-dir DIR --run-id ID [--github-file PATH=FILE ...]
"""
import argparse
import base64
import hashlib
import itertools
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

# First words of each system prompt in app/ai_engine.py; anything else is the parent-facing reply.
AI_KINDS = (
    ("Bạn là hệ thống trích xuất", "extract"),
    ("Bạn là nhân viên tư vấn trường mầm non Casa", "format_admin_reply"),
    ("Bạn là hệ thống phân loại", "classify"),
    ("Bạn là hệ thống tóm tắt", "summarize"),
)
GEMINI_PATH = re.compile(r"/v1beta/models/([^/:]+):generateContent")
AI_DEFAULTS = {
    "chat": "Dạ Casa chào Ba/Mẹ ạ, em hỗ trợ ngay ạ.",
    "extract": {},
    "classify": {"category": "Khác", "keywords": ["kiểm chứng"], "similar_questions": []},
    "summarize": "Phụ huynh hỏi thông tin chung về trường.",
}

args = None
lock = threading.Lock()
seq = itertools.count(1)
msg_ids = itertools.count(5001)
github_files: dict[str, bytes] = {}


def scenario() -> dict:
    try:
        return json.loads(Path(args.scenario).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _between(text: str, start: str, end: str) -> str:
    """What the parent wrote, cut out of the prompt app/ai_engine.py builds around it."""
    i = text.find(start)
    if i < 0:
        return text
    return text[i + len(start):].split(end, 1)[0].strip()


def openai_prompt(body: dict) -> tuple[str, str]:
    """(system prompt, last message) of an OpenAI-style chat completion request."""
    messages = body.get("messages") or []
    system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
    return system, messages[-1].get("content", "") if messages else ""


def _text(content: dict) -> str:
    return "".join(p.get("text", "") for p in (content or {}).get("parts") or [])


def gemini_prompt(body: dict) -> tuple[str, str]:
    """(systemInstruction, last content) of a Gemini REST generateContent request (google-genai)."""
    contents = body.get("contents") or []
    return _text(body.get("systemInstruction")), _text(contents[-1]) if contents else ""


def ai_reply(system: str, last: str) -> tuple[str, str, str | None]:
    """(kind, completion text, matching rule's `contains`) for a model call with this system prompt and message."""
    kind = next((k for prefix, k in AI_KINDS if system.startswith(prefix)), "chat")
    if kind == "chat":
        subject = _between(last, "[Phụ huynh hỏi]:", "[NHẮC NHỞ").removeprefix("[FIRST_MESSAGE]").strip()
    elif kind == "extract":
        subject = _between(last, "Tin nhắn phụ huynh:", "\nThông tin đã biết")
    else:
        subject = last
    sc = scenario()
    for rule in sc.get("rules", []):
        if rule.get("kind", "chat") == kind and rule.get("contains", "") in subject:
            reply, matched = rule["reply"], rule.get("contains", "")
            break
    else:
        reply, matched = (sc.get("defaults") or {}).get(kind, AI_DEFAULTS.get(kind)), None
        if kind == "format_admin_reply" and reply is None:
            reply = "Dạ, " + _between(last, "Câu trả lời từ admin:", "\n") + " ạ."
    text = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
    return kind, text, matched


def completion(text: str, model: str) -> dict:
    return {
        "id": "chatcmpl-fake",
        "object": "chat.completion",
        "created": 1,
        "model": model or "fake",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def gemini_response(text: str, model: str) -> dict:
    return {
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP", "index": 0}],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
        "modelVersion": model,
    }


def _sha(content: bytes) -> str:
    return hashlib.sha1(content).hexdigest()


def github(method: str, path: str, accept: str, body) -> tuple[int, object]:
    fail = scenario().get("fail") or {}
    stored = github_files.get(path)
    if method == "PUT":
        if fail.get("github_put"):
            return 500, {"message": "fake_server: github_put failure from scenario"}
        sha = (body or {}).get("sha")
        if stored is not None and sha != _sha(stored):  # like GitHub: the PUT must name the current version
            return 409, {"message": f"{path.rsplit('/', 1)[-1]} does not match {sha}"}
        content = base64.b64decode((body or {}).get("content", ""))
        github_files[path] = content
        out = Path(args.github_dir) / path.lstrip("/")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        return 200, {"content": {"sha": _sha(content)}}
    if "raw" in accept:
        return (200, stored) if stored is not None else (404, {"message": "Not Found"})
    if stored is None:
        return 200, {"sha": "fake-sha-initial", "content": ""}
    return 200, {"sha": _sha(stored), "encoding": "base64", "content": base64.encodebytes(stored).decode()}


def route(method: str, host: str, path: str, headers, body) -> tuple[int, object, dict]:
    """(status, response body: dict or bytes, extra fields for the outbox record)."""
    sc = scenario()
    fail = sc.get("fail") or {}
    if path.endswith("/chat/completions"):
        model = (body or {}).get("model")
        kind, text, rule = ai_reply(*openai_prompt(body or {}))
        if fail.get("openai"):
            return 500, {"error": {"message": "fake_server: openai failure from scenario"}}, {"kind": kind, "model": model}
        return 200, completion(text, model), {"kind": kind, "rule": rule, "model": model}
    gemini = GEMINI_PATH.fullmatch(path) if host == "generativelanguage.googleapis.com" else None
    if gemini:
        model = gemini.group(1)
        kind, text, rule = ai_reply(*gemini_prompt(body or {}))
        return 200, gemini_response(text, model), {"kind": kind, "rule": rule, "model": model}
    if host == "graph.facebook.com":
        if method == "GET":  # get_user_profile: /v21.0/<psid>?fields=first_name,last_name
            return 200, sc.get("fb_profile") or {"first_name": "Test", "last_name": "Parent"}, {}
        if path.endswith("/messenger_profile"):
            return 200, {"result": "success"}, {}
        if path.endswith("/messages"):
            recipient = ((body or {}).get("recipient") or {}).get("id")
            if "sender_action" in (body or {}):
                return 200, {"recipient_id": recipient}, {}
            if fail.get("graph_send"):
                err = {"message": "(#10) This message is sent outside of allowed window.", "code": 10}
                return 400, {"error": err}, {}
            return 200, {"recipient_id": recipient, "message_id": f"m_fake_{next(msg_ids)}"}, {}
    if host == "api.telegram.org":
        if fail.get("telegram"):
            return 500, {"ok": False, "description": "fake_server: telegram failure from scenario"}, {}
        if path.endswith("/sendMessage"):
            if fail.get("telegram_reply") and "reply_parameters" in (body or {}):  # replied-to message deleted
                return 400, {"ok": False, "error_code": 400, "description": "Bad Request: message to be replied not found"}, {}
            return 200, {"ok": True, "result": {"message_id": next(msg_ids)}}, {}
        return 200, {"ok": True, "result": True, "description": "fake"}, {}
    if host == "script.google.com":
        mode = fail.get("sheet", "ok")
        if mode == "false":
            return 200, {"ok": False, "error": "bad token"}, {}
        if mode == "500":
            return 500, b"<html>fake Apps Script error</html>", {}
        return 200, {"ok": True}, {}
    if host == "api.github.com":
        code, out = github(method, path, headers.get("accept", ""), body)
        return code, out, {}
    return 502, {"error": f"fake_server: unexpected host {host}"}, {"unexpected": True}


def _cut(text: str) -> str:
    return text if len(text) <= 200 else text[:200] + f"…({len(text)} chars)"


def _for_outbox(body):
    """Keep the outbox readable: system prompts (the whole Q&A database) and base64 file uploads are cut."""
    if not isinstance(body, dict):
        return body
    body = dict(body)
    if isinstance(body.get("messages"), list):
        body["messages"] = [
            {**m, "content": _cut(m["content"])} if m.get("role") == "system" and isinstance(m.get("content"), str) else m
            for m in body["messages"]
        ]
    system = body.get("systemInstruction")
    if isinstance(system, dict) and isinstance(system.get("parts"), list):
        parts = [{**p, "text": _cut(p["text"])} if isinstance(p.get("text"), str) else p for p in system["parts"]]
        body["systemInstruction"] = {**system, "parts": parts}
    if isinstance(body.get("content"), str) and len(body["content"]) > 200:
        body["content"] = f"<base64, {len(body['content'])} chars>"
    return body


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _handle(self):
        if self.path == "/__fake/health":
            return self._send(200, {"run_id": args.run_id})
        n = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(n) if n else b""
        if self.path.startswith("/__fake/github-commit?"):  # someone else commits the file (manual edit, other instance)
            path = parse_qs(urlsplit(self.path).query)["path"][0]
            github_files[path] = raw
            return self._send(200, {"path": path, "sha": _sha(raw)})
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = raw.decode("utf-8", "replace")
        parts = urlsplit(self.path)
        host, _, rest = parts.path.lstrip("/").partition("/")
        path = "/" + rest
        headers = {k.lower(): v for k, v in self.headers.items()}
        code, out, extra = route(self.command, host, path, headers, body)
        rec = {
            "method": self.command,
            "host": host,
            "path": path,
            "query": {k: v[0] for k, v in parse_qs(parts.query).items()},
            "authorization": headers.get("authorization"),
            "body": _for_outbox(body),
            "status": code,
            "response": out if isinstance(out, dict) else out.decode("utf-8", "replace"),
            **extra,
        }
        with lock:
            rec = {"seq": next(seq), **rec}
            with open(args.outbox, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._send(code, out)

    def _send(self, code, out):
        data = out if isinstance(out, bytes) else json.dumps(out, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json" if not isinstance(out, bytes) else "text/html")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _handle


def main():
    global args
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--outbox", required=True)
    p.add_argument("--scenario", required=True)
    p.add_argument("--github-dir", required=True)
    p.add_argument("--run-id", required=True)
    p.add_argument("--github-file", action="append", default=[], metavar="PATH=FILE",
                   help="serve FILE as GitHub contents PATH (/repos/<owner>/<repo>/contents/<path>) until a PUT replaces it")
    args = p.parse_args()
    for spec in args.github_file:
        path, _, file = spec.partition("=")
        github_files[path] = Path(file).read_bytes()
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

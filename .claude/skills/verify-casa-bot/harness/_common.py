"""Shared by ctl.py, send_event.py and read_back.py (stdlib only): where a run lives and how to talk to it."""
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
# Outside every repo on purpose: app/config.py calls load_dotenv(), which walks up from the copy looking for .env.
RUN_ROOT = Path(os.environ.get("CASA_VERIFY_ROOT") or Path(tempfile.gettempdir()) / "casa-verify")
MARKER = ".casa-verify-run"


def run_dir(slug: str) -> Path:
    return RUN_ROOT / slug


def load_state(slug: str) -> dict:
    path = run_dir(slug) / "state.json"
    if not path.exists():
        sys.exit(f"no run '{slug}' ({path} missing): start it with ctl.py up --slug {slug}")
    return json.loads(path.read_text(encoding="utf-8"))


def http(method: str, url: str, body: bytes | None = None, headers: dict | None = None, timeout: float = 30):
    """(status, body bytes) without raising on HTTP errors."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def outbox(state: dict) -> list[dict]:
    path = Path(state["outbox"])
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def wait_quiet(state: dict, start: int, quiet: float = 1.5, timeout: float = 30) -> list[dict]:
    """Outbound records after index `start`, once the app has sent nothing new for `quiet` seconds."""
    deadline = time.time() + timeout
    seen, last_change = len(outbox(state)), time.time()
    while time.time() < deadline:
        time.sleep(0.25)
        n = len(outbox(state))
        if n != seen:
            seen, last_change = n, time.time()
        elif time.time() - last_change >= quiet and n > start:
            break
        elif time.time() - last_change >= quiet * 3:
            break  # nothing went out at all (referral, echo, ignored event)
    return outbox(state)[start:]


def summarize(rec: dict) -> str | None:
    """One line per outbound request a verifier cares about; None for noise (typing indicator, profile lookup)."""
    host, body, method = rec["host"], rec.get("body"), rec["method"]
    seq = f"#{rec['seq']:<3} {rec['status']}"
    if host == "graph.facebook.com":
        if isinstance(body, dict) and "sender_action" in body:
            return None
        if method == "GET":
            return None
        if rec["path"].endswith("/messenger_profile"):
            return f"{seq} FB  messenger_profile {json.dumps(body, ensure_ascii=False)}"
        msg = (body or {}).get("message", {})
        to = (body or {}).get("recipient", {}).get("id")
        if "attachment" in msg:
            what = "IMAGE " + msg["attachment"]["payload"]["url"]
        else:
            what = "TEXT " + json.dumps(msg.get("text", ""), ensure_ascii=False)
        qr = msg.get("quick_replies")
        if qr:
            what += " QUICK=" + json.dumps(
                [q.get("payload") or q["content_type"] for q in qr], ensure_ascii=False
            )
        return f"{seq} FB  to={to} {what}"
    if host == "api.telegram.org":
        if rec["path"].endswith("/sendMessage"):
            mid = (rec.get("response") or {}).get("result", {}).get("message_id")
            first = (body or {}).get("text", "").split("\n", 1)[0]
            reply_to = ((body or {}).get("reply_parameters") or {}).get("message_id")
            reply = f" reply_to={reply_to}" if reply_to else ""
            return f"{seq} TG  sendMessage message_id={mid}{reply} header={first!r}"
        return f"{seq} TG  {rec['path']} {json.dumps(body, ensure_ascii=False)}"
    if host == "script.google.com" and (body or {}).get("type") == "media":
        files = (rec.get("response") or {}).get("files") if isinstance(rec.get("response"), dict) else None
        listed = f" files={len(files)}" if isinstance(files, list) else ""
        return f"{seq} SHEET {json.dumps({k: body.get(k) for k in ('type', 'token')}, ensure_ascii=False)}{listed}"
    if host in ("drive.google.com", "drive.usercontent.google.com"):
        file_id = (rec.get("query") or {}).get("id")
        what = rec.get("location") or rec.get("response")
        return f"{seq} DRIVE {method} {host}{rec['path']} id={file_id} -> {what}"
    if host == "script.google.com":
        keys = ("event", "customer_id", "phone", "visit_request", "stage", "token")
        if (body or {}).get("type") == "topic":
            keys = ("type", "customer_id", "topics", "escalated", "question", "token")
        return f"{seq} SHEET {json.dumps({k: (body or {}).get(k) for k in keys}, ensure_ascii=False)}"
    if host == "api.github.com":
        return f"{seq} GH  {method} {rec['path']}"
    if rec.get("kind"):
        return f"{seq} AI  {rec['kind']} rule={rec.get('rule')!r} model={rec.get('model')}"
    return f"{seq} ??  {method} {host}{rec['path']} (unexpected host)"

"""Send what Facebook or Telegram would send to the running bot, then print what the bot sent out because of it.

    python3 send_event.py [--slug S] text PSID "Xin chào" [--referral ADS --ad-id A1 --ad-title T --ref R]
    python3 send_event.py quick PSID QR:age:1 [--text "2-3 tuổi"]   # text quick reply button
    python3 send_event.py phone PSID 0912345678                      # Messenger's phone quick reply
    python3 send_event.py postback PSID GET_STARTED|IB_1..IB_4 [--title T] [--referral ADS ...]
    python3 send_event.py referral PSID --referral ADS|SHORTLINK [--ad-id ..] [--ad-title ..] [--ref ..]
    python3 send_event.py echo PSID "staff text" [--bot]             # Page inbox echo (--bot: the bot's own)
    python3 send_event.py raw FILE.json                              # one messaging event or a whole body
    python3 send_event.py tg-reply "admin answer" [--to TG_MSG_ID] [--quote ORIGINAL_TEXT]

Webhook bodies are signed with the run's FB_APP_SECRET like Facebook does (--bad-signature / --no-signature to
test the refusal). --mid reuses a message id (dedup). Output: the HTTP answer, then one line per outbound request
the event caused (typing indicators and profile lookups hidden; --full prints whole outbox records).
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import uuid
from pathlib import Path

from _common import http, load_state, outbox, summarize, wait_quiet

ESCALATION_HEADER = "⚠️ CẦN TRỢ GIÚP ⚠️"  # app/escalation.py


def referral(a) -> dict | None:
    if not a.referral:
        return None
    ref = {"source": a.referral, "type": "OPEN_THREAD"}
    if a.ad_id:
        ref["ad_id"] = a.ad_id
    if a.ad_title:
        ref["ads_context_data"] = {"ad_title": a.ad_title}
    if a.ref:
        ref["ref"] = a.ref
    return ref


def messaging_event(a) -> dict:
    now = int(time.time() * 1000)
    mid = a.mid or f"m_verify_{uuid.uuid4().hex[:12]}"
    event = {"sender": {"id": a.psid}, "recipient": {"id": "PAGE_ID"}, "timestamp": now}
    if a.cmd == "text":
        event["message"] = {"mid": mid, "text": a.text}
    elif a.cmd == "quick":
        event["message"] = {"mid": mid, "text": a.text or a.payload, "quick_reply": {"payload": a.payload}}
    elif a.cmd == "phone":
        event["message"] = {"mid": mid, "text": a.number, "quick_reply": {"payload": a.number}}
    elif a.cmd == "postback":
        event["postback"] = {"mid": mid, "payload": a.payload, "title": a.title or a.payload}
    elif a.cmd == "echo":
        event = {"sender": {"id": "PAGE_ID"}, "recipient": {"id": a.psid}, "timestamp": now,
                 "message": {"mid": mid, "text": a.text, "is_echo": True, "app_id": 1}}
        if a.bot:
            event["message"]["metadata"] = "casa-bot"
    ref = referral(a) if a.cmd in ("text", "postback", "referral") else None
    if ref and a.cmd == "postback":
        event["postback"]["referral"] = ref
    elif ref:
        event["referral"] = ref
    return event


def post_webhook(state: dict, body: dict, a):
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"content-type": "application/json"}
    if not a.no_signature:
        key = b"wrong-secret" if a.bad_signature else state["app_secret"].encode()
        headers["X-Hub-Signature-256"] = "sha256=" + hmac.new(key, raw, hashlib.sha256).hexdigest()
    return http("POST", state["app_url"] + "/webhook", raw, headers)


def last_escalation(state: dict) -> tuple[int, str]:
    for rec in reversed(outbox(state)):
        text = (rec.get("body") or {}).get("text", "") if isinstance(rec.get("body"), dict) else ""
        if rec["host"] == "api.telegram.org" and text.startswith(ESCALATION_HEADER):
            return rec["response"]["result"]["message_id"], text
    sys.exit("no escalation in the outbox yet: send a message the scenario answers with [ESCALATE] first")


def post_telegram(state: dict, a):
    if a.to:
        to, quote = a.to, a.quote or ""
    else:
        to, quote = last_escalation(state)
        quote = a.quote if a.quote is not None else quote
    update = {
        "update_id": int(time.time()),
        "message": {
            "message_id": a.message_id or int(time.time() * 1000) % 10**9,
            "chat": {"id": int(state["telegram_chat_id"]), "type": "supergroup"},
            "from": {"id": 42, "is_bot": False, "first_name": "Admin"},
            "date": int(time.time()),
            "text": a.text,
            "reply_to_message": {"message_id": to, "text": quote, "from": {"id": 1, "is_bot": True}},
        },
    }
    secret = "wrong-secret" if a.bad_secret else state["secret"]
    raw = json.dumps(update, ensure_ascii=False).encode("utf-8")
    headers = {"content-type": "application/json", "X-Telegram-Bot-Api-Secret-Token": secret}
    return http("POST", state["app_url"] + "/telegram-webhook", raw, headers, timeout=60)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--slug", default=None)
    p.add_argument("--no-wait", action="store_true", help="do not wait for outbound requests")
    p.add_argument("--full", action="store_true", help="print whole outbox records")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, *positional):
        sp = sub.add_parser(name)
        sp.add_argument("--slug", default=argparse.SUPPRESS)
        for arg in positional:
            sp.add_argument(arg)
        if name not in ("tg-reply", "raw"):
            sp.add_argument("--mid")
        if name != "tg-reply":
            sp.add_argument("--bad-signature", action="store_true")
            sp.add_argument("--no-signature", action="store_true")
        return sp

    for name, pos in (("text", ("psid", "text")), ("postback", ("psid", "payload")), ("referral", ("psid",))):
        sp = add(name, *pos)
        sp.add_argument("--referral", required=name == "referral", help="ADS or SHORTLINK (others: organic)")
        sp.add_argument("--ad-id")
        sp.add_argument("--ad-title")
        sp.add_argument("--ref")
        if name == "postback":
            sp.add_argument("--title")
    add("quick", "psid", "payload").add_argument("--text")
    add("phone", "psid", "number")
    add("echo", "psid", "text").add_argument("--bot", action="store_true")
    add("raw", "file")
    tg = add("tg-reply", "text")
    tg.add_argument("--to", type=int, help="Telegram message_id replied to (default: last escalation)")
    tg.add_argument("--quote", help="text of the replied-to message (default: that escalation's text)")
    tg.add_argument("--message-id", type=int, help="this reply's message_id (reuse to test dedup)")
    tg.add_argument("--bad-secret", action="store_true")
    a = p.parse_args()

    state = load_state(a.slug or os.environ.get("CASA_VERIFY_SLUG", "default"))
    start = len(outbox(state))
    if a.cmd == "tg-reply":
        code, body = post_telegram(state, a)
    elif a.cmd == "raw":
        data = json.loads(Path(a.file).read_text(encoding="utf-8"))
        if "object" not in data:
            data = {"object": "page", "entry": [{"id": "PAGE_ID", "time": int(time.time() * 1000), "messaging": [data]}]}
        code, body = post_webhook(state, data, a)
    else:
        event = messaging_event(a)
        body_json = {"object": "page", "entry": [{"id": "PAGE_ID", "time": event["timestamp"], "messaging": [event]}]}
        code, body = post_webhook(state, body_json, a)
    print(f"SENT {a.cmd} -> HTTP {code} {body.decode('utf-8', 'replace')[:300]}")
    if a.no_wait:
        return
    for rec in wait_quiet(state, start):
        line = json.dumps(rec, ensure_ascii=False) if a.full else summarize(rec)
        if line:
            print("  " + line)


if __name__ == "__main__":
    main()

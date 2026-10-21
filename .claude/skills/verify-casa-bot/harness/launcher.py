"""Runs app.main:app with no way out to the internet. Started by ctl.py up (env -i, cwd = the copy); not by hand.

1. Refuses to start with a real-looking GitHub token, GH_TOKEN, a proxy variable (httpx would use it), or a .env
   the app's load_dotenv() could find.
2. Blocks DNS to anything but loopback and TCP connects to anything but the fake and the app itself (a proxy on
   loopback would be a way out; logged to CASA_VERIFY_NETLOG).
3. Rewrites every httpx request (Graph, Telegram, Sheet, GitHub, OpenAI SDK) to the fake server.
4. Uses the asyncio loop: uvloop connects in C, past the socket guard.
5. app.followup._now_utc reads "now_utc" from the scenario file when set (the clock is outside the system).
"""
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

FAKE_PORT = int(os.environ["CASA_VERIFY_FAKE_PORT"])
APP_PORT = int(os.environ["CASA_VERIFY_APP_PORT"])
NETLOG = os.environ["CASA_VERIFY_NETLOG"]
SCENARIO = os.environ["CASA_VERIFY_SCENARIO"]
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
ALLOWED_PORTS = {FAKE_PORT, APP_PORT}


def netlog(line: str):
    with open(NETLOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")


def refuse(why: str):
    netlog(f"REFUSED START: {why}")
    sys.exit(f"launcher: refusing to start: {why}")


proxies = sorted(k for k in os.environ if k.upper().endswith("_PROXY") and k.upper() != "NO_PROXY")
if proxies:
    refuse(f"{', '.join(proxies)} set: httpx would send requests to that proxy")
if "GH_TOKEN" in os.environ or "GITHUB_PAT" in os.environ:
    refuse("GH_TOKEN/GITHUB_PAT is set (the environment must come from env -i)")
if not os.environ.get("GITHUB_TOKEN", "").startswith("fake-"):
    refuse("GITHUB_TOKEN must be a fake-… value")
if os.environ.get("GEMINI_API_KEY"):
    refuse("GEMINI_API_KEY is set: google-generativeai talks gRPC, which bypasses the httpx rewrite")
for d in [Path.cwd(), *Path.cwd().parents]:
    if (d / ".env").exists():
        refuse(f"{d / '.env'} exists: app/config.py load_dotenv() would read real secrets from it")

_getaddrinfo = socket.getaddrinfo
_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex


def _loopback(host) -> bool:
    return str(host) in LOOPBACK or str(host).startswith("127.")


def guarded_getaddrinfo(host, *a, **k):
    if host is not None and not _loopback(host.decode() if isinstance(host, bytes) else host):
        netlog(f"BLOCKED dns {host}")
        raise socket.gaierror(f"casa-verify: DNS for {host} blocked")
    return _getaddrinfo(host, *a, **k)


def _check(addr):
    if isinstance(addr, tuple) and not (_loopback(addr[0]) and addr[1] in ALLOWED_PORTS):
        netlog(f"BLOCKED connect {addr}")
        raise OSError(f"casa-verify: connect to {addr} blocked")


def guarded_connect(self, addr):
    _check(addr)
    return _connect(self, addr)


def guarded_connect_ex(self, addr):
    _check(addr)
    return _connect_ex(self, addr)


socket.getaddrinfo = guarded_getaddrinfo
socket.socket.connect = guarded_connect
socket.socket.connect_ex = guarded_connect_ex

import httpx  # after the socket guard on purpose

_send = httpx.Client.send
_asend = httpx.AsyncClient.send


def rewrite(request: httpx.Request):
    url = request.url
    if _loopback(url.host):
        return
    query = "?" + url.query.decode() if url.query else ""
    netlog(f"rewrite {request.method} {url.host}{url.path}")
    request.url = httpx.URL(f"http://127.0.0.1:{FAKE_PORT}/{url.host}{url.path}{query}")


def send(self, request, **kwargs):
    rewrite(request)
    return _send(self, request, **kwargs)


async def asend(self, request, **kwargs):
    rewrite(request)
    return await _asend(self, request, **kwargs)


httpx.Client.send = send
httpx.AsyncClient.send = asend

sys.path.insert(0, os.getcwd())
import uvicorn

from app import followup
from app.main import app

_real_now = followup._now_utc


def scenario_now():
    try:
        value = json.loads(Path(SCENARIO).read_text(encoding="utf-8")).get("now_utc")
    except (OSError, ValueError):
        value = None
    if not value:
        return _real_now()
    moment = datetime.fromisoformat(value)
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


followup._now_utc = scenario_now
netlog(f"start app on 127.0.0.1:{APP_PORT}, fake on 127.0.0.1:{FAKE_PORT}")
uvicorn.run(app, host="127.0.0.1", port=APP_PORT, loop="asyncio", log_level="info")

"""Start, check and stop one isolated instance of the bot (stdlib only; run with any python3).

    python3 ctl.py up      [--slug S] [--source DIR] [--scenario FILE] [--env KEY=VALUE ...]
    python3 ctl.py doctor  [--slug S]
    python3 ctl.py env     [--slug S]          # shell exports: eval "$(python3 ctl.py env --slug S)"
    python3 ctl.py scenario [--slug S] FILE    # swap the fake's scripted answers while running
    python3 ctl.py down    [--slug S]

up copies the source working tree (tracked + untracked, not ignored; never .env or data/customers.json) to
$TMPDIR/casa-verify/<slug>/app, starts fake_server.py and launcher.py there under `env -i` with fake secrets,
and waits until the app answers as usable. Evidence goes to <source>/artifacts/verify/<slug>/.
"""
import argparse
import hashlib
import json
import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from _common import HARNESS_DIR, MARKER, RUN_ROOT, http, load_state, outbox, run_dir

# Runtime files the app writes under data/: never copied in (real parents' data), always copied out on down.
DATA_FILES = ("customers.json", "analytics.jsonl", "pending_escalations.json", "escalation_log.json")
FORBIDDEN_ENV = ("GH_TOKEN", "GITHUB_PAT")


def git(source: Path, *cmd) -> str:
    return subprocess.run(["git", "-C", str(source), *cmd], check=True, capture_output=True, text=True).stdout


def source_files(source: Path) -> list[str]:
    out = git(source, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    files = []
    for f in sorted(set(filter(None, out.split("\0")))):
        name = Path(f).name
        if name.startswith(".env") or f.startswith(("artifacts/", ".claude/worktrees/")):
            continue
        if f.startswith("data/") and name in DATA_FILES:
            continue
        if (source / f).is_file():
            files.append(f)
    return files


def fingerprint(root: Path, files: list[str]) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update(f.encode() + b"\0" + (root / f).read_bytes() + b"\0")
    return h.hexdigest()[:16]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def app_python(source: Path) -> str:
    candidates = [source / ".venv/bin/python"]
    try:
        common = git(source, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        candidates.append(Path(common).parent / ".venv/bin/python")
    except subprocess.CalledProcessError:
        pass
    candidates += [Path(p) for p in (shutil.which("python3"), shutil.which("python")) if p]
    for c in candidates:
        probe = [str(c), "-c", "import fastapi, uvicorn, httpx, openai"]
        if c.exists() and subprocess.run(probe, capture_output=True).returncode == 0:
            return str(c)
    sys.exit("no Python with fastapi/uvicorn/httpx/openai: python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    return not (stat.exists() and stat.read_text().split(")")[-1].split()[0] == "Z")


def environ(pid: int) -> dict | None:
    path = Path(f"/proc/{pid}/environ")
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    return dict(kv.split("=", 1) for kv in raw.decode(errors="replace").split("\0") if "=" in kv)


def ours(pid: int, state: dict) -> bool:
    """pid still runs one of this run's processes (pids get reused): both carry CASA_VERIFY_RUN_ID."""
    if not alive(pid):
        return False
    env = environ(pid)
    return env is None or env.get("CASA_VERIFY_RUN_ID") == state["run_id"]  # None: no /proc (macOS)


def is_proxy(key: str) -> bool:
    """HTTP_PROXY, https_proxy, ALL_PROXY, …: httpx would send the app's requests there (NO_PROXY is harmless)."""
    return key.upper().endswith("_PROXY") and key.upper() != "NO_PROXY"


def app_env(state: dict, overrides: dict) -> dict:
    rid = state["run_id"]
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(Path(state["run_dir"]) / "home"),
        "LANG": "C.UTF-8",
        "TZ": "UTC",  # as on Render: history timestamps are naive datetime.now(), app/followup.py reads them as UTC
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "CASA_VERIFY_RUN_ID": rid,
        "CASA_VERIFY_FAKE_PORT": str(state["fake_port"]),
        "CASA_VERIFY_APP_PORT": str(state["app_port"]),
        "CASA_VERIFY_NETLOG": state["netlog"],
        "CASA_VERIFY_SCENARIO": state["scenario"],
        # Every setting in app/config.py, so load_dotenv() has nothing left to fill in.
        "FB_PAGE_ACCESS_TOKEN": f"fake-page-token-{rid}",
        "FB_VERIFY_TOKEN": state["verify_token"],
        "FB_APP_SECRET": state["app_secret"],
        "TELEGRAM_BOT_TOKEN": f"000000:fake-telegram-{rid}",
        "TELEGRAM_CHAT_ID": "-1000000000000",
        "TELEGRAM_WEBHOOK_SECRET": state["secret"],
        "LEADS_SHEET_WEBHOOK_URL": "https://script.google.com/macros/s/FAKE/exec",
        "LEADS_SHEET_TOKEN": f"fake-sheet-token-{rid}",
        "FOLLOWUP_ENABLED": "false",
        "GITHUB_TOKEN": f"fake-github-token-{rid}",
        "CUSTOMERS_GITHUB_REPO": "fake-owner/fake-private-customers",
        "OPENAI_API_KEY": f"fake-openai-key-{rid}",
        "GROQ_API_KEY": "",
        "MISTRAL_API_KEY": "",
        "DEEPSEEK_API_KEY": "",
        "GEMINI_API_KEY": "",
        "AI_MODEL_ORDER": "openai",
        "PUBLIC_BASE_URL": state["app_url"],
    }
    for key, value in overrides.items():
        if key in FORBIDDEN_ENV or key.startswith("CASA_VERIFY_") or is_proxy(key):
            sys.exit(f"--env {key} is not allowed")
        if key == "GITHUB_TOKEN" and not value.startswith("fake-"):
            sys.exit("--env GITHUB_TOKEN must start with fake-")
        if key == "GEMINI_API_KEY" and value:
            sys.exit("--env GEMINI_API_KEY: gemini talks gRPC, past the fake; not supported")
        env[key] = value
    return env


def ready(state: dict) -> str | None:
    """None when the app is usable (answers health with Q&A loaded and verifies the webhook), else why not."""
    try:
        code, body = http("GET", f"http://127.0.0.1:{state['fake_port']}/__fake/health", timeout=2)
        if code != 200 or json.loads(body).get("run_id") != state["run_id"]:
            return f"fake server on port {state['fake_port']} is not this run's"
        code, body = http("GET", state["app_url"] + "/", timeout=2)
        health = json.loads(body)
        if code != 200 or health.get("status") != "ok" or not health.get("qa_pairs"):
            return f"GET / -> {code} {health}"
        q = f"hub.mode=subscribe&hub.verify_token={state['verify_token']}&hub.challenge={state['run_id']}"
        code, body = http("GET", f"{state['app_url']}/webhook?{q}", timeout=2)
        if code != 200 or body.decode() != state["run_id"]:
            return f"GET /webhook verify -> {code} {body[:100]!r}"
    except (OSError, ValueError) as e:
        return f"{type(e).__name__}: {e}"
    return None


def stop(state: dict):
    for name in ("app_pid", "fake_pid"):
        pid = state.get(name)
        if not pid or not alive(pid) or not ours(pid, state):
            continue
        os.kill(pid, signal.SIGTERM)
        for _ in range(40):
            if not alive(pid):
                break
            time.sleep(0.25)
        else:
            os.kill(pid, signal.SIGKILL)
        print(f"stopped {name.removesuffix('_pid')} (pid {pid})")


def cmd_up(a):
    source = Path(a.source or git(Path.cwd(), "rev-parse", "--show-toplevel").strip()).resolve()
    rd = run_dir(a.slug)
    if (rd / "state.json").exists():
        old = load_state(a.slug)
        if any(old.get(k) and alive(old[k]) and ours(old[k], old) for k in ("app_pid", "fake_pid")):
            sys.exit(f"run '{a.slug}' is already up: ctl.py doctor / ctl.py down --slug {a.slug}")
    if rd.exists():
        if not (rd / MARKER).exists():
            sys.exit(f"{rd} exists and is not a casa-verify run dir; not touching it")
        shutil.rmtree(rd)
    for d in [source, *source.parents]:
        if rd.is_relative_to(d) and (d / ".env").exists():
            sys.exit(f"run dir {rd} is under {d}, which has .env: set CASA_VERIFY_ROOT outside it")
    copy = rd / "app"
    copy.mkdir(parents=True)
    (rd / MARKER).write_text(str(source) + "\n")
    (rd / "home").mkdir()
    files = source_files(source)
    for f in files:
        (copy / f).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / f, copy / f)
    (copy / "data").mkdir(exist_ok=True)
    (copy / "data" / "customers.json").write_text("{}\n", encoding="utf-8")
    (copy / "static").mkdir(exist_ok=True)

    evidence = Path(a.evidence or source / "artifacts" / "verify" / a.slug).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    for name in ("outbox.jsonl", "netlog.txt", "app.log", "fake.log"):
        (evidence / name).write_text("")
    shutil.copy(a.scenario, rd / "scenario.json")

    run_id = secrets.token_hex(4)
    app_port, fake_port = free_port(), free_port()
    state = {
        "slug": a.slug,
        "run_id": run_id,
        "run_dir": str(rd),
        "copy": str(copy),
        "source": str(source),
        "source_commit": git(source, "rev-parse", "HEAD").strip(),
        "source_dirty": bool(git(source, "status", "--porcelain").strip()),
        "fingerprint": fingerprint(source, files),
        "app_port": app_port,
        "fake_port": fake_port,
        "app_url": f"http://127.0.0.1:{app_port}",
        "secret": f"fake-admin-{run_id}",
        "verify_token": f"fake-verify-{run_id}",
        "app_secret": f"fake-app-secret-{run_id}",
        "telegram_chat_id": "-1000000000000",
        "evidence": str(evidence),
        "outbox": str(evidence / "outbox.jsonl"),
        "netlog": str(evidence / "netlog.txt"),
        "app_log": str(evidence / "app.log"),
        "scenario": str(rd / "scenario.json"),
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    overrides = dict(kv.split("=", 1) for kv in a.env)
    env = app_env(state, overrides)
    py = app_python(source)
    state["python"] = py

    fake_cmd = ["/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "LANG=C.UTF-8", f"CASA_VERIFY_RUN_ID={run_id}", py, str(HARNESS_DIR / "fake_server.py"),
                "--port", str(fake_port), "--outbox", state["outbox"], "--scenario", state["scenario"],
                "--github-dir", str(evidence / "github"), "--run-id", run_id]
    with open(evidence / "fake.log", "ab") as log:
        state["fake_pid"] = subprocess.Popen(fake_cmd, stdout=log, stderr=log, start_new_session=True).pid
    app_cmd = ["/usr/bin/env", "-i", *[f"{k}={v}" for k, v in env.items()], py, str(HARNESS_DIR / "launcher.py")]
    with open(evidence / "app.log", "ab") as log:
        proc = subprocess.Popen(app_cmd, cwd=copy, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    state["app_pid"] = proc.pid
    (rd / "state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")

    why = "not started"
    for _ in range(160):
        if proc.poll() is not None:
            break
        why = ready(state)
        if why is None:
            break
        time.sleep(0.25)
    if why is not None:
        stop(state)
        tail = Path(state["app_log"]).read_text(encoding="utf-8", errors="replace")[-3000:]
        sys.exit(f"app not ready ({why}); app.log tail:\n{tail}")
    dirty = " (with uncommitted changes)" if state["source_dirty"] else ""
    print(f"READY {state['app_url']}  slug={a.slug} run_id={run_id}")
    print(f"  copy of {source} @ {state['source_commit'][:7]}{dirty} -> {copy}")
    print(f"  fake upstream http://127.0.0.1:{fake_port}  evidence -> {evidence}")


def cmd_doctor(a):
    state = load_state(a.slug)
    problems = []
    for name in ("app_pid", "fake_pid"):
        pid = state[name]
        if not (alive(pid) and ours(pid, state)):
            problems.append(f"{name} {pid} is not running")
    why = ready(state)
    if why:
        problems.append("not usable: " + why)
    env = environ(state["app_pid"])
    if env is not None:
        if any(k in env for k in FORBIDDEN_ENV):
            problems.append("app process has GH_TOKEN/GITHUB_PAT in its environment")
        if any(is_proxy(k) for k in env):
            problems.append("app process has a *_PROXY variable in its environment")
        if not env.get("GITHUB_TOKEN", "").startswith("fake-"):
            problems.append("app process GITHUB_TOKEN is not fake")
        if env.get("CASA_VERIFY_RUN_ID") != state["run_id"]:
            problems.append("app pid belongs to another run")
    blocked = [line for line in Path(state["netlog"]).read_text().splitlines() if "BLOCKED" in line]
    if blocked:
        problems.append(f"app tried to reach the internet {len(blocked)}x (netlog.txt): {blocked[-1]}")
    unexpected = [r for r in outbox(state) if r.get("unexpected")]
    if unexpected:
        problems.append(f"{len(unexpected)} request(s) to a host the fake does not know: {unexpected[-1]['host']}")
    source = Path(state["source"])
    now = fingerprint(source, source_files(source))
    build = "copy matches source working tree" if now == state["fingerprint"] else "STALE: source changed since up"
    if now != state["fingerprint"]:
        problems.append("copy is stale: ctl.py down && ctl.py up to test the current code")
    print(f"slug={state['slug']} run_id={state['run_id']} app={state['app_url']} (pid {state['app_pid']}) "
          f"fake=:{state['fake_port']} (pid {state['fake_pid']})")
    print(f"build: {state['source_commit'][:7]} dirty={state['source_dirty']} {build}")
    print(f"outbox: {len(outbox(state))} records; netlog blocked: {len(blocked)}")
    for p in problems:
        print("FAIL", p)
    print("DOCTOR OK" if not problems else "DOCTOR FAIL")
    sys.exit(1 if problems else 0)


def cmd_env(a):
    s = load_state(a.slug)
    for key, value in (("CASA_APP", s["app_url"]), ("CASA_SECRET", s["secret"]), ("CASA_VERIFY_TOKEN", s["verify_token"]),
                       ("CASA_COPY", s["copy"]), ("CASA_EVIDENCE", s["evidence"]), ("CASA_OUTBOX", s["outbox"])):
        print(f"export {key}='{value}'")


def cmd_scenario(a):
    s = load_state(a.slug)
    json.loads(Path(a.file).read_text(encoding="utf-8"))  # fail here, not inside the fake
    shutil.copy(a.file, s["scenario"])
    print(f"scenario {a.file} -> {s['scenario']} (fake reads it on every request)")


def cmd_down(a):
    state = load_state(a.slug)
    stop(state)
    copy, evidence = Path(state["copy"]), Path(state["evidence"])
    after = evidence / "data_after"
    after.mkdir(exist_ok=True)
    for name in (*DATA_FILES, "qa_database.json"):
        if (copy / "data" / name).exists():
            shutil.copy2(copy / "data" / name, after / name)
    rd = Path(state["run_dir"])
    if (rd / MARKER).exists() and rd.is_relative_to(RUN_ROOT):
        shutil.rmtree(rd)
        print(f"removed run dir {rd}")
    print(f"evidence kept in {evidence}:")
    for p in sorted(evidence.rglob("*")):
        if p.is_file():
            print(f"  {p.relative_to(evidence)} ({p.stat().st_size} B)")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("up", "doctor", "env", "scenario", "down"):
        sp = sub.add_parser(name)
        sp.add_argument("--slug", default=os.environ.get("CASA_VERIFY_SLUG", "default"))
        if name == "up":
            sp.add_argument("--source", help="repo or worktree to copy (default: git toplevel of cwd)")
            sp.add_argument("--evidence", help="default: <source>/artifacts/verify/<slug>")
            sp.add_argument("--scenario", default=str(HARNESS_DIR / "scenario.default.json"))
            sp.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
        if name == "scenario":
            sp.add_argument("file")
    a = p.parse_args()
    {"up": cmd_up, "doctor": cmd_doctor, "env": cmd_env, "scenario": cmd_scenario, "down": cmd_down}[a.cmd](a)


if __name__ == "__main__":
    main()

"""Read back what a run did: what went out, what was stored, what the app logged.

    python3 read_back.py [--slug S] outbox [--host fb|tg|sheet|gh|ai] [--since SEQ] [--full]
    python3 read_back.py [--slug S] profile PSID [--fields phone,kid_age] [--disk]
    python3 read_back.py [--slug S] log [--grep TEXT] [--tail N]

profile reads GET /customers?secret=… (the admin endpoint); --disk reads the copy's data/customers.json instead,
an independent second view of the same write.
"""
import argparse
import json
import os
import sys
from pathlib import Path

from _common import http, load_state, outbox, summarize

HOSTS = {
    "fb": "graph.facebook.com",
    "tg": "api.telegram.org",
    "sheet": "script.google.com",
    "gh": "api.github.com",
    "ai": "api.openai.com",
}


def cmd_outbox(state, a):
    for rec in outbox(state):
        if rec["seq"] <= a.since or (a.host and rec["host"] != HOSTS[a.host]):
            continue
        line = json.dumps(rec, ensure_ascii=False) if a.full else summarize(rec)
        if line:
            print(line)


def cmd_profile(state, a):
    if a.disk:
        customers = json.loads((Path(state["copy"]) / "data" / "customers.json").read_text(encoding="utf-8"))
    else:
        code, body = http("GET", f"{state['app_url']}/customers?secret={state['secret']}")
        if code != 200:
            sys.exit(f"GET /customers -> {code} {body[:200]!r}")
        customers = json.loads(body)["customers"]
    profile = customers.get(a.psid)
    if profile is None:
        sys.exit(f"no profile for {a.psid} ({len(customers)} profiles)")
    if a.fields:
        profile = {k: profile.get(k) for k in a.fields.split(",")}
    print(json.dumps(profile, ensure_ascii=False, indent=2))


def cmd_log(state, a):
    lines = Path(state["app_log"]).read_text(encoding="utf-8", errors="replace").splitlines()
    if a.grep:
        lines = [line for line in lines if a.grep in line]
    print("\n".join(lines[-a.tail:]))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--slug", default=os.environ.get("CASA_VERIFY_SLUG", "default"))
    sub = p.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("outbox")
    o.add_argument("--host", choices=sorted(HOSTS))
    o.add_argument("--since", type=int, default=0, help="only records with seq greater than this")
    o.add_argument("--full", action="store_true")
    pr = sub.add_parser("profile")
    pr.add_argument("psid")
    pr.add_argument("--fields")
    pr.add_argument("--disk", action="store_true")
    lg = sub.add_parser("log")
    lg.add_argument("--grep")
    lg.add_argument("--tail", type=int, default=40)
    a = p.parse_args()
    {"outbox": cmd_outbox, "profile": cmd_profile, "log": cmd_log}[a.cmd](load_state(a.slug), a)


if __name__ == "__main__":
    main()

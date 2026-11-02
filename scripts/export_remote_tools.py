#!/usr/bin/env python3
"""Export the remote MCP tool definitions that agent-gateway serves at /mcp, from mcp-server/server.py.

The remote server exposes 21 of the local stdio tools: 8 gift-card tools (key scope ACQUIRY),
8 bill-pay tools (PURCHASE) and the 5 transfer tools (ALL only). Scopes rank ACQUIRY < PURCHASE
< ALL; a grant may use a tool when its key scope is at least the tool's required_key_scope.
name, title, inputSchema and annotations are copied from server.py. The remote descriptions and
instructions are the local ones with the edits below, which drop what only applies to the local
server (snaplii_config_show, snaplii_connect, update notices, the autopilot prompt, the key-scope
note) and set the remote polling cadence for transfers. Each edit must match server.py exactly
once, so a local change to an edited sentence stops the export until the edit is updated.

server.py does not read the output. When its tools change, rerun this and commit the output to
agent-gateway src/main/resources/mcp/tools.json. --check fails when --out is out of date. Run from
the repo root (server.py needs the mcp package):

    uv run --python 3.12 --with "./snaplii-cli[dev]" --with ./mcp-server python scripts/export_remote_tools.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
# The source tree, not an installed (possibly stale) copy.
sys.path[:0] = [str(ROOT / "mcp-server"), str(ROOT / "snaplii-cli" / "src")]

import server  # noqa: E402

DEFAULT_OUT = ROOT / "build" / "remote-tools" / "tools.json"

GIFT_CARD_TOOLS = ("snaplii_balance", "snaplii_browse_tags", "snaplii_browse_brand", "snaplii_giftcard_list",
                   "snaplii_giftcard_detail", "snaplii_quote", "snaplii_purchase", "snaplii_cashback_calc")
BILL_PAY_TOOLS = ("snaplii_billpay_payees", "snaplii_billpay_detail", "snaplii_billpay_history",
                  "snaplii_billpay_save", "snaplii_billpay_vouchers", "snaplii_billpay_quote",
                  "snaplii_billpay_pay", "snaplii_billpay_result")
TRANSFER_TOOLS = ("snaplii_transfer_create", "snaplii_transfer_cancel", "snaplii_transfer_finish",
                  "snaplii_transfer_status", "snaplii_transfer_list")
REQUIRED_KEY_SCOPE = {**dict.fromkeys(GIFT_CARD_TOOLS, "ACQUIRY"), **dict.fromkeys(BILL_PAY_TOOLS, "PURCHASE"),
                      **dict.fromkeys(TRANSFER_TOOLS, "ALL")}
# Connecting and local-only views; the remote client connects through OAuth instead.
LOCAL_ONLY = {"snaplii_config_show", "snaplii_init", "snaplii_connect", "snaplii_submit_api_key",
              "snaplii_dashboard"}

_POLL_LIMIT = "stop after two minutes without a final status and tell the user to check again later"

DESCRIPTION_EDITS = {
    "snaplii_transfer_create": [(
        "Only call snaplii_transfer_finish when the user explicitly asks to send now.",
        "Only call snaplii_transfer_finish when the user explicitly asks to send now. Do not poll a PENDING "
        "transfer inside its cancel window (see snaplii_transfer_status for when to check). If this call returns "
        "no result at all (timeout, dropped connection), first call snaplii_transfer_list without `status` "
        "(newest first) and look for a transfer just created with the same recipient last 4 digits and amount, "
        "including ones already FINISHED, before deciding whether to create it again.",
    )],
    "snaplii_transfer_cancel": [(
        "then poll snaplii_transfer_status.",
        f"then check snaplii_transfer_status about every 10 seconds; {_POLL_LIMIT}.",
    )],
    "snaplii_transfer_finish": [(
        "poll snaplii_transfer_status until FINISHED or FAILED.",
        f"check snaplii_transfer_status about every 10 seconds until FINISHED or FAILED; {_POLL_LIMIT}.",
    )],
    "snaplii_transfer_status": [(
        "Poll every few seconds while PENDING/FINISHING/CANCELLING; stop at FINISHED (success), CANCELLED, or "
        "FAILED (report fail_message to the user).",
        "Do not poll a PENDING transfer inside its cancel window (before auto_finish_at): telling the user the "
        "deadline is enough. After auto_finish_at, after snaplii_transfer_finish, or when a cancel returned "
        "CANCELLING, check about every 10 seconds; stop at FINISHED (success), CANCELLED, or FAILED (report "
        "fail_message to the user). If none comes within two minutes, stop and tell the user to check again later.",
    )],
}

# Paragraphs of the local instructions that the remote server leaves out, by their heading.
DROPPED_PARAGRAPHS = ("UPDATES:", "CONNECT:")
INSTRUCTION_EDITS = [
    # Every grant reads this paragraph; only ALL grants have the transfer tools.
    ("Transfers have a separate rolling 24-hour per-key transfer limit;",
     "Only when the snaplii_transfer_* tools are listed (the key allows transfers): transfers have a separate "
     "rolling 24-hour per-key transfer limit;"),
    ("P2P TRANSFERS: send Snaplii Cash to another person's phone number (the API key's scope must include P2P "
     "or ALL).",
     "P2P TRANSFERS (applies only when the snaplii_transfer_* tools are listed): send Snaplii Cash to another "
     "person's phone number."),
    (", then poll snaplii_transfer_status every few seconds until FINISHED (report success) or FAILED (report "
     "the fail_message). Once auto_finish_at passes, poll the same way to confirm the outcome.",
     ". Do not poll while the transfer is inside its cancel window: telling the user the deadline is enough. "
     "After auto_finish_at passes, after snaplii_transfer_finish, or when a cancel returns CANCELLING, check "
     "snaplii_transfer_status about every 10 seconds until FINISHED (report success), CANCELLED, or FAILED "
     f"(report the fail_message); {_POLL_LIMIT}."),
    (" Or run the snaplii_autopilot prompt for the guided end-to-end flow.", ""),
]


def _edit(text: str, edits, where: str) -> str:
    for old, new in edits:
        if text.count(old) != 1:
            raise SystemExit(f"{where}: the text this export edits is no longer in server.py exactly once: {old!r}")
        text = text.replace(old, new)
    return text


def remote_instructions() -> str:
    paragraphs = server._SERVER_INSTRUCTIONS.split("\n\n")
    for heading in DROPPED_PARAGRAPHS:
        if sum(p.startswith(heading) for p in paragraphs) != 1:
            raise SystemExit(f"instructions: expected one {heading} paragraph in server.py")
    kept = [p for p in paragraphs if not p.startswith(DROPPED_PARAGRAPHS)]
    return _edit("\n\n".join(kept), INSTRUCTION_EDITS, "instructions")


def build() -> dict:
    local = asyncio.run(server.list_tools())
    unclassified = {t.name for t in local} - set(REQUIRED_KEY_SCOPE) - LOCAL_ONLY
    missing = set(REQUIRED_KEY_SCOPE) - {t.name for t in local}
    if unclassified or missing:
        raise SystemExit(f"server.py tools changed: unclassified {sorted(unclassified)}, missing {sorted(missing)}")
    tools = []
    for tool in local:
        if tool.name not in REQUIRED_KEY_SCOPE:
            continue
        tools.append({
            "name": tool.name,
            "title": tool.title,
            "description_remote": _edit(tool.description, DESCRIPTION_EDITS.get(tool.name, ()), tool.name),
            "inputSchema": tool.inputSchema,
            "annotations": tool.annotations.model_dump(by_alias=True, exclude_none=True),
            "required_key_scope": REQUIRED_KEY_SCOPE[tool.name],
        })
    return {"instructions": remote_instructions(), "tools": tools}


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output file (default: %(default)s)")
    parser.add_argument("--check", action="store_true", help="Read-only drift check of --out")
    args = parser.parse_args(argv)
    content = render()
    if args.check:
        if not args.out.exists() or args.out.read_text(encoding="utf-8") != content:
            print(f"{args.out} is out of date; run scripts/{Path(__file__).name}", file=sys.stderr)
            return 1
        print(f"{args.out} is up to date.")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(content, encoding="utf-8")
    print(f"Wrote {args.out}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Sync the marked Auth block, or check source/staged skill distributions.

--root checks a staged tree using the same four relative distribution paths.
--skill checks an actual standalone downloaded/extracted SKILL.md (repeatable).
--require-secure-entry additionally enforces the Muse feature's release gate.
No host tools, credentials, configuration, or network access are used.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "snaplii-cli" / "src"))
from snaplii import auth  # noqa: E402

TARGETS = (
    "skills/snaplii-cli.md",
    "clawhub-publish/SKILL.md",
    "skills/snaplii-autopilot.md",
    "clawhub-autopilot/SKILL.md",
)
BEGIN = "<!-- muse-auth:begin -->"
END = "<!-- muse-auth:end -->"


def replacement(content: str, block: str) -> str:
    if content.count(BEGIN) != 1 or content.count(END) != 1:
        raise ValueError("expected exactly one Auth marker pair")
    start, end = content.index(BEGIN), content.index(END)
    if end < start:
        raise ValueError("Auth markers are reversed")
    # Check placement without interpreting or changing unrelated skill content.
    prefix = content[:start]
    if re.search(r"^## (?:Prerequisites|Requirements|Decision Flow|Full Flow)\b|"
                 r"^### (?:Step 1:|1\. )|^```|`(?:snaplii|pip install)\b", prefix, re.M):
        raise ValueError("Auth block must precede executable instructions")
    return prefix + BEGIN + "\n" + block.rstrip() + "\n" + content[end:]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Read-only drift check")
    locations = parser.add_mutually_exclusive_group()
    locations.add_argument("--root", type=Path, default=ROOT, help="Source or staged distribution root")
    locations.add_argument("--skill", type=Path, action="append", help="Standalone artifact (check only)")
    parser.add_argument("--require-secure-entry", action="store_true", help="Require verified native input calls")
    args = parser.parse_args(argv)
    if args.skill and not args.check:
        parser.error("--skill requires --check; standalone artifacts are read-only")
    actions = auth.secure_entry_actions()
    if args.require_secure_entry and (actions is None or any("tool" not in action for action in actions.values())):
        print("Muse secure-input contract is not verified; automatic-dialog release is blocked.", file=sys.stderr)
        return 1
    block = auth.render_auth_skill_block()
    paths = args.skill or [args.root / target for target in TARGETS]
    pending = []
    errors = []
    for path in paths:
        try:
            if path.is_symlink():
                raise ValueError("refusing a symlinked skill")
            content = path.read_text(encoding="utf-8")
            updated = replacement(content, block)
            if updated != content:
                pending.append((path, updated))
                if args.check:
                    errors.append(f"{path}: Auth block is out of sync")
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(f"{path}: {exc}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    # Validate every target before writing any of them.
    for path, updated in pending:
        path.write_text(updated, encoding="utf-8")
    print("Auth blocks are in sync." if args.check else f"Updated {len(pending)} Auth block(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

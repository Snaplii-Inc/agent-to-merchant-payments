#!/usr/bin/env python3
"""Sync the generated Auth section, or check source/staged skill distributions.

--root checks a staged tree using the same four relative distribution paths.
--skill checks an actual standalone downloaded/extracted SKILL.md (repeatable).
--require-secure-entry additionally requires a literal native-tool call schema.
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
# The generated block is the skill's "## Auth" section: from that heading to the
# next level-2 heading. No comment markers, so the whole section stays visible
# in every rendered view of the skill.
ATX_HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
# A "---" line under paragraph text makes that text a level-2 heading too.
SETEXT2 = re.compile(r"^ {0,3}-+[ \t]*$")
# Lines that start a list item, quote or table instead of paragraph text.
NOT_PARAGRAPH = re.compile(r"^ {0,3}(?:[-*+](?:[ \t]|$)|\d{1,9}[.)](?:[ \t]|$)|>|\|)")


def scan(text: str):
    """(offset, title) of every level-2 heading (ATX or setext) outside fenced
    code, and the fence still open at the end of the text, if any."""
    found, fence, offset = [], None, 0
    previous = None  # (offset, text) of the paragraph just above this line, if any
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        opener = FENCE.match(bare)
        paragraph = None
        if fence:
            # A fence closes on the same character, at least as long, nothing after it.
            if opener and opener.group(1)[0] == fence[0] and len(opener.group(1)) >= len(fence) \
                    and not bare[opener.end():].strip():
                fence = None
        elif opener:
            fence = opener.group(1)
        else:
            heading = ATX_HEADING.match(bare)
            if heading and len(heading.group(1)) == 2:
                title = re.sub(r"[ \t]+#+$", "", heading.group(2) or "").strip()
                found.append((offset, title))
            elif previous and SETEXT2.match(bare):
                found.append((previous[0], previous[1].strip()))
            elif bare.strip() and not heading and not NOT_PARAGRAPH.match(bare):
                # Continuation lines extend the paragraph a setext underline would title.
                paragraph = (previous[0], previous[1] + " " + bare.strip()) if previous else (offset, bare)
        previous = paragraph
        offset += len(line)
    return found, fence


def replacement(content: str, block: str) -> str:
    generated, open_fence = scan(block)
    if [title for _, title in generated] != ["Auth"] or generated[0][0] != 0 or open_fence:
        raise ValueError("the generated block must be one '## Auth' section")
    # The skills carry no HTML comments: nothing in them may be hidden from a reader.
    if "<!--" in content:
        raise ValueError("the skill must not contain HTML comments")
    headings, _ = scan(content)
    auth = [index for index, (_, title) in enumerate(headings) if title == "Auth"]
    if len(auth) != 1:
        raise ValueError("expected exactly one '## Auth' section")
    if auth[0] + 1 == len(headings):
        raise ValueError("the '## Auth' section must be followed by another '## ' section")
    start, end = headings[auth[0]][0], headings[auth[0] + 1][0]
    # Check placement without interpreting or changing unrelated skill content.
    prefix = content[:start]
    if re.search(r"^## (?:Prerequisites|Requirements|Decision Flow|Full Flow)\b|"
                 r"^### (?:Step 1:|1\. )|^```|`(?:snaplii|pip install)\b", prefix, re.M):
        raise ValueError("Auth block must precede executable instructions")
    return prefix + block.rstrip() + "\n\n" + content[end:]


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
        print("Literal native-tool schema is unavailable; --require-secure-entry requires explicit tool/arguments.",
              file=sys.stderr)
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

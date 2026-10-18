"""Published authentication instructions must match executable auth actions."""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from snaplii import auth

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sync_muse_auth_docs.py"
SKILLS = (
    "skills/snaplii-cli.md",
    "clawhub-publish/SKILL.md",
    "skills/snaplii-autopilot.md",
    "clawhub-autopilot/SKILL.md",
)


def split_auth(content):
    """Return (prefix, the '## Auth' section, the rest) of a distributed skill."""
    start = content.index("\n## Auth\n") + 1
    end = content.index("\n## ", start) + 1
    return content[:start], content[start:end], content[end:]


def run_sync(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)],
                          capture_output=True, text=True)


def test_secure_init_action_and_skill_share_the_same_instruction():
    action = auth.build_auth_action("auth_required", host="muse")
    block = auth.render_auth_skill_block()
    assert action["argv"] == [
        "snaplii", "--base-url", "https://aipayment.snaplii.com", "init", "--vault-auth",
    ]
    assert action["instruction"] in block
    assert " ".join(action["argv"]) in block
    assert "has_valid_token=true" in block
    # Missing host evidence must not produce an invented, callable host tool.
    assert "credentials.request_api_access" not in block
    assert auth.build_auth_action("credential_required", host="muse")["type"] == "muse_secure_entry"


def test_muse_input_action_requires_host_capability_without_inventing_a_tool():
    action = auth.build_auth_action("credential_required", host="muse")
    assert action["type"] == "muse_secure_entry"
    assert action["capability"] == "muse.secure_credential_store"
    assert action["operation"] == "ensure_api_key"
    assert action["credential"] == {"provider": "custom.snaplii", "entry": "access_token",
                                    "allowed_hosts": ["aipayment.snaplii.com"]}
    assert "tool" not in action and "arguments" not in action
    assert action["after_success"]["argv"] == ["snaplii", "--base-url", auth.DEFAULT_ORIGIN, "init", "--vault-auth"]
    assert action["instruction"] in auth.render_auth_skill_block()
    assert "MUST open Muse's native secure credential input dialog" in action["instruction"]
    assert auth.build_auth_action("invalid_key", host="muse")["operation"] == "replace_api_key"
    assert auth.build_auth_action("credential_lookup_failed", host="muse")["operation"] == "inspect_api_key"
    assert auth.build_auth_action("credential_required", host="unknown")["type"] == "offer_legacy"
    assert auth.build_auth_action("secure_entry_unavailable", host="muse")["type"] == "offer_legacy"
    assert auth.build_auth_action("credential_required", host="muse", origin="https://other.example")["type"] == "stop"


@pytest.mark.parametrize("state", ["credential_required", "invalid_key", "credential_lookup_failed"])
def test_muse_key_requests_carry_the_documented_app_creation_route(state):
    action = auth.build_auth_action(state, host="muse")
    # A standalone runtime action must guide key creation without relying on
    # the user or agent having read the repository's Quick Start first.
    instruction = " ".join(action["instruction"].split())
    route = "More → Payment Methods → AI Payment Management → + New API Key"
    assert route in instruction
    # Keep the actual App labels/order aligned with the public setup guide.
    quick_start = (ROOT / "README.md").read_text().split("### 1. Get Your API Key via Snaplii App", 1)[1]
    quick_start = quick_start.split("### 2.", 1)[0]
    positions = [quick_start.index(label) for label in route.split(" → ")]
    assert positions == sorted(positions)
    assert action["after_success"]["instruction"] == action["instruction"]
    # Existing sessions need no input request, and this guide is Muse-specific.
    assert auth.build_auth_action("ready", host="muse") is None
    assert "instruction" not in auth.build_auth_action("auth_required", host="unknown")


def test_all_distributed_skills_have_the_current_auth_gate():
    result = run_sync("--check")
    assert result.returncode == 0, result.stdout + result.stderr
    for relative in SKILLS:
        content = (ROOT / relative).read_text()
        # The section is plain Markdown: nothing a reviewer could read as hidden.
        assert "<!--" not in content
        assert content.count("\n## Auth\n") == 1
        _, section, rest = split_auth(content)
        assert section.strip() == auth.render_auth_skill_block().strip()
        first_step = "## Prerequisites" if "cli" in relative or "clawhub-publish" in relative else "## Requirements"
        assert rest.startswith(first_step)
        if first_step == "## Prerequisites":
            step = content.split("### Step 1:")[1].split("### Step 2:")[0]
            assert "has_valid_token=true" in step
            assert "agent_id" not in step and "{}" not in step
        assert "401 / 403" not in content


@pytest.mark.parametrize("relative", SKILLS)
def test_cli_login_guidance_gives_the_command_and_never_collects_the_key(relative):
    # Wrapping differs between distributions only by line breaks.
    text = " ".join(split_auth((ROOT / relative).read_text())[1].split())
    assert ("When CLI authentication is needed, your first message asking the user to act "
            "gives that exact command, with the "
            "installed CLI's path and the task's gateway options; do not ask for the key in "
            "the chat or in a file.") in text
    assert "`init` first asks whether sessions may be kept in an owner-only file" in text
    # The MCP chat fallback stays available when the user explicitly chooses it.
    assert "use `snaplii_init` only when the user explicitly chooses that fallback" in text


@pytest.fixture
def skill_artifacts(tmp_path):
    # Check standalone distribution files, not just imported source constants.
    for relative in SKILLS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((ROOT / relative).read_text())
    return tmp_path


@pytest.mark.parametrize("relative", SKILLS)
@pytest.mark.parametrize("changed", [
    ("has_valid_token=true", "agent_id exists"),
    ("--vault-auth", "--guessed-auth"),
    ("https://aipayment.snaplii.com", "https://other.example"),
    ("has_valid_token=true", "T1_PENDING_TOOL_CALL"),
    ("Only when host=muse", "For every host"),
    ("Honor an explicit install-only", "Ignore an explicit install-only"),
    ("keep the installed skill", "remove the installed skill"),
])
def test_check_rejects_artifact_drift_without_writing(skill_artifacts, relative, changed):
    path = skill_artifacts / relative
    before = path.read_text().replace(*changed, 1)
    path.write_text(before)
    result = run_sync("--check", "--root", skill_artifacts)
    assert result.returncode != 0
    assert relative in result.stderr
    assert path.read_text() == before


def test_sync_changes_only_generated_blocks_and_is_idempotent(skill_artifacts):
    originals = {}
    for relative in SKILLS:
        path = skill_artifacts / relative
        before = path.read_text() + "\nUnrelated distribution-specific text.\n"
        originals[relative] = before
        prefix, _, suffix = split_auth(before)
        path.write_text(prefix + "## Auth\n\nstale auth instructions\n\n" + suffix)
    assert run_sync("--root", skill_artifacts).returncode == 0
    for relative, original in originals.items():
        assert (skill_artifacts / relative).read_text() == original
    assert run_sync("--root", skill_artifacts).returncode == 0
    assert run_sync("--check", "--root", skill_artifacts).returncode == 0


def load_sync_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("sync_muse_auth_docs", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_fenced_heading_inside_auth_is_replaced_with_the_section(skill_artifacts):
    path = skill_artifacts / SKILLS[0]
    original = path.read_text()
    prefix, _, suffix = split_auth(original)
    # A "## " line inside a code fence is example text, not the end of the section.
    stale = "## Auth\n\nstale\n\n```text\n## Example\nstale example\n```\n\n"
    path.write_text(prefix + stale + suffix)
    assert run_sync("--check", "--root", skill_artifacts).returncode != 0
    assert run_sync("--root", skill_artifacts).returncode == 0
    assert path.read_text() == original
    assert run_sync("--check", "--root", skill_artifacts).returncode == 0


@pytest.mark.parametrize("next_heading", [
    "  ## Prerequisites",            # up to three spaces still make a heading
    "## Prerequisites ##",           # closing hashes
    "Prerequisites\n-------------",  # setext level-2 heading
    "**Prerequisites**\n---",          # setext heading with emphasis
])
def test_any_markdown_level2_heading_ends_the_auth_section(next_heading):
    sync = load_sync_module()
    block = auth.render_auth_skill_block()
    content = ("# Skill\n\nIntro.\n\n## Auth\n\nstale\n\n" + next_heading +
               "\n\nKeep this.\n\n## Later\n\nAnd this.\n")
    updated = sync.replacement(content, block)
    assert updated.endswith(next_heading + "\n\nKeep this.\n\n## Later\n\nAnd this.\n")
    assert "stale" not in updated


def test_auth_heading_is_found_and_counted_regardless_of_trailing_spaces():
    sync = load_sync_module()
    block = auth.render_auth_skill_block()
    content = "# Skill\n\n## Auth  \n\nstale\n\n## Prerequisites\n\nKeep.\n"
    assert "stale" not in sync.replacement(content, block)
    duplicate = content + "\n## Auth \n\nconflicting\n\n## Later\n"
    with pytest.raises(ValueError, match="exactly one"):
        sync.replacement(duplicate, block)


@pytest.mark.parametrize("generated", [
    "## Auth\n\nnew\n\n## Extra\n\nwould split the section\n",
    "## Auth\n\nnew\n\n**Extra**\n---\n",
    "## Auth\n\n```text\nnever closed\n",
    "## Auth\n\n~~~\nnever closed\n",
])
def test_a_generated_block_that_is_not_one_closed_section_is_refused(generated):
    sync = load_sync_module()
    content = "# Skill\n\n## Auth\n\nold\n\n## Prerequisites\n\nKeep.\n"
    with pytest.raises(ValueError, match="one '## Auth' section"):
        sync.replacement(content, generated)


def test_check_refuses_an_auth_section_hidden_in_a_comment(skill_artifacts):
    path = skill_artifacts / SKILLS[0]
    prefix, section, suffix = split_auth(path.read_text())
    hidden = prefix + "<!--\n" + section + suffix.replace("\n## ", "\n-->\n## ", 1)
    path.write_text(hidden)
    result = run_sync("--check", "--root", skill_artifacts)
    assert result.returncode != 0
    assert "HTML comments" in result.stderr
    standalone = run_sync("--check", "--skill", path)
    assert standalone.returncode != 0
    assert path.read_text() == hidden


@pytest.mark.parametrize("malformation", ["missing", "duplicate", "unterminated", "late"])
def test_malformed_blocks_abort_all_writes(skill_artifacts, malformation):
    path = skill_artifacts / SKILLS[-1]
    before = path.read_text()
    prefix, section, suffix = split_auth(before)
    if malformation == "missing":
        before = before.replace("\n## Auth\n", "\n## Authentication\n")
    elif malformation == "duplicate":
        before += "\n## Auth\n\nextra\n"
    elif malformation == "unterminated":
        # Nothing after the section marks where the generated text ends.
        before = prefix + section
    else:
        # The section moved below the first executable instructions.
        last = suffix.rindex("\n## ") + 1
        before = prefix + suffix[:last] + section + suffix[last:]
    path.write_text(before)
    # Also make an earlier target stale: malformed later targets must prevent
    # partial writes even when ordinary sync could repair this earlier one.
    other = skill_artifacts / SKILLS[0]
    other.write_text(other.read_text().replace("has_valid_token=true", "stale", 1))
    snapshot = {name: (skill_artifacts / name).read_bytes() for name in SKILLS}
    for flags in [("--check",), ()]:
        result = run_sync(*flags, "--root", skill_artifacts)
        assert result.returncode != 0
        assert {name: (skill_artifacts / name).read_bytes() for name in SKILLS} == snapshot


def test_literal_tool_contract_gate_does_not_certify_capability_guidance():
    result = run_sync("--check", "--require-secure-entry")
    assert result.returncode != 0
    assert "requires explicit tool/arguments" in result.stderr
    assert "automatic-dialog release is blocked" not in result.stderr


@pytest.mark.parametrize("relative", [
    *SKILLS, "README.md", "snaplii-cli/README.md", "scripts/candidate/INSTALL.md",
    "clawhub-plugin/README.md", "claude-desktop/PROJECT_INSTRUCTIONS.md",
])
def test_agent_documents_do_not_carry_obsolete_dialog_acceptance_status(relative):
    # Acceptance bookkeeping is not an instruction to the consuming agent.
    text = (ROOT / relative).read_text()
    for obsolete in ("Muse 自动输入框的真实效果仍待", "弹窗效果待验证",
                     "muse_dialog_acceptance", "muse_native_dialog",
                     "automatic-dialog release is blocked"):
        assert obsolete not in text, relative


def test_downloaded_standalone_skill_is_checked_read_only(skill_artifacts, tmp_path):
    artifact = tmp_path / "downloaded" / "SKILL.md"
    artifact.parent.mkdir()
    artifact.write_bytes((skill_artifacts / "clawhub-publish/SKILL.md").read_bytes())
    assert run_sync("--check", "--skill", artifact).returncode == 0
    artifact.write_text(artifact.read_text().replace("--vault-auth", "--wrong-argument", 1))
    before = artifact.read_bytes()
    assert run_sync("--check", "--skill", artifact).returncode != 0
    assert run_sync("--skill", artifact).returncode != 0
    assert artifact.read_bytes() == before


def test_renderer_preserves_native_request_and_reconnect_contracts(monkeypatch):
    # Synthetic contract tests the publishing seam, NOT the real Muse schema.
    original = auth.build_auth_action
    calls = {
        "credential_required": {"tool": "test_native.request", "arguments": {
            "provider": "test.snaplii", "hosts": ["aipayment.snaplii.com"],
            "input": {"name": "test_api_key", "secret": True}}},
        "invalid_key": {"tool": "test_native.reconnect", "arguments": {
            "provider": "test.snaplii", "replace": True}},
    }

    def action(state, **kwargs):
        if state not in calls:
            return original(state, **kwargs)
        return {"type": "muse_secure_entry", **calls[state],
                "instruction": auth.MUSE_AUTH_INSTRUCTION,
                "after_success": original("auth_required", host="muse")}

    monkeypatch.setattr(auth, "build_auth_action", action)
    block = auth.render_auth_skill_block()
    literal_calls = [json.loads(value) for value in re.findall(r"```json\n(.*?)\n```", block, re.S)]
    assert literal_calls == list(calls.values())
    for state in calls:
        runtime_action = auth.build_auth_action(state, host="muse")
        assert runtime_action["instruction"] in block
        assert " ".join(runtime_action["after_success"]["argv"]) in block
    assert "Automatic secure-input invocation is unavailable" not in block

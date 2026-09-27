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
BEGIN = "<!-- muse-auth:begin -->"
END = "<!-- muse-auth:end -->"


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
    assert auth.build_auth_action("credential_required", host="muse")["type"] == "offer_legacy"


def test_all_distributed_skills_have_the_current_auth_gate():
    result = run_sync("--check")
    assert result.returncode == 0, result.stdout + result.stderr
    for relative in SKILLS:
        content = (ROOT / relative).read_text()
        assert content.count(BEGIN) == content.count(END) == 1
        block = content.split(BEGIN)[1].split(END)[0].strip()
        assert block == auth.render_auth_skill_block().strip()
        first_step = "## Prerequisites" if "cli" in relative or "clawhub-publish" in relative else "## Requirements"
        assert content.index(END) < content.index(first_step)
        if first_step == "## Prerequisites":
            step = content.split("### Step 1:")[1].split("### Step 2:")[0]
            assert "has_valid_token=true" in step
            assert "agent_id" not in step and "{}" not in step
        assert "401 / 403" not in content


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
        prefix, rest = before.split(BEGIN)
        _, suffix = rest.split(END)
        path.write_text(prefix + BEGIN + "\nstale auth instructions\n" + END + suffix)
    assert run_sync("--root", skill_artifacts).returncode == 0
    for relative, original in originals.items():
        assert (skill_artifacts / relative).read_text() == original
    assert run_sync("--root", skill_artifacts).returncode == 0
    assert run_sync("--check", "--root", skill_artifacts).returncode == 0


@pytest.mark.parametrize("malformation", ["missing", "duplicate", "reversed", "late"])
def test_malformed_blocks_abort_all_writes(skill_artifacts, malformation):
    path = skill_artifacts / SKILLS[-1]
    before = path.read_text()
    if malformation == "missing":
        before = before.replace(BEGIN, "")
    elif malformation == "duplicate":
        before += "\n" + BEGIN + "\n" + END
    elif malformation == "reversed":
        before = before.replace(BEGIN, "TEMP_MARKER").replace(END, BEGIN).replace("TEMP_MARKER", END)
    else:
        prefix, rest = before.split(BEGIN)
        block, suffix = rest.split(END)
        before = prefix + suffix + BEGIN + block + END
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


def test_secure_entry_release_gate_cannot_pass_with_only_safe_fallback_docs():
    result = run_sync("--check", "--require-secure-entry")
    assert result.returncode != 0
    assert "secure-input contract is not verified" in result.stderr


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

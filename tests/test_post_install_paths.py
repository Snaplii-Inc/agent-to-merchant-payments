"""After the installer finishes, Snaplii must work from any directory.

The MCP registration is user-wide, the skill lands user-wide, the commands an
agent relays name a CLI that exists, the skill finds the installer's CLI, and
the README covers uninstalling and what a session needs.
"""

import os
import re
import sys
from pathlib import Path

import pytest

from snaplii import auth

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
CLI_SKILL = (ROOT / "skills/snaplii-cli.md").read_text()
AUTOPILOT = (ROOT / "skills/snaplii-autopilot.md").read_text()


def _components():
    exe_dir = "/home/u/.snaplii-env/bin"
    return {"cli": {"status": "installed", "version": "0.19.0", "executable": exe_dir + "/snaplii", "host_seen_by_cli": "unknown"},
            "mcp": {"status": "installed", "version": "0.19.0", "executable": exe_dir + "/snaplii-mcp", "tools": 26}}


def _steps(installer, host):
    return {s["id"]: s for s in installer.next_steps(host, "unknown", _components(), "/home/u/.snaplii-env", None,
                                                       False, False, "linux", {"HOME": "/home/u"}, ["python3", "install.py"])}


# 1. Claude Code registration is user-wide

def test_claude_code_registration_is_user_wide(installer):
    command = _steps(installer, "claude-code")["register_mcp"]["command"]
    assert command == "claude mcp add --scope user snaplii -- /home/u/.snaplii-env/bin/snaplii-mcp"


def test_readme_claude_code_block_matches_the_installer():
    block = README.split("<summary><strong>Claude Code</strong></summary>", 1)[1].split("</details>", 1)[0]
    assert "claude mcp add --scope user snaplii -- ~/.snaplii-env/bin/snaplii-mcp" in block
    assert "claude mcp get snaplii" in block


# 4. the skill install never writes into the current project

@pytest.mark.parametrize("host,tail", [("claude-code", ["-g", "-a", "claude-code", "-y"]), ("codex", ["-g", "-a", "codex", "-y"]),
                                       ("cursor", ["-g", "-a", "cursor", "-y"]), (None, ["-g", "-a", "AGENT", "-y"])])
def test_skill_install_is_user_wide(installer, host, tail):
    skill = _steps(installer, host)["install_skill"]
    words = ["--yes", "skills", "add", "https://github.com/Snaplii-Inc/agent-to-merchant-payments/tree/v0.19.0"] + tail
    if host is None:
        assert "npx " + " ".join(words) in skill["why"]
    else:
        assert skill["args"] == words


def test_readme_skill_command_is_user_wide():
    block = README.split("### Install from a release", 1)[1].split("\n### ", 1)[0]
    assert "npx --yes skills add ./snaplii-src -g -a claude-code -y" in block


# 2. relayed commands name a CLI that exists

def _bin(tmp_path, with_cli=True):
    bindir = tmp_path / "env" / "bin"
    bindir.mkdir(parents=True)
    (bindir / "python").write_text("")
    if with_cli:
        cli = bindir / "snaplii"
        cli.write_text("#!/bin/sh\n")
        cli.chmod(0o755)
    return bindir


def test_cli_off_path_is_named_by_absolute_path(tmp_path, monkeypatch):
    bindir = _bin(tmp_path)
    monkeypatch.setattr(sys, "executable", str(bindir / "python"))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert auth.cli_executable() == str(bindir / "snaplii")
    action = auth.build_auth_action("auth_required", host="unknown")
    assert action["argv"][0] == str(bindir / "snaplii")
    legacy = auth.build_auth_action("invalid_key", host="unknown")
    assert legacy["argv"][0] == str(bindir / "snaplii")


def test_cli_on_path_keeps_the_bare_name(tmp_path, monkeypatch):
    bindir = _bin(tmp_path)
    monkeypatch.setattr(sys, "executable", str(bindir / "python"))
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + "/usr/bin")
    assert auth.cli_executable() == "snaplii"


def test_no_cli_beside_the_interpreter_keeps_the_bare_name(tmp_path, monkeypatch):
    bindir = _bin(tmp_path, with_cli=False)
    monkeypatch.setattr(sys, "executable", str(bindir / "python"))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    assert auth.cli_executable() == "snaplii"


def test_skill_text_never_carries_a_machine_path(monkeypatch):
    monkeypatch.setattr(auth, "cli_executable", lambda: "/home/someone/.snaplii-env/bin/snaplii")
    block = auth.render_auth_skill_block()
    assert "/home/someone" not in block
    assert "snaplii --base-url https://aipayment.snaplii.com init --vault-auth" in block


def test_readme_says_relayed_argv_may_be_an_absolute_path():
    sessions = README.split("### Sessions and reconnecting", 1)[1].split("\n---", 1)[0]
    assert "absolute path" in sessions


# 3. the skill finds the installer's CLI and updates through the installer

def test_cli_skill_looks_in_the_installer_environment_first():
    path_section = CLI_SKILL.split("**PATH handling (Bash mode).**", 1)[1].split("## Decision Flow", 1)[0]
    assert "~/.snaplii-env/bin" in path_section
    assert "%USERPROFILE%\\.snaplii-env\\Scripts" in path_section
    assert path_section.index("~/.snaplii-env/bin") < path_section.index("~/.local/bin")


def test_cli_skill_installs_and_updates_through_the_installer():
    prerequisites = CLI_SKILL.split("## Prerequisites", 1)[1].split("You help users", 1)[0]
    assert "scripts/install.py" in prerequisites and "pip install -U snaplii-cli" not in prerequisites
    step0 = CLI_SKILL.split("### Step 0", 1)[1].split("### Step 1", 1)[0]
    assert "~/.snaplii-env" in step0 and "installer" in step0


def test_autopilot_names_the_installer_cli():
    assert "~/.snaplii-env/bin/snaplii" in AUTOPILOT


def test_skill_copies_stay_identical():
    assert (ROOT / "skills/snaplii-cli.md").read_bytes() == (ROOT / "clawhub-publish/SKILL.md").read_bytes()
    assert (ROOT / "skills/snaplii-autopilot.md").read_bytes() == (ROOT / "clawhub-autopilot/SKILL.md").read_bytes()


# 5. README: uninstall, requirements, flags, sessions

def test_readme_has_an_uninstall_section():
    assert re.search(r"^#+ Uninstall$", README, re.M)
    section = README.split("Uninstall\n", 1)[1].split("\n## ", 1)[0]
    for needle in ("claude mcp remove snaplii", "npx --yes skills remove -g -y snaplii-cli snaplii-autopilot",
                   "config clear", "rm -rf ~/.snaplii-env", "Revoke", "uv python uninstall 3.12"):
        assert needle in section, needle
    assert "(#uninstall)" in README.split("## Table of Contents", 1)[1].split("\n## ", 1)[0]


def test_readme_drops_the_manual_python_upgrade_for_mac():
    assert "Mac users: check your Python version" not in README
    assert "brew install python@3.12" not in README


def test_readme_lists_every_installer_flag():
    flags = README.split("`--host` also takes", 1)[1].split("\n\n", 1)[0]
    assert "`--help`" in flags  # the installer's own --help owns the flag list


def test_readme_sessions_cover_key_keeping_and_shared_storage():
    sessions = README.split("### Sessions and reconnecting", 1)[1].split("\n---", 1)[0]
    assert "password manager" in sessions
    assert "expires" in sessions or "lifetime" in sessions
    assert "allow_insecure_mode" in sessions and "MCP server" in sessions
    shell_only = sessions.split("**Shell-only agent.**", 1)[1].split("\n- **", 1)[0]
    assert "only if the host passes it on" in shell_only

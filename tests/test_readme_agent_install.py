"""Any Agent-Skills agent can follow the README's install section without guessing."""

import re
from pathlib import Path

README = (Path(__file__).resolve().parents[1] / "README.md").read_text()
AGENT_SECTION = README.split("## For AI agents: start here", 1)[1].split("## Table of Contents", 1)[0]


def _section(title):
    return README.split(title, 1)[1].split("\n### ", 1)[0]


def test_agent_section_stays_short():
    assert len(AGENT_SECTION.split()) <= 800


def test_install_explains_agent_names_and_hosts():
    block = _section("### Install from a release")
    for needle in ("`-a`", "gemini-cli", "github-copilot", "interactive", "Manual install",
                   "`--host`", "`muse`", "leave it out", "`--cli-only`"):
        assert needle in block, needle


def test_report_steps_say_what_to_skip():
    pending = [line for line in README.splitlines() if line.startswith("- `pending`:")][0]
    assert "skip `install_skill`" in pending and "only" in pending
    assert "JSON keys are a contract" not in README


def test_verify_is_something_an_agent_can_check():
    verify = README.split("**Verify.**", 1)[1].split("\n\n", 1)[0]
    assert "What can Snaplii do" not in verify
    assert "snaplii_config_show" in verify and "config show" in verify and "new session" in verify


def test_muse_gets_its_installer_command():
    muse = README.split("**Muse** runs the skill", 1)[1].split("\n\n", 1)[0]
    assert "--host muse --source ./snaplii-src" in muse


def test_mcp_section_registers_before_connecting_and_uses_the_installed_server():
    mcp = README.split("### MCP Server (", 1)[1].split("\n## ", 1)[0]
    assert mcp.index("#### Step 2: Configure your MCP client") < mcp.index("#### Step 3: Connect")
    for title in ("Claude Desktop", "OpenClaw", "Cursor / VS Code / Other MCP clients"):
        block = mcp.split("<summary><strong>%s</strong></summary>" % title, 1)[1].split("</details>", 1)[0]
        assert "snaplii-env" in block and "mcp-server/server.py" not in block, title
    assert "setup_claude_desktop.py" not in README


def test_small_fixes():
    assert "short version" not in README
    troubleshooting = README.split("### The skill is installed but the agent does not use it", 1)[1].split("\n### ", 1)[0]
    assert "Muse" in troubleshooting
    assert "No credential storage" not in README


# Second Codex review: one ordered finish, one release, no host-specific detours.

def test_verify_comes_after_the_report_and_registration():
    assert README.index("**Verify.**") > README.index("- `pending`:")
    pending = [line for line in README.splitlines() if line.startswith("- `pending`:")][0]
    assert "`json`" in pending and "`file`" in pending and "never run" in pending


def test_connection_timing_has_one_source():
    # The report's connect step carries the rule (Muse and Instinct connect on a first install);
    # the README points at it and the MCP guide states the same condition.
    verify = README.split("**Verify.**", 1)[1].split("\n\n", 1)[0]
    assert "first install" not in verify  # the report's connect step owns the timing rule
    step3 = README.split("#### Step 3: Connect", 1)[1].split("\n####", 1)[0]
    assert "asks to connect" in step3 and "installing alone does not connect" in step3
    assert "Connect right away" not in README


def test_branches_before_the_example_and_manual_copy_is_generic():
    block = _section("### Install from a release")
    assert block.index("Manual install") < block.index("```bash")
    manual = README.split("**Manual install.**", 1)[1].split("```bash", 1)[0]
    assert "only when the second command cannot run" in manual and "SKILLS_DIR" in manual


def test_muse_installs_from_the_clone():
    muse = README.split("**Muse** runs the skill", 1)[1].split("\n\n", 1)[0]
    assert "snaplii-src/clawhub-publish" in muse and "Ask Muse" not in muse


def test_one_release_is_the_only_install_route():
    for route in ("clawhub install", "pipx install", "pip3 install", "/tree/v", "mcp-server/server.py",
                  "pip install -e", "Without `--source`"):
        assert route not in README, route


def test_update_runs_first_and_closes_the_host_only_when_files_are_in_use():
    update = README.split("## Updating\n\n", 1)[1].split("\n\n", 1)[0]
    assert "quit the host" not in update and "files_in_use" in update and "new session" in update


def test_second_review_small_fixes():
    assert "`not_installed`" in README
    assert "a new session needs it again" not in README
    components = README.split("## Components", 1)[1].split("\n## ", 1)[0]
    assert "install.py" in components


# Codex and Claude reviews, 2026-10-09 evening: prompts, directories, bootstrap flags.

def test_skills_command_never_prompts_and_never_targets_every_agent():
    block = _section("### Install from a release")
    assert "-a claude-code -y" in block
    assert "Always pair `-y` with `-a`" in block and "every agent" in block and "`--yes`" in block


def test_the_agent_supplies_its_own_skills_directory():
    # Owner's standard: an Agent-Skills agent knows where its skills go; the README lists no directories.
    assert "Known skill directories" not in README and "~/.codex/skills" not in README
    assert "### Install the Agent Skill" not in README  # manual copy is a fallback, not a fourth step


def test_unlisted_agents_go_straight_to_manual_install():
    block = _section("### Install from a release")
    assert "| Any other agent | skip this command, use **Manual install** |" in block


def test_no_python_bootstrap_keeps_the_chosen_flags():
    section = README.split("### No Python on the machine", 1)[1].split("\n### ", 1)[0]
    assert "--host" in section and "--cli-only" in section and "same flags" in section


def test_manual_copy_is_repeatable_and_covers_project_only_agents():
    manual = README.split("**Manual install.**", 1)[1].split("**Muse**", 1)[0]
    assert 'cp -R snaplii-src/clawhub-publish/.   "$SKILLS_DIR/snaplii-cli/"' in manual
    assert '${SKILLS_DIR:?' in manual and "~/.agents/skills   #" not in manual
    assert "project skills directory" in manual and "update the files in place" in manual


def test_windows_fallbacks_name_their_shell():
    assert "Git Bash" in _section("### Install from a release")
    section = README.split("### No Python on the machine", 1)[1].split("\n### ", 1)[0]
    assert "```powershell" in section and "install.ps1" in section


def test_verify_checks_discovery_in_the_agent_and_mcp_examples_are_config():
    verify = README.split("**Verify.**", 1)[1].split("\n\n", 1)[0]
    assert "`npx skills list -g` shows `snaplii-cli` and `snaplii-autopilot`" in verify and "`Agents: not linked` is normal" in verify and "in this session" in verify and "if your agent uses MCP" in verify
    other = README.split("<summary><strong>Cursor / VS Code / Other MCP clients</strong></summary>", 1)[1].split("</details>", 1)[0]
    assert "```json" in other and "```bash" not in other


def test_manual_install_snippet_runs_and_refuses_an_unset_directory(tmp_path):
    import os
    import shutil
    import subprocess
    snippet = README.split("**Manual install.**", 1)[1].split("```bash\n", 1)[1].split("```", 1)[0]
    root = Path(__file__).resolve().parents[1]
    src = tmp_path / "snaplii-src"
    for folder in ("clawhub-publish", "clawhub-autopilot"):
        shutil.copytree(root / folder, src / folder)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)}
    unset = subprocess.run(["bash", "-c", snippet], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert unset.returncode != 0 and "SKILLS_DIR" in unset.stderr and not (tmp_path / "skills").exists()
    for _ in range(2):  # a repeat updates in place instead of nesting
        done = subprocess.run(["bash", "-c", snippet], cwd=tmp_path, env=dict(env, SKILLS_DIR=str(tmp_path / "skills")),
                              capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
    for name in ("snaplii-cli", "snaplii-autopilot"):
        assert (tmp_path / "skills" / name / "SKILL.md").is_file()
        assert not any(p.name.startswith("clawhub-") for p in (tmp_path / "skills" / name).iterdir())

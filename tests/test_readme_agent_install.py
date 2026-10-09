"""Any Agent-Skills agent can follow the README's install section without guessing."""

import re
from pathlib import Path

README = (Path(__file__).resolve().parents[1] / "README.md").read_text()
AGENT_SECTION = README.split("## For AI agents: start here", 1)[1].split("## Table of Contents", 1)[0]


def _section(title):
    return README.split(title, 1)[1].split("\n### ", 1)[0]


def test_agent_section_stays_short():
    assert len(AGENT_SECTION.split()) <= 2100


def test_install_explains_agent_names_and_hosts():
    block = _section("### Install from a release")
    for needle in ("`-a`", "gemini-cli", "github-copilot", "interactive", "Manual install",
                   "`--host`", "`muse`", "leave it out", "`--cli-only`"):
        assert needle in block, needle


def test_report_steps_say_what_to_skip():
    pending = [line for line in README.splitlines() if line.startswith("| `pending` |")][0]
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
    assert README.index("**Verify.**") > README.index("| `pending` |")
    pending = [line for line in README.splitlines() if line.startswith("| `pending` |")][0]
    assert "`json`" in pending and "`file`" in pending and "never run" in pending


def test_connection_waits_for_a_request_except_a_first_muse_install():
    verify = README.split("**Verify.**", 1)[1].split("\n\n", 1)[0]
    assert "asks to connect" in verify and "Muse" in verify
    rules = README.split("### Rules the skill enforces", 1)[1].split("\n### ", 1)[0]
    assert "installing alone does not" in rules


def test_branches_before_the_example_and_manual_copy_is_generic():
    block = _section("### Install from a release")
    assert block.index("Manual install") < block.index("```bash")
    manual = README.split("**Manual install.**", 1)[1].split("Known skill directories", 1)[0]
    assert "do not guess" in manual and "SKILLS_DIR" in manual


def test_muse_installs_from_the_clone():
    muse = README.split("**Muse** runs the skill", 1)[1].split("\n\n", 1)[0]
    assert "snaplii-src/clawhub-publish" in muse and "Ask Muse" not in muse


def test_one_release_is_the_only_install_route():
    for route in ("clawhub install", "pipx install", "pip3 install", "/tree/v", "mcp-server/server.py",
                  "pip install -e", "Without `--source`"):
        assert route not in README, route


def test_update_runs_first_and_closes_the_host_only_when_files_are_in_use():
    update = README.split("**Updating.**", 1)[1].split("\n\n", 1)[0]
    assert "quit the host" not in update and "files_in_use" in update and "new session" in update


def test_second_review_small_fixes():
    assert "`not_installed`" in README
    assert "a new session needs it again" not in README
    components = README.split("## Components", 1)[1].split("\n## ", 1)[0]
    assert "install.py" in components

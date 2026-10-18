"""The README installs the skill, the CLI and the MCP server from one release tag."""

import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
VERSION = tomllib.loads((ROOT / "snaplii-cli/pyproject.toml").read_text())["project"]["version"]
TAG = "v" + VERSION
CLONE = "git clone --depth 1 --branch %s https://github.com/Snaplii-Inc/agent-to-merchant-payments.git snaplii-src" % TAG


def test_every_release_tag_in_the_readme_is_the_current_version():
    tags = set(re.findall(r"\bv\d+\.\d+\.\d+(?:rc\d+)?\b", README))
    assert tags == {TAG}


def test_readme_installs_all_three_from_one_clone():
    block = README.split("### Install from a release", 1)[1].split("\n### ", 1)[0]
    bash = block.split("```bash", 1)[1].split("```", 1)[0]
    lines = [line.strip() for line in bash.strip().splitlines()]
    assert lines[0] == CLONE
    assert lines[1] == "npx --yes skills add ./snaplii-src -g -a claude-code -y"
    assert lines[2] == "python3 snaplii-src/scripts/install.py --host claude-code --source ./snaplii-src"
    assert "delete" in block and "same commit" in block


def test_readme_no_longer_installs_from_main():
    assert "/main/scripts/install.py" not in README
    assert "npx skills add Snaplii-Inc/agent-to-merchant-payments" not in README


def test_readme_update_uses_a_new_release_tag():
    update = README.split("## Updating\n\n", 1)[1].split("\n\n", 1)[0]
    assert "release tag" in update and "--source" in update and "snaplii update" in update


def test_instinct_and_mcp_steps_use_the_clone():
    assert "python3 snaplii-src/scripts/install.py --host instinct --source ./snaplii-src" in README
    assert "python3 snaplii-src/scripts/install.py --host claude-desktop --source ./snaplii-src" in README


def test_the_skill_installs_its_cli_from_the_same_release():
    # A skill installed on its own (e.g. from ClawHub) has no installer beside it,
    # so it names the clone and installer command itself, at the current tag.
    for relative in ("skills/snaplii-cli.md", "clawhub-publish/SKILL.md",
                     "skills/snaplii-autopilot.md", "clawhub-autopilot/SKILL.md"):
        skill = (ROOT / relative).read_text()
        assert set(re.findall(r"\bv\d+\.\d+\.\d+(?:rc\d+)?\b", skill)) == {TAG}, relative
        assert CLONE in skill, relative
        assert "python3 snaplii-src/scripts/install.py --source ./snaplii-src" in skill, relative


def test_every_plugin_starts_the_mcp_server_of_this_release():
    # uvx keeps reusing a cached server unless the version is pinned.
    # The Claude plugin directory spells an exact uvx pin with "==".
    pinned = {"clawhub-plugin": "@", "cursor-plugin": "@", "claude-plugin": "=="}
    for plugin, sep in pinned.items():
        config = "mcp.json" if plugin == "cursor-plugin" else ".mcp.json"
        server = json.loads((ROOT / plugin / config).read_text())["mcpServers"]["snaplii"]
        assert server["command"] == "uvx", plugin
        assert server["args"] == ["snaplii-mcp" + sep + VERSION], plugin
        readme = (ROOT / plugin / "README.md").read_text()
        pins = set(re.findall(r"snaplii-mcp(?:@|==)([0-9][^\s`]*)", readme))
        assert pins == {VERSION}, plugin
        assert ("snaplii-mcp" + sep + VERSION) in readme, plugin


def test_plugins_that_follow_the_package_version_match_it():
    # The Cursor and Claude plugins carry the package version and pin its CLI tag.
    for relative in ("cursor-plugin/.cursor-plugin/plugin.json", "claude-plugin/.claude-plugin/plugin.json"):
        assert json.loads((ROOT / relative).read_text())["version"] == VERSION, relative
    for relative in ("cursor-plugin/skills/snaplii-cli/SKILL.md", "claude-plugin/skills/snaplii-cli/SKILL.md"):
        skill = (ROOT / relative).read_text()
        assert set(re.findall(r"\bv\d+\.\d+\.\d+(?:rc\d+)?\b", skill)) == {TAG}, relative
        assert CLONE in skill, relative

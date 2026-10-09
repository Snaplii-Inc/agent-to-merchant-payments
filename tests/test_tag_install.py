"""The README installs the skill, the CLI and the MCP server from one release tag."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()
VERSION = tomllib.loads((ROOT / "snaplii-cli/pyproject.toml").read_text())["project"]["version"]
TAG = "v" + VERSION
CLONE = "git clone --depth 1 --branch %s https://github.com/Snaplii-Inc/agent-to-merchant-payments.git snaplii-src" % TAG


def test_every_release_tag_in_the_readme_is_the_current_version():
    tags = set(re.findall(r"\bv\d+\.\d+\.\d+\b", README))
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

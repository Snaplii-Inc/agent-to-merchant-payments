import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "claude-plugin"


def _manifest():
    return json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())


def test_api_key_option_is_optional_secret_and_reaches_the_mcp_server_env():
    options = _manifest()["userConfig"]
    assert set(options) == {"snaplii_api_key"}
    option = options["snaplii_api_key"]
    assert option["sensitive"] is True and option["required"] is False
    # Cowork never prompts for options and skips a server whose option has no default.
    assert option["default"] == ""
    env = json.loads((PLUGIN / ".mcp.json").read_text())["mcpServers"]["snaplii"]["env"]
    # Claude Code expands an unset optional value to an empty string, which the
    # server treats as no key.
    assert env == {"SNAPLII_API_KEY": "${user_config.snaplii_api_key}"}


def test_manifest_names_publisher_license_and_links():
    manifest = _manifest()
    assert manifest["name"] == "snaplii-a2m-payment"
    assert manifest["author"]["name"] == "Snaplii Inc."
    assert manifest["license"] == "Apache-2.0"
    assert manifest["repository"] == "https://github.com/Snaplii-Inc/agent-to-merchant-payments"
    assert (ROOT / "LICENSE").is_file()
    # The directory listing reads these fields.
    assert (PLUGIN / manifest["icon"]).is_file()
    for field in ("documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl"):
        assert manifest[field].startswith("https://"), field
    assert "logo" not in manifest


def test_the_repo_marketplace_lists_this_plugin():
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    [entry] = marketplace["plugins"]
    assert entry["name"] == _manifest()["name"]
    assert entry["source"] == "./claude-plugin"
    readme = (PLUGIN / "README.md").read_text()
    assert ("/plugin install %s --marketplace Snaplii-Inc/agent-to-merchant-payments" % entry["name"]) in readme


def test_skills_are_written_for_claude():
    for name in ("snaplii-cli", "snaplii-autopilot"):
        text = (PLUGIN / "skills" / name / "SKILL.md").read_text()
        assert text.startswith("---\nname: %s\n" % name), name
        assert "Cursor" not in text, name
        assert "<!--" not in text, name


def test_icon_matches_the_cursor_plugin_logo():
    assert (PLUGIN / _manifest()["icon"]).read_bytes() == (ROOT / "cursor-plugin" / "assets" / "logo.png").read_bytes()


def test_readme_says_what_the_plugin_runs_and_sends():
    readme = (PLUGIN / "README.md").read_text()
    for heading in ("## What this plugin runs, sends and fetches", "### Where it works"):
        assert heading in readme
    assert "aipayment.snaplii.com" in readme

"""The README must tell a third-party agent how sessions end and how to reconnect."""
from pathlib import Path

README = (Path(__file__).resolve().parents[1] / "README.md").read_text()


def test_readme_documents_session_states_and_reconnecting_by_host():
    section = README.split("### Sessions and reconnecting", 1)[1].split("\n## ", 1)[0]
    for phrase in ("reauth_required", "mcp_required", "no_persistent_storage", "SNAPLII_ALLOW_INSECURE=1",
                   "call_mcp_tool", "run_cli", "use_terminal_or_chat_key", "already_connected",
                   "invalid_key", "retry_auth_later", "--vault-auth", "has_valid_token"):
        assert phrase in section, phrase


def test_readme_does_not_offer_the_mcp_tool_to_shell_only_agents():
    assert "if the Snaplii MCP tools are available" in README
    assert "api_key_missing" in README


def test_readme_troubleshooting_and_requirements_cover_expiry_and_npx():
    assert "### Every Snaplii call answers `auth_required`, `reauth_required`, or `mcp_required`" in README
    requirements = README.split("## Requirements", 1)[1].split("\n## ", 1)[0]
    assert "npx" in requirements


def test_plugin_readme_connects_off_model_and_installs_what_the_plugin_runs():
    plugin = (Path(__file__).resolve().parents[1] / "clawhub-plugin" / "README.md").read_text()
    assert "uvx snaplii-mcp" in plugin
    assert "snaplii-cli==" not in plugin
    assert "follow its `next_action`, normally `snaplii_connect`" in plugin
    assert "Never ask for the API key in the chat" in plugin
    for stale in ("call `snaplii_init` with the user's API key", "token expired, re-run `snaplii_init`",
                  "Ask the user for their API key"):
        assert stale not in plugin, stale

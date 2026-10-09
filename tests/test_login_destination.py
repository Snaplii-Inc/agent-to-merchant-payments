"""Where an API key may go, and what the person entering it is told.

Sign-in is limited to the two Snaplii gateways. The hosted connect page must
sit on the gateway's own address, the person typing the key sees that
address, and fallback guidance stays honest without blocking the chat path.
"""

import asyncio
import io
import json
import sys
import time

import httpx
import keyring
import pytest
from keyring.backends.fail import Keyring

import server
from snaplii import auth, cli
from snaplii.cards import APIKEY_CARD_HTML
from snaplii.client import GatewayClient
from snaplii.config_store import ConfigStore
from snaplii.exceptions import ConfigError

PROD = "https://aipayment.snaplii.com"
STAGING = "https://aipay.stage.snaplii.com"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.setenv("SNAPLII_ALLOW_INSECURE", "1")
    monkeypatch.setenv("SNAPLII_CONFIG_PATH", str(tmp_path / "config.json"))
    for name in ("SNAPLII_BASE_URL", "SNAPLII_ELICIT_URL"):
        monkeypatch.delenv(name, raising=False)
    return ConfigStore(tmp_path / "config.json")


def _no_network(client):
    client._http = httpx.Client(transport=httpx.MockTransport(
        lambda request: pytest.fail("no request may leave for %s" % request.url)))
    return client


# ── which gateways may receive a key ──────────────────────────────────────────

@pytest.mark.parametrize("base_url", [PROD, PROD + "/", STAGING, STAGING + "/gw", "HTTPS://AIPAY.STAGE.SNAPLII.COM"])
def test_snaplii_gateways_are_allowed(base_url):
    assert auth.require_login_origin(base_url) in (PROD, STAGING)


@pytest.mark.parametrize("base_url", [
    "https://gateway.example",
    "http://localhost:8080",
    "http://127.0.0.1:18765",
    "https://aipayment.snaplii.com.evil.example",
    "https://evil.aipayment.snaplii.com",
    "https://aipayment.snaplii.com:444",
    "http://aipayment.snaplii.com",
])
def test_other_gateways_are_refused(base_url):
    with pytest.raises(ConfigError) as exc:
        auth.require_login_origin(base_url)
    assert PROD in exc.value.message and STAGING in exc.value.message


@pytest.mark.parametrize("base_url", ["https://gateway.example", "http://localhost:8080"])
def test_client_login_refuses_before_sending_the_key(store, base_url):
    client = _no_network(GatewayClient(base_url, store))
    with pytest.raises(ConfigError):
        client.login("agent-1", "snp_sk_live_SECRET")


def test_client_connect_poll_refuses_before_sending_the_eid(store):
    client = _no_network(GatewayClient("https://gateway.example", store))
    with pytest.raises(ConfigError):
        client.poll_connect_token("a" * 32)


def test_cli_init_refuses_before_reading_the_key(store, monkeypatch, capsys):
    monkeypatch.setattr(cli, "ConfigStore", lambda: store)
    stdin = io.StringIO("snp_sk_live_SECRET\n")
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "argv", ["snaplii", "--base-url", "https://gateway.example", "init"])
    with pytest.raises(SystemExit) as exc:
        cli._cli()
    assert exc.value.code == 1
    output = capsys.readouterr()
    assert PROD in output.err and "SECRET" not in output.err + output.out
    assert stdin.read() == "snp_sk_live_SECRET\n"


def test_terminal_prompt_names_the_gateway(store, monkeypatch, capsys, httpx_mock):
    monkeypatch.setattr(cli, "ConfigStore", lambda: store)
    monkeypatch.setattr(sys, "argv", ["snaplii", "--base-url", STAGING + "/gw", "init"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    shown = []

    def prompt(text, **kwargs):
        shown.append(text)
        assert kwargs.get("hide_input") is True
        return "synthetic-api-key"

    monkeypatch.setattr("snaplii.commands.init.click.prompt", prompt)
    httpx_mock.add_response(method="POST", url=STAGING + "/gw/v2/auth/token",
                            json={"access_token": "synthetic-token", "expires_in": 600})
    cli._cli()
    assert shown and STAGING in shown[0]
    assert json.loads(capsys.readouterr().out)["has_valid_token"] is True


# ── the hosted connect page must be on the gateway's own address ─────────────

def test_connect_page_defaults_to_the_gateway(store, monkeypatch):
    monkeypatch.setenv("SNAPLII_BASE_URL", STAGING + "/gw")
    assert server._elicit_url() == STAGING + "/gw/connect"


@pytest.mark.parametrize("page", [STAGING + "/gw/connect?lang=en", STAGING + "/connect"])
def test_connect_page_override_on_the_same_address_is_kept(store, monkeypatch, page):
    monkeypatch.setenv("SNAPLII_BASE_URL", STAGING + "/gw")
    monkeypatch.setenv("SNAPLII_ELICIT_URL", page)
    assert server._elicit_url() == page


@pytest.mark.parametrize("page", [
    "https://evil.example/connect",
    STAGING + "/connect",
    PROD + "/connect#x",
    "https://user@aipayment.snaplii.com/connect",
    PROD + "/connect?eid=" + "a" * 32,
    "http://aipayment.snaplii.com/connect",
])
def test_connect_page_elsewhere_is_refused(store, monkeypatch, page):
    monkeypatch.setenv("SNAPLII_ELICIT_URL", page)
    with pytest.raises(ConfigError):
        server._elicit_url()


def test_connect_page_from_config_is_checked_too(store, monkeypatch):
    store.set("elicit_url", "https://evil.example/connect")
    with pytest.raises(ConfigError):
        server._elicit_url()


def test_connect_page_needs_an_allowed_gateway(store, monkeypatch):
    monkeypatch.setenv("SNAPLII_BASE_URL", "https://gateway.example")
    with pytest.raises(ConfigError):
        server._elicit_url()


def test_instinct_never_hands_out_a_vault_fill_for_another_site(store, monkeypatch):
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    monkeypatch.setattr(server, "_update_notice", lambda: None)
    monkeypatch.setenv("SNAPLII_ELICIT_URL", "https://evil.example/connect")
    monkeypatch.setattr(server, "ConfigStore", lambda: ConfigStore(store._path, runtime="mcp"))
    out = json.loads(asyncio.run(server.call_tool("snaplii_connect", {}))[0].text)
    assert "connect_url" not in out and "vault_entry" not in out
    assert out["error"] == "Configuration error"


# ── what the person and the agent are told ────────────────────────────────────

class _Disconnected:
    def __init__(self, storage):
        self.storage = storage

    def auth_status(self, *, origin):
        return {"has_valid_token": False, "host": "unknown", "credential_storage": self.storage}

    def get(self, key, default=None):
        return default


def _connect_text(monkeypatch, storage, route="text"):
    monkeypatch.setattr(server, "_connect_route", lambda: route)
    monkeypatch.setattr(server, "ConfigStore", lambda: _Disconnected(storage))
    monkeypatch.setattr(server, "_base_url", lambda: PROD)
    return json.loads(asyncio.run(server.call_tool("snaplii_connect", {}))[0].text)


@pytest.mark.parametrize("route", ["text", "card"])
def test_fallback_offers_terminal_first_and_keeps_the_chat_path(monkeypatch, route):
    out = _connect_text(monkeypatch, "system keychain", route)
    message = out["message"]
    assert "snaplii init" in message and "snaplii_init" in message
    assert message.index("snaplii init") < message.index("snaplii_init")
    assert "equal" not in message.lower()
    assert "do not describe" not in message.lower()


def test_memory_only_session_does_not_send_the_user_to_a_terminal(monkeypatch):
    out = _connect_text(monkeypatch, "process memory")
    assert "snaplii_init" in out["message"]
    assert "snaplii init'" not in out["message"] and "run 'snaplii init" not in out["message"]


def test_raw_key_tool_no_longer_calls_the_key_safe_to_accept():
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    description = tools["snaplii_init"].description
    assert "SAFE" not in description
    assert "never stored" in description


def test_card_shows_where_the_key_goes(monkeypatch):
    monkeypatch.setattr(server, "_base_url", lambda: STAGING + "/gw")
    html = server._card_html_for_client()
    assert "aipay.stage.snaplii.com" in html


def test_card_ignores_messages_from_other_windows_and_clears_on_error():
    listener = APIKEY_CARD_HTML.split('window.addEventListener("message"', 1)[1].split("});", 1)[0]
    assert "event.source !== window.parent" in listener
    failure = APIKEY_CARD_HTML.split(".catch(function (err)", 1)[1].split("});", 1)[0]
    assert 'inputEl.value = ""' in failure


def test_elicit_message_names_the_page_host(monkeypatch):
    captured = {}

    class Session:
        async def elicit_url(self, message, url, elicitation_id):
            captured["message"] = message
            return type("R", (), {"action": "decline"})()

    class App:
        request_context = type("C", (), {"session": Session()})()

    monkeypatch.setattr(server, "_connect_route", lambda: "elicit")
    monkeypatch.setattr(server, "ConfigStore", lambda: _Disconnected("system keychain"))
    monkeypatch.setattr(server, "_elicit_url", lambda: PROD + "/connect")
    monkeypatch.setattr(server, "app", App())
    asyncio.run(server.call_tool("snaplii_connect", {}))
    assert "aipayment.snaplii.com" in captured["message"]


# ── a session saved without its gateway is not reused ────────────────────────

def test_token_without_a_recorded_gateway_is_not_reused(store):
    store.commit_session("session-token", 3600, agent_id="agent-1", auth_method="api_key", token_origin=PROD)
    data = json.loads(store._path.read_text())
    data.pop("token_origin")
    store._path.write_text(json.dumps(data))
    assert store.get_cached_token(origin=PROD) is None
    assert store.get_cached_token() == "session-token"

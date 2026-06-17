"""The MCP Apps API-key card: the key reaches the server off the model context.

Covers the card resource, the app-only submit tool, and that authentication
never echoes the key back. Card *rendering* itself is host-side and verified
manually in Claude Desktop.
"""

import asyncio
import json

import server

from snaplii.cards import APIKEY_RES_URI, MCP_APP_MIME, SUBMIT_TOOL, APIKEY_CARD_HTML


class FakeClient:
    def __init__(self):
        self.logged_in = None

    def login(self, agent_id, api_key):
        self.logged_in = (agent_id, api_key)
        return {"access_token": "jwt", "country": "CA"}


class FakeStore:
    def set(self, key, value):
        pass  # no-op so tests never touch the real ~/.snaplii/config.json


def _wire(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(server, "_get_client", lambda: client)
    monkeypatch.setattr(server, "ConfigStore", FakeStore)
    return client


def _call(name, args):
    res = asyncio.run(server.call_tool(name, args))
    return json.loads(res[0].text)


# ── the card resource ─────────────────────────────────────────────────────────

def test_read_resource_serves_card_with_app_mime():
    res = asyncio.run(server.read_resource(APIKEY_RES_URI))
    assert res[0].mime_type == MCP_APP_MIME == "text/html;profile=mcp-app"
    assert res[0].content == APIKEY_CARD_HTML


def test_unknown_resource_raises():
    try:
        asyncio.run(server.read_resource("ui://snaplii/nope.html"))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_card_html_targets_app_only_submit_tool_and_masks_input():
    html = APIKEY_CARD_HTML
    assert SUBMIT_TOOL in html                 # card calls the app-only submit tool
    assert 'type="password"' in html           # key input is masked in the UI
    assert "tools/call" in html
    # No real secret baked into the static card.
    assert "snp_sk_live_" not in html or "snp_sk_live_…" in html


# ── tool metadata: the security linchpin ──────────────────────────────────────

def test_submit_tool_is_app_only_and_connect_carries_card():
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    # App-only: model can neither see nor call the submit tool.
    assert tools[SUBMIT_TOOL].meta["ui"]["visibility"] == ["app"]
    # Connect tool points the host at the card resource.
    assert tools["snaplii_connect"].meta["ui"]["resourceUri"] == APIKEY_RES_URI


# ── authentication via the off-model submit ───────────────────────────────────

def test_submit_authenticates_without_echoing_key(monkeypatch):
    client = _wire(monkeypatch)
    res = asyncio.run(server.call_tool(SUBMIT_TOOL, {"api_key": "snp_sk_live_SECRET123"}))
    text = res[0].text
    out = json.loads(text)

    assert out["status"] == "authenticated"
    assert out["agent_id"].startswith("agent-")
    # The key was used to log in...
    assert client.logged_in[1] == "snp_sk_live_SECRET123"
    # ...but never echoed back to the model.
    assert "SECRET123" not in text


def test_submit_empty_key_is_rejected(monkeypatch):
    _wire(monkeypatch)
    out = _call(SUBMIT_TOOL, {"api_key": "  "})
    assert out["error"] == "api_key_required"


def test_init_and_submit_share_one_auth_path(monkeypatch):
    # snaplii_init (fallback) and the card submit must behave identically.
    client = _wire(monkeypatch)
    a = _call("snaplii_init", {"api_key": "snp_sk_live_K"})
    b = _call(SUBMIT_TOOL, {"api_key": "snp_sk_live_K"})
    assert a == b  # both paths return the identical auth result
    assert a["status"] == "authenticated"
    assert a["agent_id"]
    assert "daily limit" in a["notice"]  # one-time consent notice on connect


def test_auth_fails_when_gateway_returns_no_token(monkeypatch):
    # A bogus key the gateway rejects (no access_token) must NOT report success.
    class NoTokenClient:
        def login(self, agent_id, api_key):
            return {"rspMsgCd": "MCA20101", "rspMsgInf": "Invalid API key"}
    monkeypatch.setattr(server, "_get_client", lambda: NoTokenClient())
    monkeypatch.setattr(server, "ConfigStore", FakeStore)
    out = _call(SUBMIT_TOOL, {"api_key": "1"})
    assert out.get("status") != "authenticated"
    assert out["error"] == "auth_failed"


def test_auth_fails_when_login_raises(monkeypatch):
    from snaplii.exceptions import GatewayApiError

    class RaisingClient:
        def login(self, agent_id, api_key):
            raise GatewayApiError(401, {"friendly_message": "This API key has been deactivated."}, "/v2/auth/token")
    monkeypatch.setattr(server, "_get_client", lambda: RaisingClient())
    monkeypatch.setattr(server, "ConfigStore", FakeStore)
    out = _call(SUBMIT_TOOL, {"api_key": "snp_sk_live_x"})
    assert out["error"] == "auth_failed"
    assert "deactivated" in out["message"]


# ── connect routing: card / URL-elicitation / text, by client capability ──────

from types import SimpleNamespace


def _caps(experimental=None, elicitation=None):
    return SimpleNamespace(experimental=experimental, elicitation=elicitation)


def test_route_card_when_host_advertises_ui():
    caps = _caps(experimental={"io.modelcontextprotocol/ui": {}})
    assert server._route_for_caps(caps) == "card"


def test_route_elicit_only_when_url_mode_supported():
    # URL mode present → elicit; form-only → card (spec forbids key via form).
    assert server._route_for_caps(_caps(elicitation=SimpleNamespace(url={}, form={}))) == "elicit"
    assert server._route_for_caps(_caps(elicitation=SimpleNamespace(url=None, form={}))) == "card"


def test_route_defaults_to_card_when_no_positive_elicit_signal():
    # No surface advertised → default to card, NOT text: the card_requested message
    # self-describes and the card still renders via the tool's own _meta.ui.
    assert server._route_for_caps(_caps()) == "card"
    # form-only elicitation is not enough (spec forbids key via form) → card.
    assert server._route_for_caps(_caps(elicitation=SimpleNamespace(url=None, form={}))) == "card"


def test_connect_card_route_warns_against_pasting_key(monkeypatch):
    monkeypatch.setattr(server, "_connect_route", lambda: "card")
    out = _call("snaplii_connect", {})
    assert out["status"] == "card_requested"
    assert "paste" in out["message"].lower()
    assert "snaplii init" in out["message"]


def test_connect_elicit_route_unconfigured_falls_back_to_cli(monkeypatch):
    # Client can do URL-mode elicitation, but the hosted page (#2) isn't set up.
    monkeypatch.setattr(server, "_connect_route", lambda: "elicit")
    monkeypatch.setattr(server, "_elicit_url", lambda: None)
    out = _call("snaplii_connect", {})
    assert out["status"] == "connect_unconfigured"
    assert "snaplii init" in out["message"]


def test_connect_elicit_route_with_url_opens_secure_page(monkeypatch):
    # When the page IS configured, fire URL-mode elicitation and report on accept.
    monkeypatch.setattr(server, "_connect_route", lambda: "elicit")
    monkeypatch.setattr(server, "_elicit_url", lambda: "https://connect.snaplii.com/x")

    captured = {}

    class FakeSession:
        async def elicit_url(self, message, url, elicitation_id):
            captured["url"] = url
            captured["id"] = elicitation_id
            return SimpleNamespace(action="accept")

    class FakeApp:
        @property
        def request_context(self):
            return SimpleNamespace(session=FakeSession())

    class TokenStore:
        def get_cached_token(self):
            return "jwt"

    monkeypatch.setattr(server, "app", FakeApp())
    monkeypatch.setattr(server, "ConfigStore", TokenStore)
    out = _call("snaplii_connect", {})
    assert out["status"] == "authenticated"
    assert captured["url"] == "https://connect.snaplii.com/x"
    assert captured["id"]  # a correlation id was generated

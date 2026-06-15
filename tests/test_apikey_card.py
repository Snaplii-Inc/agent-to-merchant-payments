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
    assert a == b == {"status": "authenticated", "agent_id": a["agent_id"]}


def test_connect_fallback_tells_model_not_to_paste_key(monkeypatch):
    _wire(monkeypatch)
    out = _call("snaplii_connect", {})
    assert out["status"] == "card_requested"
    assert "paste" in out["message"].lower()

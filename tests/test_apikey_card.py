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


def test_card_keeps_full_success_for_codex_no_collapse(monkeypatch):
    # Default card collapses to the slim bar (NO_COLLAPSE=false).
    assert "var NO_COLLAPSE = false;" in APIKEY_CARD_HTML
    # Codex drops downward resize → served card keeps the full success card.
    codex_app = SimpleNamespace(request_context=SimpleNamespace(session=SimpleNamespace(
        client_params=SimpleNamespace(clientInfo=SimpleNamespace(name="codex-mcp-client")))))
    monkeypatch.setattr(server, "app", codex_app)
    html = server._card_html_for_client()
    assert "var NO_COLLAPSE = true;" in html
    assert "var NO_COLLAPSE = false;" not in html


def test_card_default_collapse_for_other_clients(monkeypatch):
    other_app = SimpleNamespace(request_context=SimpleNamespace(session=SimpleNamespace(
        client_params=SimpleNamespace(clientInfo=SimpleNamespace(name="claude-ai")))))
    monkeypatch.setattr(server, "app", other_app)
    assert server._card_html_for_client() == APIKEY_CARD_HTML  # unchanged → collapses


def test_card_self_checks_connection_on_load():
    # On (re)load the card queries snaplii_config_show and collapses to the
    # "✓ Connected" state if already authenticated (avoids re-showing a live form
    # when revisiting an old conversation).
    html = APIKEY_CARD_HTML
    assert "snaplii_config_show" in html
    assert "has_valid_token" in html
    assert "checkAlreadyConnected" in html


# ── tool metadata: the security linchpin ──────────────────────────────────────

def test_submit_tool_is_app_only_and_connect_carries_card():
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    # App-only: model can neither see nor call the submit tool.
    assert tools[SUBMIT_TOOL].meta["ui"]["visibility"] == ["app"]
    # Connect tool ALWAYS points the host at the card resource (no state-dependent
    # _meta — host caches list_tools, so varying it by connection state goes stale).
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


def _caps(experimental=None, elicitation=None, extensions=None):
    return SimpleNamespace(experimental=experimental, elicitation=elicitation,
                           extensions=extensions)


def test_route_card_when_host_advertises_ui_extensions():
    # Real MCP Apps hosts (claude-ai/Claude desktop, VS Code) advertise the ui cap
    # under capabilities.extensions["io.modelcontextprotocol/ui"]. Detect it there.
    caps = _caps(extensions={"io.modelcontextprotocol/ui": {"mimeTypes": ["text/html;profile=mcp-app"]}})
    assert server._route_for_caps(caps) == "card"


def test_route_card_when_host_advertises_ui_experimental():
    # Some hosts may put it under experimental — still card.
    assert server._route_for_caps(_caps(experimental={"io.modelcontextprotocol/ui": {}})) == "card"


def test_route_card_wins_over_elicitation():
    # VS Code advertises BOTH a ui extension AND elicitation. Card must win — it
    # renders the secure card; it must not be mis-routed to elicit.
    caps = _caps(extensions={"io.modelcontextprotocol/ui": {}},
                 elicitation=SimpleNamespace(url=None, form={}))
    assert server._route_for_caps(caps) == "card"


def test_route_elicit_unless_form_only():
    # Explicit URL mode → elicit (codex/cursor). A url-capable cap elicits even when
    # form is also present. Form-ONLY (form present, url absent) → text: the spec
    # forbids collecting a secret via form, so there's no usable off-model path.
    assert server._route_for_caps(_caps(elicitation=SimpleNamespace(url={}, form={}))) == "elicit"
    assert server._route_for_caps(_caps(elicitation=SimpleNamespace(url={}, form=None))) == "elicit"
    assert server._route_for_caps(_caps(elicitation=SimpleNamespace(url=None, form={}))) == "text"


def test_route_bare_elicitation_elicits_nothing_goes_text():
    # claude-code advertises a bare ElicitationCapability(form=None, url=None). The
    # form/url sub-fields are non-standard; per the docs claude-code supports URL mode,
    # and the spec picks mode per-request — so a bare cap routes to elicit and the
    # request-time handler falls back to terminal only if the client returns -32602.
    assert server._route_for_caps(_caps(elicitation=SimpleNamespace(url=None, form=None))) == "elicit"
    # Nothing advertised at all → terminal (no card host, no elicitation cap).
    assert server._route_for_caps(_caps()) == "text"


def test_connect_card_route_warns_against_pasting_key(monkeypatch):
    monkeypatch.setattr(server, "_connect_route", lambda: "card")
    monkeypatch.setattr(server, "ConfigStore", _DisconnectedStore)  # not yet connected
    out = _call("snaplii_connect", {})
    assert out["status"] == "card_requested"
    assert "paste" in out["message"].lower()
    assert "snaplii init" in out["message"]


class _FakeSession:
    """elicit_url stub: records the page URL + eid, returns the given action."""
    def __init__(self, action, captured):
        self._action = action
        self._captured = captured

    async def elicit_url(self, message, url, elicitation_id):
        self._captured["url"] = url
        self._captured["eid"] = elicitation_id
        return SimpleNamespace(action=self._action)


class _FakeApp:
    def __init__(self, session):
        self._session = session

    @property
    def request_context(self):
        return SimpleNamespace(session=self._session)


class _DisconnectedStore:
    """ConfigStore stub with NO cached token, so the already-connected guard in
    snaplii_connect passes through to the routing/flow under test."""
    def get_cached_token(self): return None
    def get(self, k, d=None): return d
    def set(self, k, v): pass
    def cache_token(self, token, expires_in): pass


def _wire_elicit(monkeypatch, action, captured):
    monkeypatch.setattr(server, "_connect_route", lambda: "elicit")
    monkeypatch.setattr(server, "_elicit_url", lambda: "https://connect.snaplii.com/connect")
    monkeypatch.setattr(server, "app", _FakeApp(_FakeSession(action, captured)))
    # Disconnected by default so the already-connected guard doesn't short-circuit.
    monkeypatch.setattr(server, "ConfigStore", _DisconnectedStore)
    # No real waiting between polls in tests.
    monkeypatch.setattr(server, "_ELICIT_POLL_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(server, "_ELICIT_POLL_INTERVAL_S", 0)


def test_connect_elicit_opens_page_polls_and_caches_token(monkeypatch):
    captured = {}
    _wire_elicit(monkeypatch, "accept", captured)

    class FakeClient:
        def poll_connect_token(self, eid):
            captured["polled_eid"] = eid
            return {"access_token": "jwt-x", "expires_in": 1800, "country": "ca"}

    cached = {}

    class FakeStore:
        def get_cached_token(self): return None  # not yet connected → guard passes
        def cache_token(self, token, expires_in): cached["token"] = token; cached["exp"] = expires_in
        def set(self, k, v): cached[k] = v
        def get(self, k, d=None): return d

    monkeypatch.setattr(server, "_get_client", lambda: FakeClient())
    monkeypatch.setattr(server, "ConfigStore", FakeStore)

    out = _call("snaplii_connect", {})
    assert out["status"] == "authenticated"
    # eid is generated and appended to the page URL, then polled for.
    assert captured["eid"] and captured["eid"] in captured["url"]
    assert captured["polled_eid"] == captured["eid"]
    # Token cached like login(): token + expiry + uppercased country.
    assert cached["token"] == "jwt-x"
    assert cached["exp"] == 1800
    assert cached["country"] == "CA"


def test_connect_elicit_declined_does_not_authenticate(monkeypatch):
    captured = {}
    _wire_elicit(monkeypatch, "decline", captured)
    out = _call("snaplii_connect", {})
    assert out["status"] == "declined"


def test_connect_elicit_pending_when_token_never_arrives(monkeypatch):
    captured = {}
    _wire_elicit(monkeypatch, "accept", captured)

    class FakeClient:
        def poll_connect_token(self, eid):
            return None  # never ready

    monkeypatch.setattr(server, "_get_client", lambda: FakeClient())
    out = _call("snaplii_connect", {})
    assert out["status"] == "pending"
    assert "snaplii init" in out["message"]


# ── _CARD_CLIENT_NAMES: name-based card allowlist (Codex) ──────────────────────

def test_route_card_for_allowlisted_client_without_ui_cap():
    # Codex advertises ONLY elicitation (no ui ext) yet renders the card. The name
    # allowlist routes it to card so we don't also fire URL-mode elicitation.
    caps = _caps(elicitation=SimpleNamespace(url={}, form={}))
    assert server._route_for_caps(caps, SimpleNamespace(name="codex-mcp-client")) == "card"


def test_route_allowlist_is_case_insensitive():
    caps = _caps(elicitation=SimpleNamespace(url={}, form={}))
    assert server._route_for_caps(caps, SimpleNamespace(name="Codex-MCP-Client")) == "card"


def test_route_non_allowlisted_url_client_still_elicits():
    # A url-mode client NOT on the allowlist (e.g. cursor) keeps elicit.
    caps = _caps(elicitation=SimpleNamespace(url={}, form={}))
    assert server._route_for_caps(caps, SimpleNamespace(name="cursor")) == "elicit"


def test_route_without_client_info_unchanged():
    # No clientInfo → behaves exactly as the capability-only rule (elicit here).
    caps = _caps(elicitation=SimpleNamespace(url={}, form={}))
    assert server._route_for_caps(caps, None) == "elicit"


# ── already-connected guard (no force) ────────────────────────────────────────

def test_connect_short_circuits_when_already_connected(monkeypatch):
    class ConnectedStore:
        def get_cached_token(self): return "cached-jwt"
        def get(self, k, d=None): return d
        def set(self, k, v): pass
    monkeypatch.setattr(server, "ConfigStore", ConnectedStore)
    # The guard must return BEFORE routing — record any route call to prove it didn't.
    calls = []
    monkeypatch.setattr(server, "_connect_route", lambda: calls.append(1) or "card")
    out = _call("snaplii_connect", {})
    assert out["status"] == "already_connected"
    assert calls == []  # routing never reached


def test_connect_proceeds_when_not_connected(monkeypatch):
    monkeypatch.setattr(server, "ConfigStore", _DisconnectedStore)
    monkeypatch.setattr(server, "_connect_route", lambda: "card")
    out = _call("snaplii_connect", {})
    assert out["status"] == "card_requested"  # guard passed, normal card route ran


# ── region from stored config: no asking, surfaced for the model ──────────────

class _CountryStore:
    """ConfigStore stub that knows the account country (cached at login)."""
    def get(self, k, d=None): return "CA" if k == "country" else d
    def set(self, k, v): pass


def test_browse_tags_surfaces_account_country(monkeypatch):
    class Client:
        def get_all_card_tags(self, channel="HOME_PAGE"): return {"tags": ["coffee"]}
    monkeypatch.setattr(server, "_get_client", lambda: Client())
    monkeypatch.setattr(server, "ConfigStore", _CountryStore)
    out = _call("snaplii_browse_tags", {})
    # account_country is surfaced so the agent filters by region WITHOUT asking.
    assert out["account_country"] == "CA"
    assert out["tags"] == ["coffee"]


def test_balance_labels_currency_from_stored_country(monkeypatch):
    class Client:
        def get_balance(self): return {"data": {"balance": 100}}
    monkeypatch.setattr(server, "_get_client", lambda: Client())
    monkeypatch.setattr(server, "ConfigStore", _CountryStore)
    out = _call("snaplii_balance", {})  # NOTE: no country argument passed
    assert out["currency"] == "CAD"
    assert out["balance"] == 100


def test_balance_falls_back_when_country_unknown(monkeypatch):
    class Client:
        def get_balance(self): return {"data": {"balance": 50}}
    class Store:
        def get(self, k, d=None): return d  # no stored country
        def set(self, k, v): pass
    monkeypatch.setattr(server, "_get_client", lambda: Client())
    monkeypatch.setattr(server, "ConfigStore", Store)
    out = _call("snaplii_balance", {})
    assert "currency" not in out
    assert "currency_note" in out

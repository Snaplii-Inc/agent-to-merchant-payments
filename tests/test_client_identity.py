"""Every gateway request from the CLI or the MCP server names the official client, so the
gateway can tell supported traffic from agents calling the API directly. Telemetry only:
the header is easy to forge and is never a security control."""
import keyring
import pytest
from keyring.backends.fail import Keyring

from snaplii.client import GatewayClient
from snaplii.config_store import ConfigStore

ORIGIN = "https://aipayment.snaplii.com"


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    clients = []

    def make(runtime):
        store = ConfigStore(tmp_path / ("config-%s.json" % runtime))
        store.commit_session("session-token", 3600, agent_id="agent-1", auth_method="api_key", token_origin=ORIGIN)
        store.runtime = runtime  # after the commit: a CLI runtime refuses memory-only sessions
        client = GatewayClient(ORIGIN, store)
        clients.append(client)
        return client
    yield make
    for client in clients:
        client._http.close()


@pytest.mark.parametrize("runtime", ["cli", "mcp"])
def test_requests_name_the_client_and_its_runtime(make_client, httpx_mock, runtime):
    httpx_mock.add_response(status_code=204)
    make_client(runtime).poll_connect_token("abc123")
    header = httpx_mock.get_request().headers["X-Snaplii-Client"]
    assert header.startswith("snaplii-cli/") and header.endswith("(%s)" % runtime)


def test_authenticated_requests_carry_the_header(make_client, httpx_mock):
    httpx_mock.add_response(json={"rspMsgCd": "MCA00000", "data": {"balance": "1.00"}})
    make_client("mcp").get_balance()
    assert httpx_mock.get_request().headers["X-Snaplii-Client"].endswith("(mcp)")

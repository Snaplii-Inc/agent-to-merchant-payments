"""Transport failures on money-moving requests and business-error reasons."""

import json

import httpx
import keyring
import pytest
from keyring.backends.fail import Keyring

from snaplii.client import GatewayClient
from snaplii.config_store import ConfigStore
from snaplii.exceptions import GatewayApiError, GatewayConnectionError

ORIGIN = "https://aipayment.snaplii.com"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    store = ConfigStore(tmp_path / "config.json")
    store.commit_session("session-token", 3600, agent_id="agent-1",
                         auth_method="api_key", token_origin=ORIGIN)
    client = GatewayClient(ORIGIN, store)
    yield client
    client._http.close()


def _raising_transport(exc):
    def handler(request):
        raise exc
    return httpx.MockTransport(handler)


@pytest.mark.parametrize("exc", [
    httpx.ReadTimeout("read timed out"),
    httpx.RemoteProtocolError("server disconnected"),
    httpx.ReadError("connection reset"),
], ids=["read-timeout", "remote-protocol", "read-error"])
def test_purchase_failure_after_send_is_reported_as_indeterminate(client, exc):
    client._http = httpx.Client(transport=_raising_transport(exc))
    with pytest.raises(GatewayConnectionError) as info:
        client.create_order_and_pay("CB1-CT1", "10")
    out = info.value.to_dict()
    assert out["outcome"] == "indeterminate"
    assert "may or may not" in out["error"]
    assert "retry" in out["retry_hint"].lower()
    assert str(exc) not in json.dumps(out)


@pytest.mark.parametrize("exc", [
    httpx.ConnectError("connection refused"),
    httpx.ConnectTimeout("connect timed out"),
], ids=["connect-error", "connect-timeout"])
def test_purchase_failure_before_send_stays_definite(client, exc):
    client._http = httpx.Client(transport=_raising_transport(exc))
    with pytest.raises(GatewayConnectionError) as info:
        client.create_order_and_pay("CB1-CT1", "10")
    out = info.value.to_dict()
    assert out["error"] == "Connection failed"
    assert out["outcome"] == "not_sent"
    assert "retry_hint" not in out


def test_non_auth_business_error_keeps_its_reason():
    out = GatewayApiError(400, {"message": "price exceeds daily limit"}, "/v2/purchase").to_dict()
    assert "price exceeds daily limit" in out["error"]


def test_auth_endpoint_error_never_copies_upstream_text():
    out = GatewayApiError(400, {"message": "synthetic-secret"}, "/v2/auth/token").to_dict()
    assert "synthetic-secret" not in json.dumps(out)

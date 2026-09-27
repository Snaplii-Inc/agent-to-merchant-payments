import json

import httpx
import keyring
import pytest
from keyring.backends.fail import Keyring

from snaplii.client import GatewayClient
from snaplii.config_store import ConfigStore
from snaplii.exceptions import AuthError, GatewayApiError, TransferApiError

ORIGIN = "https://aipayment.snaplii.com"


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    store = ConfigStore(tmp_path / "config.json")
    store.commit_session("old-token", 3600, agent_id="agent-1", auth_method="vault", token_origin=ORIGIN)
    client = GatewayClient(ORIGIN, store)
    yield client, store
    client._http.close()


def test_origin_mismatch_blocks_network_without_deleting_session(session):
    _, store = session
    client = GatewayClient("https://other.example", store)
    client._http = httpx.Client(transport=httpx.MockTransport(lambda req: pytest.fail("must not send token")))
    with pytest.raises(AuthError):
        client.get_balance()
    assert store.get_cached_token(origin=ORIGIN) == "old-token"


@pytest.mark.parametrize("operation,method,path,error_type", [
    (lambda c: c.get_balance(), "GET", "/v2/balance", GatewayApiError),
    (lambda c: c.quote_order("item", "10"), "POST", "/v2/quote", GatewayApiError),
    (lambda c: c._delete("/v2/test"), "DELETE", "/v2/test", GatewayApiError),
    (lambda c: c.transfer_create("+14165550123", "10", idempotency_key="retry-key"), "POST", "/v2/transfers", TransferApiError),
])
@pytest.mark.parametrize("status,code", [(401, ""), (200, "MCAP9999"), (200, "USR_NOT_EXIST")])
def test_rejected_session_is_cleared_without_replay(session, httpx_mock, operation, method, path, error_type, status, code):
    client, store = session
    httpx_mock.add_response(method=method, url=ORIGIN + path, status_code=status,
                            json={"rspMsgCd": code, "code": code, "message": "synthetic-secret"})
    with pytest.raises(error_type) as exc:
        operation(client)
    output = exc.value.to_dict()
    assert output["auth_state"] == "reauth_required"
    assert output["next_action"]["argv"][-1] == "--vault-auth"
    assert "synthetic-secret" not in json.dumps(output)
    if error_type is TransferApiError:
        assert output["idempotency_key"] == "retry-key"
    assert store.get_cached_token() is None
    assert store.get("agent_id") == "agent-1"
    assert len(httpx_mock.get_requests()) == 1


def test_scope_denied_does_not_clear_session(session, httpx_mock):
    client, store = session
    httpx_mock.add_response(status_code=403, json={"rspMsgCd": "SCOPE_DENIED"})
    with pytest.raises(GatewayApiError):
        client.get_balance()
    assert store.get_cached_token() == "old-token"


def test_late_rejection_does_not_clear_new_session(session, httpx_mock):
    client, store = session

    def late_response(request):
        store.commit_session("new-token", 3600, agent_id="agent-2", auth_method="vault", token_origin=ORIGIN)
        return httpx.Response(401, json={})

    httpx_mock.add_callback(late_response)
    with pytest.raises(GatewayApiError):
        client.get_balance()
    assert store.get_cached_token() == "new-token"
    assert len(httpx_mock.get_requests()) == 1


@pytest.mark.parametrize("operation,error_type", [
    (lambda c: c.get_balance(), GatewayApiError),
    (lambda c: c.transfer_create("+14165550123", "10", idempotency_key="recovery-key"), TransferApiError),
])
def test_rejection_with_broken_config_preserves_the_request_error(session, httpx_mock, operation, error_type):
    client, store = session

    def corrupt_config_while_request_is_in_flight(request):
        store.path.write_text("invalid JSON synthetic-secret")
        return httpx.Response(401, json={"message": "synthetic-secret"})

    httpx_mock.add_callback(corrupt_config_while_request_is_in_flight)
    with pytest.raises(error_type) as exc:
        operation(client)
    output = exc.value.to_dict()
    assert output["auth_state"] == "session_cache_failed"
    assert output["reason_code"] == "session_clear_failed"
    assert output["next_action"] == {"type": "stop", "reason": "session_cache_failed"}
    if error_type is TransferApiError:
        assert output["idempotency_key"] == "recovery-key"
        assert "same idempotency key" in output["retry_hint"].lower()
    assert "synthetic-secret" not in json.dumps(output)
    assert len(httpx_mock.get_requests()) == 1

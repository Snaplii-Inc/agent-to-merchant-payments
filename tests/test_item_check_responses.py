"""The item check and MCAP2107 through the real response path.

MCAP2107: the gateway rejected the item_id, so nothing was bought at any HTTP status,
and the agent gets the rethink-and-retry hint. After a failed brand detail lookup, the
account's brand lists decide between a wrong item_id and an unverifiable one."""

import json

import httpx
import keyring
import pytest
from keyring.backends.fail import Keyring

from snaplii.client import GatewayClient
from snaplii.config_store import ConfigStore
from snaplii.exceptions import GatewayApiError, ItemCheckUnavailableError, ItemIdError

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


def _answer(client, status, text):
    client._http = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, text=text)))


_CALLS = [
    lambda c: c.quote_order("CB1-CT1", "10"),
    lambda c: c.create_order_and_pay("CB1-CT1", "10"),
]


@pytest.mark.parametrize("status", [200, 400, 422, 500, 502, 503])
@pytest.mark.parametrize("call", _CALLS, ids=["quote", "purchase"])
def test_mcap2107_is_a_definite_item_rejection_at_any_status(client, call, status):
    _answer(client, status, json.dumps({"rspMsgCd": "MCAP2107", "rspMsgInf": "item invalid"}))
    with pytest.raises(GatewayApiError) as info:
        call(client)
    out = info.value.to_dict()
    assert out["error_code"] == "MCAP2107" and out["status_code"] == status
    assert "outcome" not in out and "reason_code" not in out
    assert "rejected this item_id" in out["error"]
    assert out["retry_hint"].startswith("The gateway refused this item_id, so nothing was charged.")
    assert "Rethink the parameters" in out["retry_hint"]


@pytest.mark.parametrize("text", ["<html>401</html>", json.dumps({"rspMsgCd": "MCAP2107"})])
@pytest.mark.parametrize("call", _CALLS, ids=["quote", "purchase"])
def test_a_401_always_rejects_the_session(client, call, text):
    # Whatever a 401 carries, it is a session rejection, never an item correction.
    _answer(client, 401, text)
    with pytest.raises(GatewayApiError) as info:
        call(client)
    out = info.value.to_dict()
    assert out["reason_code"] == "session_rejected" and "retry_hint" not in out
    assert client._config.get_cached_token() is None


@pytest.mark.parametrize("text", [
    json.dumps({"rspMsgCd": " MCAP2107 "}),
    json.dumps({"rspMsgCd": ["MCAP2107"]}),
    json.dumps({"code": "MCAP2107"}),
    "MCAP2107",
    "",
])
@pytest.mark.parametrize("status", [500, 502])
def test_a_purchase_5xx_that_does_not_clearly_say_mcap2107_stays_indeterminate(client, status, text):
    _answer(client, status, text)
    with pytest.raises(GatewayApiError) as info:
        client.create_order_and_pay("CB1-CT1", "10")
    out = info.value.to_dict()
    assert out["outcome"] == "indeterminate"
    assert "Rethink" not in out["retry_hint"]


def _route(client, brand_status, list_status, home=("CB_OTHER",), gift=("CB_OTHER",)):
    def handler(request):
        if request.url.path == "/v2/card-brands":
            listed = home if request.url.params.get("channel") == "HOME_PAGE" else gift
            body = [{"name": "Food", "cardBrands": [{"cardBrandId": b} for b in listed]},
                    {"name": "Empty", "cardBrands": None}]
            return httpx.Response(list_status, text=json.dumps(body))
        return httpx.Response(brand_status, text="")
    client._http = httpx.Client(transport=httpx.MockTransport(handler))


def test_a_brand_absent_from_both_readable_brand_lists_is_a_wrong_id(client):
    _route(client, 502, 200)
    with pytest.raises(ItemIdError) as info:
        client.validate_amount("CB9-CT1", "5")
    assert not isinstance(info.value, ItemCheckUnavailableError)
    assert info.value.to_dict()["error"] == "invalid_item_id"


@pytest.mark.parametrize("home, gift", [(("CB9",), ()), ((), ("CB9",))], ids=["home-page", "send-gift"])
def test_a_listed_brand_whose_detail_lookup_fails_is_unverifiable(client, home, gift):
    _route(client, 502, 200, home=home or ("CB_OTHER",), gift=gift or ("CB_OTHER",))
    with pytest.raises(ItemCheckUnavailableError):
        client.validate_amount("CB9-CT1", "5")


def test_a_failed_detail_lookup_with_the_lists_down_is_unverifiable(client):
    _route(client, 502, 502)
    with pytest.raises(ItemCheckUnavailableError):
        client.validate_amount("CB9-CT1", "5")

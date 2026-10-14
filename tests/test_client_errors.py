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


def _answering_transport(status, text):
    def handler(request):
        return httpx.Response(status, text=text)
    return httpx.MockTransport(handler)


_PAYMENTS = [
    lambda c: c.create_order_and_pay("CB1-CT1", "10"),
    lambda c: c.billpay_create_and_pay("PAY1", "10"),
]


@pytest.mark.parametrize("pay", _PAYMENTS, ids=["gift-card", "bill-pay"])
def test_unreadable_payment_success_is_indeterminate(client, pay):
    client._http = httpx.Client(transport=_answering_transport(200, "not json"))
    with pytest.raises(GatewayApiError) as info:
        pay(client)
    out = info.value.to_dict()
    assert out["outcome"] == "indeterminate"
    assert out["status_code"] == 200
    assert "may have completed" in out["error"]
    assert "not json" not in json.dumps(out)


def test_unreadable_success_on_a_read_is_an_error(client):
    client._http = httpx.Client(transport=_answering_transport(200, "not json"))
    with pytest.raises(GatewayApiError) as info:
        client.get_balance()
    out = info.value.to_dict()
    assert "outcome" not in out
    assert "unreadable" in out["error"]


@pytest.mark.parametrize("status", [500, 502, 503, 504])
@pytest.mark.parametrize("pay", _PAYMENTS, ids=["gift-card", "bill-pay"])
def test_payment_5xx_is_indeterminate_and_never_says_retry(client, pay, status):
    client._http = httpx.Client(transport=_answering_transport(status, "upstream down"))
    with pytest.raises(GatewayApiError) as info:
        pay(client)
    out = info.value.to_dict()
    assert out["outcome"] == "indeterminate"
    assert out["status_code"] == status
    assert "try again" not in out["error"].lower()
    assert "do not" in out["retry_hint"].lower()


def test_quote_502_still_suggests_a_retry():
    out = GatewayApiError(502, {}, "/v2/quote").to_dict()
    assert "try again" in out["error"]
    assert out["status_code"] == 502
    assert "outcome" not in out


@pytest.mark.parametrize("voucher_option", ["BEST_FIT", "NOT_USE", "USE"])
def test_quote_and_purchase_send_the_same_payment_context(client, voucher_option):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content)["paymentContext"])
        return httpx.Response(200, json={"rspMsgCd": "MCA00000"})

    client._http = httpx.Client(transport=httpx.MockTransport(handler))
    options = dict(voucher_option=voucher_option, cashback_option="NOT_USE", specified_voucher="V-9")
    client.quote_order("CB1-CT1", "10", **options)
    client.create_order_and_pay("CB1-CT1", "10", **options)
    assert sent[0] == sent[1]
    assert sent[0]["voucherOption"] == "USE"


def test_plain_403_is_a_permission_problem_not_a_login():
    out = GatewayApiError(403, {}, "/v2/purchase").to_dict()
    assert "snaplii init" not in out["error"]
    assert "permission" in out["error"].lower()
    assert out["status_code"] == 403


@pytest.mark.parametrize("content", [b"null", b"{}", b"[]", b'{"rspMsgCd": null}'],
                         ids=["null", "empty", "list", "odd-code"])
@pytest.mark.parametrize("pay", _PAYMENTS, ids=["gift-card", "bill-pay"])
def test_payment_reply_without_a_result_is_indeterminate(client, pay, content):
    client._http = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, content=content)))
    with pytest.raises(GatewayApiError) as info:
        pay(client)
    out = info.value.to_dict()
    assert out["outcome"] == "indeterminate"
    assert "may have completed" in out["error"]


def test_a_catalog_list_is_still_a_result(client):
    client._http = httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, json=[{"cardBrandId": "CB1"}])))
    assert client.get_all_card_tags()["data"] == [{"cardBrandId": "CB1"}]


@pytest.mark.parametrize("call", [
    lambda c: c.get_balance(),
    lambda c: c.poll_connect_token("0" * 32),
], ids=["read", "connect-poll"])
def test_a_read_timeout_is_a_structured_error(client, call):
    client._http = httpx.Client(transport=_raising_transport(httpx.ReadTimeout("read timed out")))
    with pytest.raises(GatewayConnectionError) as info:
        call(client)
    assert info.value.to_dict()["error"] == "Connection failed"


def _card_pages(total, *, ignores_page=False):
    def handler(request):
        page = 1 if ignores_page else int(request.url.params["page"])
        size = int(request.url.params["pageSize"])
        rows = [{"cardNo": str(i)} for i in range((page - 1) * size, min(page * size, total))]
        return httpx.Response(200, json={"data": rows})
    return httpx.MockTransport(handler)


@pytest.mark.parametrize("total", [0, 99, 100, 101, 250])
def test_all_owned_cards_are_read_page_by_page(client, total):
    client._http = httpx.Client(transport=_card_pages(total))
    assert len(client.list_all_user_cards()) == total


def test_a_server_that_ignores_paging_is_not_counted_twice(client):
    client._http = httpx.Client(transport=_card_pages(300, ignores_page=True))
    assert len(client.list_all_user_cards()) == 100

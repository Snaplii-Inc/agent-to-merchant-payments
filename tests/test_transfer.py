"""P2P transfer support: client envelope handling, idempotency-key discipline,
and the CLI's cross-currency / failure decoration and --wait polling."""

import json

import httpx
import pytest
from click.testing import CliRunner

from snaplii.client import GatewayClient
from snaplii.commands.transfer import (
    decorate_transfer,
    cancel_cmd,
    create_cmd,
    finish_cmd,
    status_cmd,
)
from snaplii.exceptions import TransferApiError


class _FakeStore:
    def get(self, key, default=None):
        return default

    def get_cached_token(self):
        return "tok-123"


def _client(httpx_mock=None):
    return GatewayClient("https://gw.test", _FakeStore())


# ── Client: envelope + idempotency ───────────────────────────────


def test_create_sends_idempotency_key_and_echoes_it(httpx_mock):
    httpx_mock.add_response(
        method="POST", url="https://gw.test/v2/transfers", status_code=201,
        json={"order_no": "ZZ1", "status": "PENDING", "amount": "12.50",
              "currency": "CAD", "received_amount": "12.50",
              "received_currency": "CAD"},
    )
    resp = _client().transfer_create("4165550006", "12.50")
    req = httpx_mock.get_requests()[0]
    key = req.headers["Idempotency-Key"]
    assert 16 <= len(key) <= 64
    assert resp["idempotency_key"] == key


def test_create_reuses_caller_key(httpx_mock):
    httpx_mock.add_response(
        method="POST", url="https://gw.test/v2/transfers", status_code=200,
        json={"order_no": "ZZ1", "status": "PENDING"},
    )
    resp = _client().transfer_create("4165550006", "12.50", idempotency_key="k" * 20)
    assert httpx_mock.get_requests()[0].headers["Idempotency-Key"] == "k" * 20
    assert resp["idempotency_key"] == "k" * 20


def test_error_envelope_surfaced_meaningfully(httpx_mock):
    httpx_mock.add_response(
        method="POST", url="https://gw.test/v2/transfers", status_code=403,
        json={"status": "error", "code": "TRANSFER_LIMIT_EXCEEDED",
              "message": "This API key's transfer limit for the window is exhausted.",
              "retryable": False, "upstream_code": None,
              "details": {"limit_cents": 2000, "used_cents": 1500}},
    )
    with pytest.raises(TransferApiError) as exc:
        _client().transfer_create("4165550006", "12.50")
    out = exc.value.to_dict()
    assert out["error"] == "This API key's transfer limit for the window is exhausted."
    assert out["code"] == "TRANSFER_LIMIT_EXCEEDED"
    assert out["retryable"] is False
    assert out["details"]["limit_cents"] == 2000
    # The key rides on the error so a retry can reuse it.
    assert out["idempotency_key"]


def test_validation_400_field_errors_joined(httpx_mock):
    # @Valid 400s use the common shape: message null, per-field messages in `errors`.
    httpx_mock.add_response(
        method="POST", url="https://gw.test/v2/transfers", status_code=400,
        json={"status": "error", "message": None,
              "errors": [{"field": "amount",
                          "message": "amount must be a string with up to 8 digits and 2 decimals"}]},
    )
    with pytest.raises(TransferApiError) as exc:
        _client().transfer_create("4165550006", "1.999")
    out = exc.value.to_dict()
    assert "amount" in out["error"]
    assert "8 digits" in out["error"]


def test_quote_expired_hints_fresh_key(httpx_mock):
    httpx_mock.add_response(
        method="POST", url="https://gw.test/v2/transfers", status_code=409,
        json={"status": "error", "code": "QUOTE_EXPIRED", "retryable": True,
              "message": "The quote expired before an order could be created."},
    )
    with pytest.raises(TransferApiError) as exc:
        _client().transfer_create("4165550006", "2.00")
    out = exc.value.to_dict()
    assert "fresh key" in out["retry_hint"]


def test_terminal_422_has_no_same_key_hint(httpx_mock):
    httpx_mock.add_response(
        method="POST", url="https://gw.test/v2/transfers", status_code=422,
        json={"status": "error", "code": "INSUFFICIENT_BALANCE", "retryable": True,
              "message": "The sending account balance is lower than the transfer amount."},
    )
    with pytest.raises(TransferApiError) as exc:
        _client().transfer_create("4165550006", "2.00")
    out = exc.value.to_dict()
    assert "retry_hint" not in out


def test_timeout_is_indeterminate_and_keeps_key(httpx_mock):
    httpx_mock.add_exception(httpx.ReadTimeout("timed out"))
    with pytest.raises(TransferApiError) as exc:
        _client().transfer_create("4165550006", "12.50", idempotency_key="k" * 20)
    out = exc.value.to_dict()
    assert out["code"] == "CLIENT_TIMEOUT"
    assert out["retryable"] is True
    assert out["idempotency_key"] == "k" * 20
    assert "never a fresh key" in out["retry_hint"]


# ── Decoration ───────────────────────────────────────────────────


def test_cross_currency_notice_added():
    row = decorate_transfer({"amount": "10.00", "currency": "CAD",
                     "received_amount": "7.31", "received_currency": "USD",
                     "conversion_rate": "0.731"})
    assert "7.31 USD" in row["cross_currency_notice"]
    assert "10.00 CAD" in row["cross_currency_notice"]


def test_same_currency_has_no_notice():
    row = decorate_transfer({"amount": "10.00", "currency": "CAD",
                     "received_amount": "10.00", "received_currency": "CAD"})
    assert "cross_currency_notice" not in row


def test_fail_reason_translated():
    row = decorate_transfer({"status": "FAILED", "fail_reason": "INSUFFICIENT_BALANCE"})
    assert "insufficient" in row["fail_message"].lower()


# ── CLI commands ─────────────────────────────────────────────────


class FakeTransferClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def _next(self, name, *args, **kwargs):
        self.calls.append(name)
        return self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]

    def transfer_create(self, **kw):
        return self._next("create")

    def transfer_cancel(self, order_no):
        return self._next("cancel")

    def transfer_finish(self, order_no):
        return self._next("finish")

    def transfer_get(self, order_no):
        return self._next("get")


def _run(cmd, client, args):
    return CliRunner().invoke(cmd, args, obj={"client": client, "config_store": _FakeStore()})


def test_cli_create_creating_gives_same_key_instruction():
    client = FakeTransferClient([{"status": "CREATING", "idempotency_key": "abc",
                                  "retry_after_seconds": 15}])
    result = _run(create_cmd, client, ["--to-phone", "4165550006", "--amount", "5.00"])
    assert result.exit_code == 0
    out = json.loads(result.output)
    assert "NEVER a fresh key" in out["next_step"]


def test_cli_status_wait_polls_until_terminal(monkeypatch):
    monkeypatch.setattr("snaplii.commands.transfer.time.sleep", lambda s: None)
    client = FakeTransferClient([
        {"status": "PENDING"},
        {"status": "FINISHING"},
        {"status": "FINISHED", "finished_at": "2026-08-30T00:00:00.000Z"},
    ])
    result = _run(status_cmd, client, ["--order-no", "ZZ1", "--wait"])
    out = json.loads(result.output)
    assert out["status"] == "FINISHED"
    assert client.calls.count("get") == 3


def test_cli_status_wait_reports_failure_meaningfully(monkeypatch):
    monkeypatch.setattr("snaplii.commands.transfer.time.sleep", lambda s: None)
    client = FakeTransferClient([
        {"status": "FAILED", "fail_code": "MCAP6992", "fail_reason": "INSUFFICIENT_BALANCE"},
    ])
    result = _run(status_cmd, client, ["--order-no", "ZZ1", "--wait"])
    out = json.loads(result.output)
    assert out["status"] == "FAILED"
    assert "Top up" in out["fail_message"]


def test_cli_cancel_cancelling_suggests_polling():
    client = FakeTransferClient([{"order_no": "ZZ1", "status": "CANCELLING"}])
    result = _run(cancel_cmd, client, ["--order-no", "ZZ1"])
    out = json.loads(result.output)
    assert "--wait" in out["next_step"]


def test_cli_finish_points_to_status_polling():
    client = FakeTransferClient([{"order_no": "ZZ1", "status": "PENDING",
                                  "auto_finish_at": "2026-08-30T00:00:05.000Z"}])
    result = _run(finish_cmd, client, ["--order-no", "ZZ1"])
    out = json.loads(result.output)
    assert "transfer status" in out["next_step"]

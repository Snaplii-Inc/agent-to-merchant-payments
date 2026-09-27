"""Every public business entrypoint must return auth guidance before sending HTTP."""
import asyncio
import json
import shlex
import sys

import click
import keyring
import pytest
from keyring.backends.fail import Keyring

import server
from snaplii import auth, cli
from snaplii.client import GatewayClient
from snaplii.config_store import ConfigStore


# Paired CLI/MCP entrypoints, with syntactically valid, synthetic arguments.
OPERATIONS = [
    ("balance", "balance", {}),
    ("browse tags", "browse_tags", {}),
    ("browse brand --id brand", "browse_brand", {"brand_id": "brand"}),
    ("giftcard list", "giftcard_list", {}),
    ("giftcard detail --card-no card", "giftcard_detail", {"card_no": "card"}),
    ("quote --item-id brand-template --price 10", "quote", {"item_id": "brand-template", "price": "10"}),
    ("purchase --item-id brand-template --price 10", "purchase", {"item_id": "brand-template", "price": "10"}),
    ("smart cashback --brand-id brand --amount 10", "cashback_calc", {"brand_id": "brand", "amount": 10}),
    ("smart dashboard", "dashboard", {}),
    ("billpay payees", "billpay_payees", {}),
    ("billpay detail --payee-code payee", "billpay_detail", {"payee_code": "payee"}),
    ("billpay history --payee-code payee", "billpay_history", {"payee_code": "payee"}),
    ("billpay save --payee-code payee --first-name Test --last-name User --amount 10 --account account",
     "billpay_save", {"payee_code": "payee", "first_name": "Test", "last_name": "User",
                      "amount": "10", "account": "account"}),
    ("billpay vouchers --pay-code bill --price 10", "billpay_vouchers", {"pay_code": "bill", "price": "10"}),
    ("billpay quote --pay-code bill --price 10", "billpay_quote", {"pay_code": "bill", "price": "10"}),
    ("billpay pay --pay-code bill --price 10", "billpay_pay", {"pay_code": "bill", "price": "10"}),
    ("billpay result --payment-no payment", "billpay_result", {"payment_no": "payment"}),
    ("transfer create --to-phone +14165550123 --amount 10", "transfer_create",
     {"to_phone": "+14165550123", "amount": "10"}),
    ("transfer cancel --order-no order", "transfer_cancel", {"order_no": "order"}),
    ("transfer finish --order-no order", "transfer_finish", {"order_no": "order"}),
    ("transfer status --order-no order", "transfer_status", {"order_no": "order"}),
    ("transfer list", "transfer_list", {}),
]


@pytest.fixture
def muse_runtime(tmp_path, monkeypatch, muse_filesystem):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    monkeypatch.delenv("SNAPLII_BASE_URL", raising=False)
    store = ConfigStore(tmp_path / "config.json")
    client = GatewayClient(auth.DEFAULT_ORIGIN, store)
    monkeypatch.setattr(cli, "ConfigStore", lambda: store)
    monkeypatch.setattr(cli, "GatewayClient", lambda *args: client)
    monkeypatch.setattr(cli, "check_for_update", lambda *args: None)
    monkeypatch.setattr(server, "ConfigStore", lambda: store)
    monkeypatch.setattr(server, "_get_client", lambda: client)
    monkeypatch.setattr(server, "_base_url", lambda: auth.DEFAULT_ORIGIN)
    monkeypatch.setattr(server, "_update_notice", lambda: None)
    yield store
    client._http.close()


def test_business_auth_matrix_covers_all_registered_entrypoints():
    # New business commands must be included in the behavioral checks below.
    def leaves(command, prefix=()):
        if isinstance(command, click.Group):
            return {path for name, child in command.commands.items()
                    for path in leaves(child, prefix + (name,))}
        return {" ".join(prefix)}

    local_cli = {"help", "update", "init", "config set", "config show", "config doctor", "config clear"}
    assert leaves(cli.main) - local_cli == {command.split(" --", 1)[0] for command, _, _ in OPERATIONS}
    local_mcp = {"snaplii_config_show", "snaplii_init", "snaplii_connect", "snaplii_submit_api_key"}
    assert {tool.name for tool in asyncio.run(server.list_tools())} - local_mcp == {
        "snaplii_" + name for _, name, _ in OPERATIONS
    }


@pytest.mark.parametrize("surface", ["cli", "mcp"])
@pytest.mark.parametrize("expired", [False, True], ids=["missing-session", "expired-session"])
@pytest.mark.parametrize("command,name,arguments", OPERATIONS, ids=[op[1] for op in OPERATIONS])
def test_every_business_operation_requires_session(
    muse_runtime, monkeypatch, capsys, httpx_mock, surface, expired, command, name, arguments,
):
    store = muse_runtime
    store.runtime = surface
    if expired:
        store.commit_session("synthetic-token", 3600, agent_id="agent-1",
                             auth_method="vault", token_origin=auth.DEFAULT_ORIGIN)
        store.set("token_expires_at", 1)

    if surface == "cli":
        monkeypatch.setattr(sys, "argv", ["snaplii", *shlex.split(command)])
        with pytest.raises(SystemExit) as exc:
            cli._cli()
        assert exc.value.code == 1
        output = capsys.readouterr()
        assert output.out == ""
        result = json.loads(output.err)
    else:
        result = json.loads(asyncio.run(server.call_tool("snaplii_" + name, arguments))[0].text)

    state = "reauth_required" if expired else "auth_required"
    assert result["auth_state"] == state
    assert result["next_action"] == auth.build_auth_action(state, host="muse")
    assert result["next_action"]["instruction"] == auth.MUSE_AUTH_INSTRUCTION
    # No business request or implicit API-key exchange may be sent first.
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize("command", ["help", "--version", "config show", "config doctor", "config clear"])
def test_local_setup_and_recovery_remain_available_without_session(
    muse_runtime, monkeypatch, capsys, httpx_mock, command,
):
    monkeypatch.setattr(sys, "argv", ["snaplii", *shlex.split(command)])
    cli._cli()
    output = capsys.readouterr()
    assert output.err == ""
    assert output.out
    assert httpx_mock.get_requests() == []

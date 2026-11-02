"""scripts/export_remote_tools.py exports the remote MCP tools agent-gateway serves from server.py."""
import asyncio
import importlib.util
import os
from pathlib import Path

import server

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("export_remote_tools", ROOT / "scripts/export_remote_tools.py")
export = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(export)

GIFT_CARD = ["snaplii_balance", "snaplii_browse_tags", "snaplii_browse_brand", "snaplii_giftcard_list",
             "snaplii_giftcard_detail", "snaplii_quote", "snaplii_purchase", "snaplii_cashback_calc"]
BILL_PAY = ["snaplii_billpay_payees", "snaplii_billpay_detail", "snaplii_billpay_history", "snaplii_billpay_save",
            "snaplii_billpay_vouchers", "snaplii_billpay_quote", "snaplii_billpay_pay", "snaplii_billpay_result"]
TRANSFER = ["snaplii_transfer_create", "snaplii_transfer_cancel", "snaplii_transfer_finish",
            "snaplii_transfer_status", "snaplii_transfer_list"]
NOT_REMOTE = {"snaplii_config_show", "snaplii_init", "snaplii_connect", "snaplii_submit_api_key", "snaplii_dashboard"}

BILL_NOT_CAPPED = "bill payments are not subject to it"


def _local():
    return {t.name: t for t in asyncio.run(server.list_tools())}


def _remote():
    return export.build()


def _remote_tools():
    return {t["name"]: t for t in _remote()["tools"]}


def _remote_texts():
    remote = _remote()
    texts = {"instructions": remote["instructions"]}
    texts.update({t["name"]: t["description_remote"] for t in remote["tools"]})
    return texts


def test_exports_the_21_remote_tools_and_no_local_only_tool():
    names = [t["name"] for t in _remote()["tools"]]
    assert names == GIFT_CARD + BILL_PAY + TRANSFER
    assert not NOT_REMOTE & set(names)
    # Every local tool is either exported or deliberately local-only.
    assert set(_local()) == set(names) | NOT_REMOTE


def test_names_schemas_and_annotations_match_server_py():
    local = _local()
    for tool in _remote()["tools"]:
        source = local[tool["name"]]
        assert set(tool) == {"name", "title", "description_remote", "inputSchema", "annotations",
                             "required_key_scope"}, tool["name"]
        assert tool["inputSchema"] == source.inputSchema, tool["name"]
        assert tool["annotations"] == source.annotations.model_dump(by_alias=True, exclude_none=True), tool["name"]
        assert tool["title"] == source.title, tool["name"]


def test_every_tool_names_the_key_scope_it_needs():
    scopes = {name: tool["required_key_scope"] for name, tool in _remote_tools().items()}
    assert scopes == {**{n: "ACQUIRY" for n in GIFT_CARD}, **{n: "PURCHASE" for n in BILL_PAY},
                      **{n: "ALL" for n in TRANSFER}}


def test_remote_text_drops_local_only_content():
    banned = ("P2P or ALL", "must include P2P", "snaplii_config_show", "has_valid_token", "snaplii_connect",
              "snaplii_init", "snaplii_submit_api_key", "snaplii_autopilot", "snaplii_dashboard", "update_available")
    for where, text in _remote_texts().items():
        for phrase in banned:
            assert phrase not in text, (where, phrase)
    # The local instructions still carry them; the export removed them.
    assert "P2P or ALL" in server._SERVER_INSTRUCTIONS and "snaplii_connect" in server._SERVER_INSTRUCTIONS


def test_bill_pay_is_not_capped_by_the_key_daily_limit():
    local = _local()["snaplii_billpay_pay"].description
    assert BILL_NOT_CAPPED in local
    assert "within the user's per-key daily limit" not in local
    assert "cannot be undone" in local
    assert _remote_tools()["snaplii_billpay_pay"]["description_remote"] == local
    payment = next(p for p in _remote()["instructions"].split("\n\n") if p.startswith("HOW PAYMENT WORKS:"))
    assert "daily limit" in payment and BILL_NOT_CAPPED in payment
    # Gift cards stay capped.
    assert "daily limit" in _remote_tools()["snaplii_purchase"]["description_remote"]


def test_gift_card_and_bill_descriptions_are_the_local_ones():
    local = _local()
    for name in GIFT_CARD + BILL_PAY:
        assert _remote_tools()[name]["description_remote"] == local[name].description, name


def test_transfer_create_says_to_check_the_list_when_no_result_came_back():
    text = _remote_tools()["snaplii_transfer_create"]["description_remote"]
    assert "returns no result at all (timeout, dropped connection)" in text
    assert "snaplii_transfer_list without `status`" in text
    assert "last 4 digits and amount" in text
    assert "including ones already FINISHED" in text


def test_transfer_texts_do_not_poll_inside_the_cancel_window():
    texts = _remote_texts()
    for where in TRANSFER + ["instructions"]:
        assert "every few seconds" not in texts[where], where
        assert "poll the same way" not in texts[where], where
    for where in ("snaplii_transfer_create", "snaplii_transfer_status", "instructions"):
        assert "not poll" in texts[where], where
    for where in ("snaplii_transfer_cancel", "snaplii_transfer_finish", "snaplii_transfer_status", "instructions"):
        assert "about every 10 seconds" in texts[where], where
        assert "two minutes" in texts[where], where
    # The local texts keep their own cadence.
    assert "every few seconds" in _local()["snaplii_transfer_status"].description


def test_p2p_paragraph_applies_only_when_the_transfer_tools_are_listed():
    paragraphs = _remote()["instructions"].split("\n\n")
    [p2p] = [p for p in paragraphs if p.startswith("P2P TRANSFERS")]
    assert p2p.startswith("P2P TRANSFERS (applies only when the snaplii_transfer_* tools are listed):")
    for kept in ("ASK for it", "cancel deadline", "cross_currency_notice", "explicitly asks to send now",
                 "SAME idempotency_key"):
        assert kept in p2p, kept
    assert not any(p.startswith(("UPDATES:", "CONNECT:")) for p in paragraphs)


def test_remote_text_keeps_the_facts_the_agent_judges_by():
    instructions = _remote()["instructions"].lower()
    for needle in ("prepaid", "daily limit", "revocable", "cannot be undone", "5 minutes"):
        assert needle in instructions, needle


def test_output_does_not_depend_on_the_instinct_environment(monkeypatch):
    plain = export.render()
    monkeypatch.setenv("INSTINCT_AGENT_ID", "agent-1")
    assert export.render() == plain
    # The export leaves the environment as it found it.
    assert os.environ["INSTINCT_AGENT_ID"] == "agent-1"


def test_main_writes_the_file_and_check_reports_drift(tmp_path, capsys):
    out = tmp_path / "remote-tools" / "tools.json"
    assert export.main(["--check", "--out", str(out)]) == 1
    assert export.main(["--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == export.render()
    assert export.main(["--check", "--out", str(out)]) == 0
    out.write_text(out.read_text(encoding="utf-8").replace("ACQUIRY", "PURCHASE", 1), encoding="utf-8")
    assert export.main(["--check", "--out", str(out)]) == 1
    assert "out of date" in capsys.readouterr().err
    assert export.DEFAULT_OUT == ROOT / "build" / "remote-tools" / "tools.json"

"""`snaplii agent balance / catalog / buy / order / top-up*`: buying and topping up with the phone connection."""
import json

import pytest

from conftest import AGENT_GATEWAY, NO_AGENT_API, TOKEN_REFUSED, connect_by_phone
from snaplii.exceptions import ConnectError, GatewayApiError

API = f"{AGENT_GATEWAY}/api/agent/v1"

AGENT_TOKEN = "snp_ag_longterm0000000000000000000000000000000000"
ORDER_ID = "0b7e2c1a-5d0f-4f5e-9a55-2f6f3f0c9d11"
ITEM = "CB0000000000201-CT0002010000025"


@pytest.fixture
def run(run_agent_cli, agent_config):
    """The CLI, with this configuration connected by phone as Muse."""
    connect_by_phone(agent_config, AGENT_TOKEN)
    return run_agent_cli


def order(status, **more):
    return {"id": ORDER_ID, "status": status, "item_id": ITEM, "price": "25", "amount_cents": 2500,
            "currency": "CAD", "next_step": "...", **more}


def test_buy_sends_the_order_with_the_agents_token_and_prints_where_it_ended(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/orders", method="POST", json=order("PAID", card_no="SIMCARD-1-1"))

    result = run("agent", "buy", "--item-id", ITEM, "--price", "25")

    assert result.exit_code == 0
    printed = json.loads(result.stdout)
    assert printed["status"] == "PAID"
    assert printed["amount"] == "CA$25.00"
    request = httpx_mock.get_request()
    assert request.headers["Authorization"] == f"Bearer {AGENT_TOKEN}"
    sent = json.loads(request.content)
    assert sent == {"item_id": ITEM, "price": "25", "idempotency_key": printed["idempotency_key"]}
    assert sent["idempotency_key"] in result.stderr  # known before the answer, for a run that dies
    assert "snp_" not in result.stdout + result.stderr  # no token is ever printed


def test_buy_with_an_earlier_key_asks_about_that_order_instead_of_buying_again(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/orders", method="POST", json=order("PAID"))

    run("agent", "buy", "--item-id", ITEM, "--price", "25", "--key", "cli-earlier-run-0001")

    assert json.loads(httpx_mock.get_request().content)["idempotency_key"] == "cli-earlier-run-0001"


def test_buy_waits_while_snaplii_is_paying(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/orders", method="POST", json=order("PAYING"))
    httpx_mock.add_response(url=f"{API}/orders/{ORDER_ID}", method="GET", json=order("PAYING"))
    httpx_mock.add_response(url=f"{API}/orders/{ORDER_ID}", method="GET", json=order("PAID"))

    result = run("agent", "buy", "--item-id", ITEM, "--price", "25")

    assert json.loads(result.stdout)["status"] == "PAID"
    assert len(httpx_mock.get_requests()) == 3  # the order is sent once, then only asked about


def test_buy_says_how_much_cash_is_missing(run, httpx_mock):
    httpx_mock.add_response(
        url=f"{API}/orders", method="POST",
        json=order("NEEDS_TOP_UP", price="150", amount_cents=15000, gap_cents=5000),
    )

    printed = json.loads(run("agent", "buy", "--item-id", ITEM, "--price", "150").stdout)

    assert printed["status"] == "NEEDS_TOP_UP"
    assert printed["gap"] == "CA$50.00"


def test_order_continue_checks_the_same_order_again_after_a_top_up(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/orders/{ORDER_ID}/continue", method="POST", json=order("PAID"))

    printed = json.loads(run("agent", "order", ORDER_ID, "--continue").stdout)

    assert printed["status"] == "PAID"
    assert httpx_mock.get_request().headers["Authorization"] == f"Bearer {AGENT_TOKEN}"


def test_order_shows_an_order(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/orders/{ORDER_ID}", method="GET", json=order("OVER_LIMIT"))

    assert json.loads(run("agent", "order", ORDER_ID).stdout)["status"] == "OVER_LIMIT"


@pytest.mark.parametrize("status,more,says", [
    ("NEEDS_TOP_UP", {"gap_cents": 5000},
     ["'snaplii agent top-up 50.00'", f"'snaplii agent order {ORDER_ID} --continue'", "Do not buy this again"]),
    ("PAYING", {}, [f"'snaplii agent order {ORDER_ID}'", "Do not order again"]),
    ("PAID", {}, ["Snaplii app", "Never show the card's code or PIN"]),
    ("EXPIRED", {}, ["nothing was charged", "'snaplii agent buy' again without --key"]),
])
def test_an_orders_next_step_names_cli_commands_never_the_gateways_api(run, httpx_mock, status, more, says):
    gateways_words = f"Call POST /api/agent/v1/orders/{ORDER_ID}/continue or GET /api/agent/v1/orders/{ORDER_ID}/card."
    httpx_mock.add_response(url=f"{API}/orders/{ORDER_ID}", method="GET",
                            json=order(status, next_step=gateways_words, **more))

    next_step = json.loads(run("agent", "order", ORDER_ID, "--timeout", "0").stdout)["next_step"]

    assert "/api/" not in next_step
    for words in says:
        assert words in next_step


def test_an_order_short_of_cash_without_its_gap_names_no_amount(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/orders/{ORDER_ID}", method="GET", json=order("NEEDS_TOP_UP"))

    next_step = json.loads(run("agent", "order", ORDER_ID).stdout)["next_step"]

    assert "'snaplii agent top-up AMOUNT'" in next_step and "0.00" not in next_step


def test_no_next_step_naming_the_api_reaches_the_agent_whatever_the_status(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/orders/{ORDER_ID}", method="GET",
                            json=order("UNKNOWN", next_step=f"Check GET /api/agent/v1/orders/{ORDER_ID}."))
    httpx_mock.add_response(url=f"{API}/top-ups/{TOP_UP_ID}", method="GET",
                            json=top_up("REVIEW", next_step=f"Check GET /api/agent/v1/top-ups/{TOP_UP_ID}."))

    order_step = json.loads(run("agent", "order", ORDER_ID).stdout)["next_step"]
    top_up_step = json.loads(run("agent", "top-up-status", TOP_UP_ID).stdout)["next_step"]

    assert "/api/" not in order_step and f"'snaplii agent order {ORDER_ID}'" in order_step
    assert "/api/" not in top_up_step and f"'snaplii agent top-up-status {TOP_UP_ID}'" in top_up_step


def test_an_orders_next_step_without_api_calls_is_the_gateways(run, httpx_mock):
    why = "This order would pass this agent's daily limit. Tell the user to buy it in the Snaplii app."
    httpx_mock.add_response(url=f"{API}/orders/{ORDER_ID}", method="GET", json=order("OVER_LIMIT", next_step=why))

    assert json.loads(run("agent", "order", ORDER_ID).stdout)["next_step"] == why


def test_there_is_no_redeem_that_sends_a_card_to_a_checkout_url(run):
    result = run("agent", "redeem", ORDER_ID, "--checkout-url", "https://merchant.example/checkout")

    assert result.exit_code == 2  # no such command


def test_catalog_lists_the_brands_and_one_brands_cards_as_the_gateway_gives_them(run, httpx_mock):
    brands = {"categories": [{"id": "12", "name": "Food & Dining", "brands": [
        {"brand_id": "CB0000000000201", "name": "DoorDash", "cashback_percent": "3"}]}]}
    cards = {"brand_id": "CB0000000000201", "name": "DoorDash", "cards": [
        {"item_id": ITEM, "type": "FIXED", "amount": "25", "cashback_percent": "3"}]}
    httpx_mock.add_response(url=f"{API}/card-brands", method="GET", json=brands)
    httpx_mock.add_response(url=f"{API}/card-brands/CB0000000000201", method="GET", json=cards)

    assert json.loads(run("agent", "catalog").stdout) == brands
    assert json.loads(run("agent", "catalog", "CB0000000000201").stdout) == cards
    assert all(r.headers["Authorization"] == f"Bearer {AGENT_TOKEN}" for r in httpx_mock.get_requests())


def test_balance_shows_cash_and_what_is_left_of_the_limit(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/balance", method="GET", json={
        "cash_cents": 10000, "currency": "CAD", "daily_limit_cents": 20000, "spent_today_cents": 5000,
        "available_today_cents": 15000,
    })

    printed = json.loads(run("agent", "balance").stdout)

    assert printed["cash"] == "CA$100.00"
    assert printed["available_today"] == "CA$150.00"


def test_agent_balance_never_uses_the_api_key_session(run, agent_config, httpx_mock):
    agent_config.commit_session("api-key-session-token", 3600, agent_id="agent-1", auth_method="api_key",
                                token_origin=AGENT_GATEWAY)
    httpx_mock.add_response(url=f"{API}/balance", method="GET", json={"cash_cents": 100, "currency": "CAD"})

    run("agent", "balance")

    assert httpx_mock.get_request().headers["Authorization"] == f"Bearer {AGENT_TOKEN}"


def test_an_agent_whose_access_to_snaplii_ended_is_told_how_to_connect_again(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/orders", method="POST", status_code=409, json={
        "status": "error", "code": "reconnect-needed", "message": "Connect the agent again.",
    })

    with pytest.raises(ConnectError, match="snaplii agent connect"):
        run("agent", "buy", "--item-id", ITEM, "--price", "25")


def test_buying_needs_a_connected_agent(run, agent_config, httpx_mock):
    httpx_mock.add_response(url=f"{API}/orders", method="POST", status_code=401, json=TOKEN_REFUSED)
    with pytest.raises(ConnectError, match="isn't connected any more"):
        run("agent", "buy", "--item-id", ITEM, "--price", "25")

    agent_config.update_agent_connection(remove=("agent_token", "agent_name"))
    with pytest.raises(ConnectError, match="isn't connected by phone yet"):
        run("agent", "buy", "--item-id", ITEM, "--price", "25")


def test_a_401_from_the_agent_api_leaves_the_api_key_session_alone(run, agent_config, httpx_mock):
    agent_config.commit_session("api-key-session-token", 3600, agent_id="agent-1", auth_method="api_key",
                                token_origin=AGENT_GATEWAY)
    httpx_mock.add_response(url=f"{API}/balance", method="GET", status_code=401, json=TOKEN_REFUSED)

    with pytest.raises(ConnectError):
        run("agent", "balance")

    assert agent_config.get_cached_token(origin=AGENT_GATEWAY) == "api-key-session-token"


WAITING = {"tokens": {"connect_token": "snp_ct_waiting0000000000000000000000000000000000"},
           "fields": {"connect_agent_name": "muse"}}


def test_a_dead_token_with_a_sign_in_waiting_says_to_have_it_approved_not_to_start_another(run, agent_config,
                                                                                            httpx_mock):
    agent_config.update_agent_connection(**WAITING)
    httpx_mock.add_response(url=f"{API}/balance", method="GET", status_code=401, json=TOKEN_REFUSED)
    httpx_mock.add_response(url=f"{API}/connect/token", method="POST", json={"status": "pending"})

    with pytest.raises(ConnectError, match="isn't approved yet.*snaplii agent connect --agent muse --resume"):
        run("agent", "balance")


def test_a_dead_token_replaced_by_an_approved_sign_in_collects_the_new_one(run, agent_config, httpx_mock):
    agent_config.update_agent_connection(**WAITING)
    new_token = "snp_ag_newtoken000000000000000000000000000000000"
    httpx_mock.add_response(url=f"{API}/balance", method="GET", status_code=401, json=TOKEN_REFUSED)
    httpx_mock.add_response(url=f"{API}/connect/token", method="POST", json={
        "status": "connected", "agent_token": new_token, "agent": "muse", "daily_limit_cents": 20000,
        "currency": "CAD"})

    with pytest.raises(ConnectError, match="run the command again"):
        run("agent", "balance")

    assert agent_config.get_agent_secret("agent_token") == new_token


def test_a_401_that_does_not_name_the_agents_token_is_not_read_as_disconnected(run, agent_config, httpx_mock):
    httpx_mock.add_response(url=f"{API}/balance", method="GET", status_code=401, json=NO_AGENT_API)

    with pytest.raises(ConnectError, match="didn't say its token stopped working") as refused:
        run("agent", "balance")

    assert "isn't connected any more" not in str(refused.value)
    assert agent_config.get_agent_secret("agent_token") == AGENT_TOKEN


def test_a_field_the_gateway_refused_is_named_with_its_reason(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/orders", method="POST", status_code=400, json={
        "status": "error", "message": None,
        "errors": [{"field": "idempotency_key", "message": "must match [A-Za-z0-9_-]{8,64}"}],
    })

    with pytest.raises(GatewayApiError) as refused:
        run("agent", "buy", "--item-id", ITEM, "--price", "25", "--key", "abc")

    assert refused.value.to_dict()["error"] == "idempotency_key: must match [A-Za-z0-9_-]{8,64}"


def test_a_refused_field_without_its_reason_still_reads(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/orders", method="POST", status_code=400, json={
        "status": "error", "message": None, "errors": [{"field": "price", "message": None}]})

    with pytest.raises(GatewayApiError) as refused:
        run("agent", "buy", "--item-id", ITEM, "--price", "25")

    assert refused.value.to_dict()["error"] == "price: invalid"


TOP_UP_ID = "5a1f6c2e-8b0d-4e3a-9f1c-7d2e4b6a8c01"


PAY_PAGE = "http://localhost:8080/top-up/pay/snp_pay_abc"

# The gateway's own words for an unpaid top-up name its API calls; the CLI says them with its commands.
GATEWAYS_NEXT_STEP = (
    "Give the user the link in pay_url. Wait for them to pay: check GET /api/agent/v1/top-ups/"
    f"{TOP_UP_ID} every few seconds. To ask for another amount, cancel this one first (DELETE /api/agent/v1/top-ups/{TOP_UP_ID})."
)
CLI_COMMANDS_OF_UNPAID_TOP_UP = (
    f"Wait for them to pay: check 'snaplii agent top-up-status {TOP_UP_ID}' every few seconds until it is "
    "CREDITED, FAILED or EXPIRED. Do not start another top-up: to ask for another amount or payment method, "
    f"take this one back first with 'snaplii agent top-up-cancel {TOP_UP_ID}'."
)


def top_up(status, **more):
    return {"id": TOP_UP_ID, "status": status, "amount_cents": 5000, "currency": "CAD",
            "payment_method": "stripe", "expires_at": "2026-11-18T12:30:00Z", "next_step": "...", **more}


def test_top_up_prints_the_next_step_in_cli_commands_then_the_pay_link_and_returns_at_once(run, httpx_mock):
    httpx_mock.add_response(
        url=f"{API}/top-ups", method="POST", status_code=201,
        json=top_up("CREATED", pay_url=PAY_PAGE, next_step=GATEWAYS_NEXT_STEP),
    )

    result = run("agent", "top-up", "50")

    printed = json.loads(result.stdout)
    assert printed["id"] == TOP_UP_ID
    assert printed["status"] == "CREATED"
    assert printed["amount"] == "CA$50.00"
    assert printed["pay_url"] == PAY_PAGE
    # What to do names this CLI's commands, never the gateway's API; then the link itself.
    next_step = ("Give the user the link in pay_url: they pay CA$50.00 there with Apple Pay or Google Pay, which "
                 "adds it to their Snaplii Cash. " + CLI_COMMANDS_OF_UNPAID_TOP_UP)
    assert printed["next_step"] == next_step
    assert result.stderr.splitlines() == [next_step, f"The pay link (pay_url) to give to the user: {PAY_PAGE}"]
    [request] = httpx_mock.get_requests()  # no polling
    assert json.loads(request.content) == {"amount": "50"}
    assert request.headers["Authorization"] == f"Bearer {AGENT_TOKEN}"
    assert AGENT_TOKEN not in result.stdout + result.stderr


def test_top_up_without_a_next_step_from_the_gateway_still_prints_what_to_do_and_the_pay_link(run, httpx_mock):
    without_next_step = top_up("CREATED", pay_url=PAY_PAGE)
    del without_next_step["next_step"]
    httpx_mock.add_response(url=f"{API}/top-ups", method="POST", status_code=201, json=without_next_step)

    result = run("agent", "top-up", "50")

    [what_to_do, pay_link] = result.stderr.splitlines()
    assert what_to_do.endswith(CLI_COMMANDS_OF_UNPAID_TOP_UP)
    assert pay_link == f"The pay link (pay_url) to give to the user: {PAY_PAGE}"


def test_a_texted_top_up_says_where_the_text_went(run, httpx_mock):
    httpx_mock.add_response(
        url=f"{API}/top-ups", method="POST", status_code=200,
        json=top_up("CREATED", texted_to="••••0123", next_step=GATEWAYS_NEXT_STEP),
    )

    result = run("agent", "top-up", "50")

    printed = json.loads(result.stdout)
    assert printed["status"] == "CREATED"
    assert printed["amount"] == "CA$50.00"
    assert result.stderr.splitlines() == [
        "The user got a text at ••••0123 with the link to pay CA$50.00 with Apple Pay or Google Pay, which adds it "
        "to their Snaplii Cash. "
        "It works until 2026-11-18T12:30:00Z. " + CLI_COMMANDS_OF_UNPAID_TOP_UP]
    assert printed["texted_to"] == "••••0123"
    [request] = httpx_mock.get_requests()  # no polling
    assert json.loads(request.content) == {"amount": "50"}


def test_top_up_by_alipay_names_the_payment_method_and_prints_the_link_to_give_the_user(run, httpx_mock):
    pay_url = "http://localhost:1090/alipay/PSP1"
    httpx_mock.add_response(
        url=f"{API}/top-ups", method="POST", status_code=201,
        json=top_up("CREATED", payment_method="alipay", texted_to=None, pay_url=pay_url),
    )

    result = run("agent", "top-up", "50", "--payment-method", "Alipay")

    [request] = httpx_mock.get_requests()
    assert json.loads(request.content) == {"amount": "50", "payment_method": "alipay"}
    assert f"The pay link (pay_url) to give to the user: {pay_url}" in result.stderr
    assert json.loads(result.stdout)["pay_url"] == pay_url


def test_an_open_top_up_comes_back_without_its_link_and_says_the_user_has_it(run, httpx_mock):
    httpx_mock.add_response(
        url=f"{API}/top-ups", method="POST", status_code=200,
        json=top_up("CREATED", payment_method="alipay", texted_to=None, next_step=GATEWAYS_NEXT_STEP),
    )

    result = run("agent", "top-up", "50", "--payment-method", "alipay")

    assert result.stderr.splitlines() == [
        "The user already has the link of this top-up of CA$50.00: it was in the answer that started it. "
        + CLI_COMMANDS_OF_UNPAID_TOP_UP]
    assert "pay_url" not in json.loads(result.stdout)


def test_a_top_up_that_failed_at_once_prints_why_and_no_command_to_follow_it_with(run, httpx_mock):
    why = "The top-up couldn't be started, or the payment failed, and nobody was charged."
    httpx_mock.add_response(
        url=f"{API}/top-ups", method="POST", status_code=201, json=top_up("FAILED", next_step=why)
    )

    result = run("agent", "top-up", "50")

    assert result.stderr.splitlines() == [why]
    assert json.loads(result.stdout)["status"] == "FAILED"


def test_a_payment_method_the_cli_does_not_know_is_a_usage_error_and_sends_nothing(run, httpx_mock):
    result = run("agent", "top-up", "50", "--payment-method", "wechat")

    assert result.exit_code == 2
    assert httpx_mock.get_requests() == []


def test_top_up_status_reads_once_and_shows_cash_once_credited(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/top-ups/{TOP_UP_ID}", method="GET", json=top_up("CREATED"))
    httpx_mock.add_response(url=f"{API}/top-ups/{TOP_UP_ID}", method="GET", json=top_up("CREDITED"))
    httpx_mock.add_response(url=f"{API}/balance", method="GET", json={"cash_cents": 15000, "currency": "CAD"})

    waiting = json.loads(run("agent", "top-up-status", TOP_UP_ID).stdout)
    credited = json.loads(run("agent", "top-up-status", TOP_UP_ID).stdout)

    assert waiting["status"] == "CREATED" and "cash" not in waiting
    assert credited["status"] == "CREDITED"
    assert credited["cash"] == "CA$150.00"
    assert "'snaplii agent buy'" in credited["next_step"] and "--continue" in credited["next_step"]
    assert len(httpx_mock.get_requests()) == 3


def test_top_up_cancel_takes_back_an_unpaid_top_up(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/top-ups/{TOP_UP_ID}", method="DELETE", json=top_up("CANCELLED"))

    result = run("agent", "top-up-cancel", TOP_UP_ID)

    [request] = httpx_mock.get_requests()
    assert request.method == "DELETE"
    assert request.headers["Authorization"] == f"Bearer {AGENT_TOKEN}"
    cancelled = json.loads(result.stdout)
    assert cancelled["status"] == "CANCELLED" and cancelled["amount"] == "CA$50.00"


def test_top_up_cancel_of_a_paid_top_up_says_why(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/top-ups/{TOP_UP_ID}", method="DELETE", status_code=409, json={
        "status": "error", "code": "top-up-not-open",
        "message": "Only a top-up nobody paid yet can be cancelled: this one is CREDITED.",
    })

    with pytest.raises(GatewayApiError) as refused:
        run("agent", "top-up-cancel", TOP_UP_ID)

    shown = refused.value.to_dict()
    assert shown["code"] == "top-up-not-open"
    assert "this one is CREDITED" in shown["error"]


def test_top_up_with_wait_waits_until_cash_has_the_money(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/top-ups", method="POST", status_code=201, json=top_up("CREATED"))
    httpx_mock.add_response(url=f"{API}/top-ups/{TOP_UP_ID}", method="GET", json=top_up("PAID"))
    httpx_mock.add_response(url=f"{API}/top-ups/{TOP_UP_ID}", method="GET", json=top_up("CREDITED"))
    httpx_mock.add_response(url=f"{API}/balance", method="GET", json={"cash_cents": 15000, "currency": "CAD"})

    printed = json.loads(run("agent", "top-up", "50", "--wait").stdout)

    assert printed["status"] == "CREDITED"
    assert printed["cash"] == "CA$150.00"


def test_a_top_up_nobody_paid_in_time_ends_with_what_to_do(run, httpx_mock):
    httpx_mock.add_response(url=f"{API}/top-ups/{TOP_UP_ID}", method="GET",
                            json=top_up("EXPIRED", next_step="Start a new top-up only if the user still wants one."))

    printed = json.loads(run("agent", "top-up-status", TOP_UP_ID).stdout)

    assert printed["status"] == "EXPIRED"
    assert "new top-up" in printed["next_step"]


@pytest.mark.parametrize("code", ["daily-limit-reached", "top-up-in-progress", "top-up-amount-out-of-range"])
def test_a_refused_top_up_says_why(run, httpx_mock, code):
    httpx_mock.add_response(url=f"{API}/top-ups", method="POST", status_code=409, json={
        "status": "error", "code": code, "message": "Refused for this reason.",
    })

    with pytest.raises(GatewayApiError) as refused:
        run("agent", "top-up", "50")

    shown = refused.value.to_dict()  # what the CLI prints
    assert shown["code"] == code
    assert shown["error"] == "Refused for this reason."

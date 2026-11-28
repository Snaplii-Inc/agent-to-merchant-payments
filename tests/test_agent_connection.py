"""`snaplii agent connect / connection / disconnect`: the phone connection, side by side with the API-key session."""
import json

import pytest

from conftest import AGENT_GATEWAY, NO_AGENT_API, TOKEN_REFUSED, connect_by_phone
from snaplii.config_store import AGENT_TOKEN as AGENT_TOKEN_NAME, CONNECT_TOKEN as CONNECT_TOKEN_NAME
from snaplii.exceptions import ConfigError, ConnectError, GatewayApiError

CONNECT = f"{AGENT_GATEWAY}/api/agent/v1/connect"
COLLECT = f"{AGENT_GATEWAY}/api/agent/v1/connect/token"
CONNECTION = f"{AGENT_GATEWAY}/api/agent/v1/connection"

CONNECT_TOKEN = "snp_ct_temporary000000000000000000000000000000000"
EARLIER_CONNECT_TOKEN = "snp_ct_earlier00000000000000000000000000000000000"
AGENT_TOKEN = "snp_ag_longterm0000000000000000000000000000000000"
OLD_AGENT_TOKEN = "snp_ag_earlier00000000000000000000000000000000000"
MUSE = {"agent": "muse", "daily_limit_cents": 20000, "currency": "CAD"}
PHONE = "416 555 0100"
TEXTED_TO = "+1 ••• ••• 0100"


def started(httpx_mock):
    httpx_mock.add_response(
        url=CONNECT, method="POST", status_code=202,
        json={"connect_token": CONNECT_TOKEN, "match_code": "4821", "texted_to": TEXTED_TO,
              "expires_in": 600, "interval": 3},
    )


def pending(httpx_mock):
    httpx_mock.add_response(url=COLLECT, method="POST", json={"status": "pending"})


def connected(httpx_mock):
    httpx_mock.add_response(
        url=COLLECT, method="POST", json={"status": "connected", "agent_token": AGENT_TOKEN, **MUSE}
    )


def connect_requests(httpx_mock):
    return [r for r in httpx_mock.get_requests() if str(r.url) == CONNECT]


def wait_for_sign_in(store, connect_token=EARLIER_CONNECT_TOKEN, agent_name="muse"):
    store.update_agent_connection(tokens={CONNECT_TOKEN_NAME: connect_token},
                                  fields={"connect_agent_name": agent_name, "agent_origin": AGENT_GATEWAY})


# --- a sign-in: the agent gives the user's phone, and Snaplii texts the link ---------------------


def test_connect_gives_the_phone_says_the_code_and_keeps_the_token_without_printing_it(
    run_agent_cli, agent_config, httpx_mock
):
    started(httpx_mock)
    pending(httpx_mock)
    pending(httpx_mock)
    connected(httpx_mock)

    result = run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE)

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"status": "connected", **MUSE, "daily_limit": "CA$200.00"}
    # The agent's name and the user's phone go with a first request, and no token.
    request = connect_requests(httpx_mock)[0]
    assert json.loads(request.content) == {"agent": "muse", "phone": PHONE}
    assert "Authorization" not in request.headers
    # The agent is told where the link went and which code its user types. There is no URL to open.
    assert f"texted a sign-in link to {TEXTED_TO}" in result.stderr
    assert "Tell the user this code." in result.stderr and "4821" in result.stderr
    assert "http" not in result.stderr
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == AGENT_TOKEN
    assert agent_config.get("agent_name") == "muse"
    assert agent_config.get("agent_origin") == AGENT_GATEWAY
    assert agent_config.get_agent_secret(CONNECT_TOKEN_NAME) is None  # used up
    assert agent_config.get("connect_match_code") is None
    assert agent_config.get("connect_texted_to") is None
    assert "snp_ct_" not in result.stdout + result.stderr  # no token is ever printed
    assert "snp_ag_" not in result.stdout + result.stderr


def test_a_new_sign_in_sends_the_token_held_and_keeps_it_until_the_user_approves(
    run_agent_cli, agent_config, httpx_mock
):
    connect_by_phone(agent_config, OLD_AGENT_TOKEN)
    started(httpx_mock)
    pending(httpx_mock)

    result = run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE, "--no-wait")

    assert json.loads(result.stdout)["status"] == "pending"
    # The token it held goes along, so the approval replaces that connection instead of adding one ...
    assert connect_requests(httpx_mock)[0].headers["Authorization"] == f"Bearer {OLD_AGENT_TOKEN}"
    # ... and it stays here, as it still works until then.
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == OLD_AGENT_TOKEN
    assert agent_config.get("agent_name") == "muse"
    assert agent_config.get_agent_secret(CONNECT_TOKEN_NAME) == CONNECT_TOKEN

    # A later run still sends it, so a request the user never approved can't leave a second connection.
    pending(httpx_mock)  # it asks about the earlier request first
    started(httpx_mock)
    pending(httpx_mock)
    run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE, "--no-wait")
    assert connect_requests(httpx_mock)[1].headers["Authorization"] == f"Bearer {OLD_AGENT_TOKEN}"

    connected(httpx_mock)
    run_agent_cli("agent", "connect", "--agent", "muse", "--resume")
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == AGENT_TOKEN  # replaced on approval


def test_a_token_held_from_another_gateway_is_not_sent_with_a_new_sign_in(run_agent_cli, agent_config, httpx_mock):
    connect_by_phone(agent_config, OLD_AGENT_TOKEN, origin="https://aipay.stage.snaplii.com")
    started(httpx_mock)
    pending(httpx_mock)

    run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE, "--no-wait")

    assert "Authorization" not in connect_requests(httpx_mock)[0].headers
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) is None
    assert agent_config.get("agent_origin") == AGENT_GATEWAY


def test_a_new_run_ends_the_earlier_unfinished_request(run_agent_cli, agent_config, httpx_mock):
    wait_for_sign_in(agent_config)
    pending(httpx_mock)  # the earlier request, still not approved
    started(httpx_mock)
    pending(httpx_mock)

    run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE, "--no-wait")

    assert json.loads(connect_requests(httpx_mock)[0].content) == {
        "agent": "muse", "phone": PHONE, "replaces": EARLIER_CONNECT_TOKEN}
    assert agent_config.get_agent_secret(CONNECT_TOKEN_NAME) == CONNECT_TOKEN


def test_a_new_run_collects_an_earlier_request_the_user_approved_instead_of_texting_again(
    run_agent_cli, agent_config, httpx_mock
):
    connect_by_phone(agent_config, OLD_AGENT_TOKEN)
    wait_for_sign_in(agent_config)
    connected(httpx_mock)

    result = run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE, "--no-wait")

    assert json.loads(result.stdout)["status"] == "connected"
    assert connect_requests(httpx_mock) == []  # nobody was texted
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == AGENT_TOKEN
    assert agent_config.get_agent_secret(CONNECT_TOKEN_NAME) is None


def test_waiting_at_a_gateway_without_phone_connections_says_so(run_agent_cli, agent_config, httpx_mock):
    wait_for_sign_in(agent_config)
    httpx_mock.add_response(url=COLLECT, method="POST", status_code=401, json=NO_AGENT_API)

    with pytest.raises(ConnectError, match="doesn't take phone connections right now"):
        run_agent_cli("agent", "connect", "--agent", "muse", "--resume")


def test_commands_to_copy_name_the_agent_as_the_gateway_does(run_agent_cli, httpx_mock):
    started(httpx_mock)
    pending(httpx_mock)

    result = run_agent_cli("agent", "connect", "--agent", " My Agent ", "--phone", PHONE, "--no-wait")

    assert "'snaplii agent connect --agent 'my agent' --resume'" in json.loads(result.stdout)["message"]


def test_no_wait_returns_pending_with_the_code_and_resume_goes_on_with_the_same_request_without_a_phone(
    run_agent_cli, agent_config, httpx_mock
):
    started(httpx_mock)
    pending(httpx_mock)

    first = run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE, "--no-wait")

    answer = json.loads(first.stdout)
    assert answer["status"] == "pending"
    assert answer["texted_to"] == TEXTED_TO
    assert answer["match_code"] == "4821"
    assert "snaplii agent connect --agent muse --resume" in answer["message"]

    connected(httpx_mock)
    second = run_agent_cli("agent", "connect", "--agent", "muse", "--resume")

    assert json.loads(second.stdout)["status"] == "connected"
    assert "Still waiting" in second.stderr
    assert TEXTED_TO in second.stderr and "4821" in second.stderr  # said again
    assert len(connect_requests(httpx_mock)) == 1  # one request only


def test_resume_with_nothing_to_resume_starts_a_new_sign_in(run_agent_cli, httpx_mock):
    started(httpx_mock)
    connected(httpx_mock)

    result = run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE, "--resume")

    assert "starting a new sign-in" in result.stderr
    assert json.loads(result.stdout)["status"] == "connected"


def test_waiting_stops_at_the_timeout_and_keeps_the_request(run_agent_cli, agent_config, httpx_mock):
    started(httpx_mock)
    pending(httpx_mock)

    result = run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE, "--timeout", "0")

    assert json.loads(result.stdout)["status"] == "pending"
    assert agent_config.get_agent_secret(CONNECT_TOKEN_NAME) == CONNECT_TOKEN


def test_an_expired_request_fails_and_takes_everything_it_waited_for_with_it(run_agent_cli, agent_config, httpx_mock):
    connect_by_phone(agent_config, OLD_AGENT_TOKEN)
    started(httpx_mock)
    httpx_mock.add_response(url=COLLECT, method="POST", status_code=400, json={
        "status": "error", "code": "invalid-connect-token", "message": "This sign-in request has expired."})

    with pytest.raises(ConnectError, match="expired, a newer one replaced it, or its token was already collected"):
        run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE)

    assert agent_config.get_agent_secret(CONNECT_TOKEN_NAME) is None
    for key in ("connect_agent_name", "connect_match_code", "connect_texted_to"):
        assert agent_config.get(key) is None
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == OLD_AGENT_TOKEN  # still the agent's


def test_any_other_refusal_of_the_swap_is_the_gateways_and_keeps_the_request(run_agent_cli, agent_config,
                                                                              httpx_mock):
    started(httpx_mock)
    httpx_mock.add_response(url=COLLECT, method="POST", status_code=400, json={
        "status": "error", "message": None, "errors": [{"field": "connect_token", "message": "must not be blank"}]})

    with pytest.raises(GatewayApiError) as refused:
        run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE)

    assert refused.value.to_dict()["error"] == "connect_token: must not be blank"
    assert agent_config.get_agent_secret(CONNECT_TOKEN_NAME) == CONNECT_TOKEN


def test_a_gateway_without_phone_connections_texts_nobody_and_keeps_the_token_held(run_agent_cli, agent_config,
                                                                                    httpx_mock):
    connect_by_phone(agent_config, OLD_AGENT_TOKEN)
    httpx_mock.add_response(url=CONNECT, method="POST", status_code=401, json=NO_AGENT_API)

    with pytest.raises(ConnectError, match="doesn't take phone connections right now"):
        run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE)

    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == OLD_AGENT_TOKEN
    assert agent_config.get_agent_secret(CONNECT_TOKEN_NAME) is None


def test_a_sign_in_without_a_phone_sends_nothing_and_keeps_the_token_held(run_agent_cli, agent_config, httpx_mock):
    connect_by_phone(agent_config, OLD_AGENT_TOKEN)

    result = run_agent_cli("agent", "connect", "--agent", "muse")

    assert result.exit_code == 2  # a usage error
    assert "--phone is needed" in result.stderr
    assert httpx_mock.get_requests() == []
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == OLD_AGENT_TOKEN


def test_the_region_says_how_to_read_a_number_without_plus_one(run_agent_cli, httpx_mock):
    started(httpx_mock)
    pending(httpx_mock)

    run_agent_cli("agent", "connect", "--agent", "muse", "--phone", "425 111 2222", "--region", "us", "--no-wait")

    assert json.loads(connect_requests(httpx_mock)[0].content) == {
        "agent": "muse", "phone": "425 111 2222", "region": "US"}


def test_a_gateway_that_signs_in_by_itself_has_no_text_and_no_code_to_tell(run_agent_cli, agent_config, httpx_mock):
    # A gateway in its dev sign-in mode approves the request as its configured test user.
    httpx_mock.add_response(
        url=CONNECT, method="POST", status_code=202,
        json={"connect_token": CONNECT_TOKEN, "expires_in": 600, "interval": 3},
    )
    connected(httpx_mock)

    result = run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE)

    assert json.loads(result.stdout)["status"] == "connected"
    assert "No text and no code" in result.stderr
    assert "Tell the user this code" not in result.stderr
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == AGENT_TOKEN


def test_the_agents_name_is_read_as_the_gateway_reads_it(run_agent_cli, agent_config, httpx_mock):
    # The gateway keeps "muse" for --agent Muse; the next run with --agent Muse is the same agent.
    connect_by_phone(agent_config, OLD_AGENT_TOKEN)
    started(httpx_mock)
    pending(httpx_mock)

    result = run_agent_cli("agent", "connect", "--agent", " Muse ", "--phone", PHONE, "--no-wait")

    assert json.loads(result.stdout)["status"] == "pending"
    connected(httpx_mock)
    assert json.loads(run_agent_cli("agent", "connect", "--agent", "MUSE", "--resume").stdout)["status"] == "connected"
    assert len(connect_requests(httpx_mock)) == 1  # --resume went on with the same request


def test_one_configuration_holds_one_agent(run_agent_cli, agent_config, httpx_mock):
    connect_by_phone(agent_config, AGENT_TOKEN)

    with pytest.raises(ConfigError, match="belongs to agent 'muse'.*SNAPLII_CONFIG_PATH"):
        run_agent_cli("agent", "connect", "--agent", "grok", "--phone", PHONE)

    assert httpx_mock.get_requests() == []
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == AGENT_TOKEN  # Muse is untouched


@pytest.mark.parametrize("code,status,message", [
    ("phone-not-allowlisted", 403,
     "Connecting an agent to Snaplii is in an invite-only alpha, and this phone number isn't invited."),
    ("unknown-agent", 400, "This agent can't connect to Snaplii."),
])
def test_a_refused_sign_in_shows_the_gateways_code_and_words(run_agent_cli, agent_config, httpx_mock,
                                                              code, status, message):
    connect_by_phone(agent_config, OLD_AGENT_TOKEN)
    httpx_mock.add_response(url=CONNECT, method="POST", status_code=status,
                            json={"status": "error", "code": code, "message": message})

    with pytest.raises(GatewayApiError) as refused:
        run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE)

    shown = refused.value.to_dict()
    assert shown["code"] == code
    assert shown["error"] == message  # the gateway's words, not a guess about API keys
    # Nothing was started, so the connection held stays.
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == OLD_AGENT_TOKEN


# --- where a sign-in may start, and where its tokens may go --------------------------------------


@pytest.mark.parametrize("base_url", ["https://aipayment.snaplii.com", "https://aipay.stage.snaplii.com",
                                      "http://localhost:8080", "http://127.0.0.1:8080"])
def test_a_sign_in_starts_at_the_snaplii_gateways_or_one_on_this_machine(run_agent_cli, httpx_mock, base_url):
    httpx_mock.add_response(url=f"{base_url}/api/agent/v1/connect", method="POST", status_code=202,
                            json={"connect_token": CONNECT_TOKEN, "match_code": "4821", "interval": 3})
    httpx_mock.add_response(url=f"{base_url}/api/agent/v1/connect/token", method="POST",
                            json={"status": "pending"})

    result = run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE, "--no-wait",
                           base_url=base_url)

    assert json.loads(result.stdout)["status"] == "pending"


def test_a_sign_in_at_any_other_gateway_is_refused_before_anything_is_sent(run_agent_cli, agent_config,
                                                                           httpx_mock):
    connect_by_phone(agent_config, OLD_AGENT_TOKEN)

    with pytest.raises(ConfigError, match="phone connection works only with the Snaplii gateways"):
        run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE, base_url="https://example.com")

    assert httpx_mock.get_requests() == []
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == OLD_AGENT_TOKEN


def test_the_token_is_never_sent_to_a_gateway_other_than_the_one_it_came_from(run_agent_cli, agent_config,
                                                                               httpx_mock):
    connect_by_phone(agent_config, AGENT_TOKEN, origin="https://aipay.stage.snaplii.com")

    with pytest.raises(ConnectError, match="connected by phone at https://aipay.stage.snaplii.com"):
        run_agent_cli("agent", "connection", base_url="https://aipayment.snaplii.com")

    assert httpx_mock.get_requests() == []


def test_without_a_keychain_or_file_storage_a_sign_in_is_refused_before_the_user_is_texted(
    run_agent_cli, agent_config, httpx_mock, monkeypatch
):
    import keyring
    from keyring.backends.fail import Keyring
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())

    with pytest.raises(ConfigError, match="No usable keyring"):
        run_agent_cli("agent", "connect", "--agent", "muse", "--phone", PHONE)

    assert httpx_mock.get_requests() == []


# --- signing in with the kept token ----------------------------------------------------------------


def test_connection_signs_in_with_the_kept_token(run_agent_cli, agent_config, httpx_mock):
    connect_by_phone(agent_config, AGENT_TOKEN)
    httpx_mock.add_response(url=CONNECTION, method="GET", json={**MUSE, "daily_limit_cents": 5000})

    result = run_agent_cli("agent", "connection")

    assert json.loads(result.stdout) == {
        "status": "connected", "agent": "muse", "daily_limit_cents": 5000, "currency": "CAD",
        "daily_limit": "CA$50.00",
    }
    assert httpx_mock.get_request().headers["Authorization"] == f"Bearer {AGENT_TOKEN}"


def test_connection_without_a_token_says_to_connect(run_agent_cli, httpx_mock):
    with pytest.raises(ConnectError, match="isn't connected by phone yet"):
        run_agent_cli("agent", "connection")

    assert httpx_mock.get_requests() == []


def test_connection_shows_whether_the_agent_can_buy(run_agent_cli, agent_config, httpx_mock):
    connect_by_phone(agent_config, AGENT_TOKEN)
    httpx_mock.add_response(url=CONNECTION, method="GET",
                            json={**MUSE, "connected_at": "2026-11-20T10:00:00Z", "can_buy": False})

    shown = json.loads(run_agent_cli("agent", "connection").stdout)

    assert shown["connected_at"] == "2026-11-20T10:00:00Z"
    assert shown["can_buy"] is False
    assert "connects again" in shown["message"] and "snaplii agent connect" in shown["message"]


def test_connection_with_a_dead_token_says_to_connect_again(run_agent_cli, agent_config, httpx_mock):
    connect_by_phone(agent_config, AGENT_TOKEN)
    httpx_mock.add_response(url=CONNECTION, method="GET", status_code=401, json=TOKEN_REFUSED)

    with pytest.raises(ConnectError, match="isn't connected any more"):
        run_agent_cli("agent", "connection")


def test_connection_at_a_gateway_without_phone_connections_does_not_say_disconnected(run_agent_cli, agent_config,
                                                                                      httpx_mock):
    connect_by_phone(agent_config, AGENT_TOKEN)
    httpx_mock.add_response(url=CONNECTION, method="GET", status_code=401, json=NO_AGENT_API)

    with pytest.raises(ConnectError, match="may not take phone connections right now"):
        run_agent_cli("agent", "connection")

    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == AGENT_TOKEN


# --- the agent disconnecting itself ---------------------------------------------------------------


def test_disconnect_ends_the_connection_and_drops_the_token(run_agent_cli, agent_config, httpx_mock):
    connect_by_phone(agent_config, AGENT_TOKEN)
    agent_config.set("country", "CA")
    httpx_mock.add_response(url=CONNECTION, method="DELETE", status_code=204)

    result = run_agent_cli("agent", "disconnect")

    shown = json.loads(result.stdout)
    assert shown["status"] == "disconnected"
    assert shown["agent"] == "muse"
    assert "snaplii agent connect --agent muse" in shown["message"]
    assert AGENT_TOKEN not in result.stdout
    assert httpx_mock.get_request().headers["Authorization"] == f"Bearer {AGENT_TOKEN}"
    # The configuration is free for any agent again, and keeps what isn't the connection's.
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) is None
    assert agent_config.get("agent_name") is None
    assert agent_config.get("country") == "CA"


def test_disconnect_with_a_token_that_already_stopped_working_still_drops_it(run_agent_cli, agent_config,
                                                                              httpx_mock):
    connect_by_phone(agent_config, AGENT_TOKEN)
    httpx_mock.add_response(url=CONNECTION, method="DELETE", status_code=401, json=TOKEN_REFUSED)

    shown = json.loads(run_agent_cli("agent", "disconnect").stdout)

    assert shown["status"] == "disconnected"
    assert "already stopped working" in shown["message"]
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) is None


def test_disconnect_at_a_gateway_without_phone_connections_keeps_the_token(run_agent_cli, agent_config, httpx_mock):
    # The gateway didn't end anything, so the token stays for a disconnect that can.
    connect_by_phone(agent_config, AGENT_TOKEN)
    httpx_mock.add_response(url=CONNECTION, method="DELETE", status_code=401, json=NO_AGENT_API)

    with pytest.raises(ConnectError, match="may not take phone connections right now"):
        run_agent_cli("agent", "disconnect")

    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == AGENT_TOKEN


def test_disconnect_collects_a_sign_in_the_user_approved_and_ends_that_connection(run_agent_cli, agent_config,
                                                                                   httpx_mock):
    # The approval replaced the old token's connection: ending it takes the new token.
    connect_by_phone(agent_config, OLD_AGENT_TOKEN)
    wait_for_sign_in(agent_config, connect_token=CONNECT_TOKEN)
    connected(httpx_mock)
    httpx_mock.add_response(url=CONNECTION, method="DELETE", status_code=204)

    shown = json.loads(run_agent_cli("agent", "disconnect").stdout)

    assert shown["status"] == "disconnected"
    [delete] = [r for r in httpx_mock.get_requests() if r.method == "DELETE"]
    assert delete.headers["Authorization"] == f"Bearer {AGENT_TOKEN}"
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) is None
    assert agent_config.get_agent_secret(CONNECT_TOKEN_NAME) is None


def test_disconnect_still_ends_the_connection_when_the_waiting_request_cant_be_checked(run_agent_cli, agent_config,
                                                                                      httpx_mock):
    connect_by_phone(agent_config, OLD_AGENT_TOKEN)
    wait_for_sign_in(agent_config, connect_token=CONNECT_TOKEN)
    httpx_mock.add_response(url=COLLECT, method="POST", status_code=503, json={"status": "error"})
    httpx_mock.add_response(url=CONNECTION, method="DELETE", status_code=204)

    shown = json.loads(run_agent_cli("agent", "disconnect").stdout)

    assert shown["status"] == "disconnected"
    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) is None


def test_disconnect_with_only_a_waiting_request_keeps_it_to_end_its_connection_later(run_agent_cli, agent_config,
                                                                                      httpx_mock):
    wait_for_sign_in(agent_config, connect_token=CONNECT_TOKEN)
    pending(httpx_mock)

    with pytest.raises(ConnectError, match="not to approve its link. If they did, run disconnect again"):
        run_agent_cli("agent", "disconnect")

    assert agent_config.get_agent_secret(CONNECT_TOKEN_NAME) == CONNECT_TOKEN


def test_disconnect_while_a_sign_in_waits_says_so_and_forgets_it(run_agent_cli, agent_config, httpx_mock):
    connect_by_phone(agent_config, OLD_AGENT_TOKEN)
    wait_for_sign_in(agent_config, connect_token=CONNECT_TOKEN)
    pending(httpx_mock)
    httpx_mock.add_response(url=CONNECTION, method="DELETE", status_code=204)

    shown = json.loads(run_agent_cli("agent", "disconnect").stdout)

    assert "tell them not to approve its link" in shown["message"]
    [delete] = [r for r in httpx_mock.get_requests() if r.method == "DELETE"]
    assert delete.headers["Authorization"] == f"Bearer {OLD_AGENT_TOKEN}"
    assert agent_config.get_agent_secret(CONNECT_TOKEN_NAME) is None


def test_disconnect_keeps_the_token_when_the_gateway_fails_so_it_can_be_run_again(run_agent_cli, agent_config,
                                                                                   httpx_mock):
    connect_by_phone(agent_config, AGENT_TOKEN)
    httpx_mock.add_response(url=CONNECTION, method="DELETE", status_code=503, json={"status": "error"})

    with pytest.raises(GatewayApiError):
        run_agent_cli("agent", "disconnect")

    assert agent_config.get_agent_secret(AGENT_TOKEN_NAME) == AGENT_TOKEN
    assert agent_config.get("agent_name") == "muse"


def test_disconnect_without_a_token_sends_nothing(run_agent_cli, httpx_mock):
    with pytest.raises(ConnectError, match="nothing to disconnect"):
        run_agent_cli("agent", "disconnect")

    assert httpx_mock.get_requests() == []


def test_config_show_never_prints_the_agents_tokens(run_agent_cli, agent_config):
    connect_by_phone(agent_config, AGENT_TOKEN)
    wait_for_sign_in(agent_config, connect_token=CONNECT_TOKEN)

    result = run_agent_cli("config", "show")

    assert result.exit_code == 0
    assert "snp_ag_" not in result.stdout and "snp_ct_" not in result.stdout

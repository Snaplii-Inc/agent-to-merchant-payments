"""login() must fail loudly when the gateway answers 2xx without an access token
(e.g. the core rejected the key but the gateway echoed HTTP 200), instead of
letting `snaplii init` print "authenticated" with nothing cached."""

import pytest
from click.testing import CliRunner

from snaplii.client import GatewayClient
from snaplii.commands.init import init_cmd
from snaplii.exceptions import GatewayApiError


class _RecordingStore:
    def __init__(self):
        self.cached = None
        self.values = {}

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def cache_token(self, token, expires_in):
        self.cached = (token, expires_in)

    def get_cached_token(self):
        return self.cached[0] if self.cached else None


def _client(store):
    return GatewayClient("https://gw.test", store)


def test_200_without_token_raises_and_caches_nothing(httpx_mock):
    # The exact shape the gateway produces today: HTTP 200, plain-text body
    # labeled application/json.
    httpx_mock.add_response(
        method="POST", url="https://gw.test/v2/auth/token", status_code=200,
        content=b"Snaplii core did not return an access token in the x-auth-token header",
        headers={"Content-Type": "application/json"},
    )
    store = _RecordingStore()
    with pytest.raises(GatewayApiError) as exc:
        _client(store).login("agent-1", "snp_sk_bogus")
    out = exc.value.to_dict()
    assert "did not return an access token" in out["error"]
    assert "x-auth-token header" in out["error"]  # the gateway's reason is kept
    assert store.cached is None


def test_200_with_core_business_error_surfaces_rspmsginf(httpx_mock):
    # Once the gateway passes core's rspMsgCd/rspMsgInf through, the CLI must
    # show that reason rather than a generic message.
    httpx_mock.add_response(
        method="POST", url="https://gw.test/v2/auth/token", status_code=200,
        json={"rspMsgCd": "MCA20102", "rspMsgInf": "API key has been deactivated"},
    )
    store = _RecordingStore()
    with pytest.raises(GatewayApiError) as exc:
        _client(store).login("agent-1", "snp_sk_dead")
    out = exc.value.to_dict()
    # The rspMsgCd path already raises inside _parse_response with the mapped
    # friendly text; either way the user learns the key is deactivated.
    assert "deactivated" in out["error"].lower()
    assert store.cached is None


def test_200_empty_json_without_token_raises(httpx_mock):
    httpx_mock.add_response(
        method="POST", url="https://gw.test/v2/auth/token", status_code=200, json={},
    )
    store = _RecordingStore()
    with pytest.raises(GatewayApiError):
        _client(store).login("agent-1", "snp_sk_x")
    assert store.cached is None


def test_login_with_token_still_caches(httpx_mock):
    httpx_mock.add_response(
        method="POST", url="https://gw.test/v2/auth/token", status_code=200,
        json={"access_token": "jwt-1", "expires_in": 600, "country": "US"},
    )
    store = _RecordingStore()
    resp = _client(store).login("agent-1", "snp_sk_ok")
    assert resp["access_token"] == "jwt-1"
    assert store.cached == ("jwt-1", 600)
    assert store.values["country"] == "US"


def test_init_does_not_print_authenticated_without_token():
    class FailingClient:
        def login(self, agent_id, api_key):
            raise GatewayApiError(200, {"friendly_message": "Login did not return an access token"},
                                  "/v2/auth/token")

    store = _RecordingStore()
    result = CliRunner().invoke(
        init_cmd, [], input="snp_sk_bogus\n",
        obj={"client": FailingClient(), "config_store": store},
    )
    assert result.exit_code != 0
    assert "authenticated" not in result.output
    assert isinstance(result.exception, GatewayApiError)

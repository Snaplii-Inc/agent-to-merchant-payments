"""login() must fail loudly when a 2xx login reply carries no access token,
instead of letting `snaplii init` print "authenticated" with nothing cached."""

import pytest
import keyring
from keyring.backends.fail import Keyring
from click.testing import CliRunner

from snaplii.client import GatewayClient
from snaplii.commands.init import init_cmd
from snaplii.exceptions import GatewayApiError
from snaplii.config_store import ConfigStore
from snaplii.exceptions import AuthError


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

    def commit_session(self, token, expires_in, **metadata):
        self.cached = (token, expires_in)
        self.values.update(metadata)

    def auth_status(self, *, origin):
        return {"host": "unknown", "auth_method": self.values.get("auth_method")}

    def get_cached_token(self, *, origin=None):
        return self.cached[0] if self.cached else None


def _client(store):
    return GatewayClient("https://aipayment.snaplii.com", store)


def test_200_without_token_raises_and_caches_nothing(httpx_mock):
    # HTTP 200 with a plain-text body labeled application/json.
    httpx_mock.add_response(
        method="POST", url="https://aipayment.snaplii.com/v2/auth/token", status_code=200,
        content=b"Snaplii core did not return an access token in the x-auth-token header",
        headers={"Content-Type": "application/json"},
    )
    store = _RecordingStore()
    with pytest.raises(GatewayApiError) as exc:
        _client(store).login("agent-1", "snp_sk_live_bogus000000000000000000000000000")
    out = exc.value.to_dict()
    assert "did not return an access token" in out["error"]
    assert "x-auth-token header" not in out["error"]  # no raw upstream text
    assert store.cached is None


def test_200_with_core_business_error_surfaces_rspmsginf(httpx_mock):
    # Once the gateway passes core's rspMsgCd/rspMsgInf through, the CLI must
    # show that reason rather than a generic message.
    httpx_mock.add_response(
        method="POST", url="https://aipayment.snaplii.com/v2/auth/token", status_code=200,
        json={"rspMsgCd": "MCA20102", "rspMsgInf": "API key has been deactivated"},
    )
    store = _RecordingStore()
    with pytest.raises(GatewayApiError) as exc:
        _client(store).login("agent-1", "snp_sk_live_dead0000000000000000000000000000")
    out = exc.value.to_dict()
    # The rspMsgCd path already raises inside _parse_response with the mapped
    # friendly text; either way the user learns the key is deactivated.
    assert "deactivated" in out["error"].lower()
    assert store.cached is None


def test_200_empty_json_without_token_raises(httpx_mock):
    httpx_mock.add_response(
        method="POST", url="https://aipayment.snaplii.com/v2/auth/token", status_code=200, json={},
    )
    store = _RecordingStore()
    with pytest.raises(GatewayApiError):
        _client(store).login("agent-1", "snp_sk_live_x0000000000000000000000000000000")
    assert store.cached is None


def test_login_with_token_still_caches(httpx_mock):
    httpx_mock.add_response(
        method="POST", url="https://aipayment.snaplii.com/v2/auth/token", status_code=200,
        json={"access_token": "jwt-1", "expires_in": 600, "country": "US"},
    )
    store = _RecordingStore()
    resp = _client(store).login("agent-1", "snp_sk_live_ok000000000000000000000000000000")
    assert resp["access_token"] == "jwt-1"
    assert store.cached == ("jwt-1", 600)
    assert store.values["country"] == "US"


def test_init_does_not_print_authenticated_without_token():
    class FailingClient:
        origin = "https://aipayment.snaplii.com"

        def auth_status(self):
            return {"host": "unknown", "has_valid_token": False}

        def login(self, agent_id, api_key):
            raise GatewayApiError(200, {"friendly_message": "Login did not return an access token"},
                                  "/v2/auth/token")

    store = _RecordingStore()
    result = CliRunner().invoke(
        init_cmd, [], input="snp_sk_live_bogus000000000000000000000000000\n",
        obj={"client": FailingClient(), "config_store": store},
    )
    assert result.exit_code != 0
    assert "authenticated" not in result.output
    assert isinstance(result.exception, GatewayApiError)


@pytest.mark.parametrize("ttl", [None, True, "600", 0, -1, 90, 3600.5])
def test_invalid_expiry_does_not_replace_existing_identity(httpx_mock, tmp_path, monkeypatch, ttl):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    store = ConfigStore(tmp_path / "config.json")
    store.set("agent_id", "previous-agent")
    httpx_mock.add_response(method="POST", url="https://aipayment.snaplii.com/v2/auth/token",
                            json={"access_token": "new-token", "expires_in": ttl})
    with pytest.raises(AuthError) as exc:
        _client(store).login("new-agent", "snp_sk_live_syntheticapikey00000000000000000")
    assert exc.value.auth_state == "auth_response_invalid"
    assert store.get("agent_id") == "previous-agent"
    assert store.get_cached_token() is None


def test_login_commits_identity_method_and_origin_together(httpx_mock, tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    store = ConfigStore(tmp_path / "config.json")
    httpx_mock.add_response(method="POST", url="https://aipayment.snaplii.com/v2/auth/token",
                            json={"access_token": "new-token", "expires_in": 604800, "country": "US"})
    _client(store).login("new-agent", "snp_sk_live_syntheticapikey00000000000000000")
    status = store.auth_status(origin="https://aipayment.snaplii.com")
    assert status["agent_id"] == "new-agent"
    assert status["auth_method"] == "api_key"
    assert status["has_valid_token"] is True
    assert store.get_cached_token(origin="https://aipay.stage.snaplii.com") is None


@pytest.mark.parametrize("code", [["synthetic-secret"], {"synthetic-secret": True}, 42])
def test_invalid_auth_error_code_is_still_safe_json(httpx_mock, tmp_path, monkeypatch, code):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    httpx_mock.add_response(status_code=500, json={"rspMsgCd": code, "friendly_message": "synthetic-secret"})
    with pytest.raises(GatewayApiError) as exc:
        _client(ConfigStore(tmp_path / "config.json")).login("agent-1", "snp_sk_live_synthetickey00000000000000000000")
    assert "synthetic-secret" not in str(exc.value.to_dict())


GOOD_KEY = "snp_sk_live_" + "A1b2" * 8
URL = "https://aipayment.snaplii.com/v2/auth/token"


@pytest.mark.parametrize("message, code", [
    ("Snaplii core rejected the credentials (MCA20101: Unable to complete the request. Please try again later.)", "MCA20101"),
    ("Snaplii core rejected the credentials (MCA20102: This API key has been deactivated.)", "MCA20102"),
    ("Snaplii core rejected the credentials", ""),
])
def test_the_gateways_own_rejection_means_the_key_was_refused(httpx_mock, message, code):
    httpx_mock.add_response(method="POST", url=URL, status_code=401, json={"status": "error", "message": message})
    with pytest.raises(GatewayApiError) as exc:
        _client(_RecordingStore()).login("agent-1", GOOD_KEY)
    assert exc.value.auth_fields["auth_state"] == "invalid_key"
    assert exc.value.body.get("rspMsgCd", "") == code


@pytest.mark.parametrize("status, kwargs", [
    (401, {"text": "Unauthorized"}),
    (401, {"html": "<html><body>401 Authorization Required</body></html>"}),
    (403, {"json": {"error": "forbidden", "message": "Request blocked"}}),
    (401, {"json": {"status": "error", "message": "Invalid token"}}),
])
def test_a_rejection_not_from_the_gateway_does_not_condemn_the_key(httpx_mock, status, kwargs):
    httpx_mock.add_response(method="POST", url=URL, status_code=status, **kwargs)
    with pytest.raises(GatewayApiError) as exc:
        _client(_RecordingStore()).login("agent-1", GOOD_KEY)
    fields = exc.value.auth_fields
    assert (fields["auth_state"], fields["reason_code"]) == ("auth_response_invalid", "auth_rejected_unverified")
    assert fields["next_action"] == {"type": "stop", "reason": "auth_response_invalid"}
    assert "key may still be valid" in exc.value.to_dict()["error"]

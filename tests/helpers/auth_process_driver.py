"""Exercise real CLI/client/store code in an isolated child, with fake I/O only."""
import io
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

import httpx
import keyring
from keyring.backends.fail import Keyring
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "snaplii-cli" / "src"))
from snaplii import auth
from snaplii import cli
from snaplii.config_store import ConfigStore

path, operation, host = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
counts = {"auth": 0, "protected": 0}
client_type = httpx.Client


def transport(request):
    assert request.url.path == "/v2/balance"
    assert request.headers["Authorization"] == "Bearer synthetic-process-token"
    counts["protected"] += 1
    return httpx.Response(200, json={"data": {"balance": 42}})


def secure_exchange(opener, request, timeout):
    assert operation == "init", "protected commands must not exchange tokens implicitly"
    assert request.full_url == auth.DEFAULT_ORIGIN + "/v2/auth/token"
    assert list(json.loads(request.data)) == ["agent_id"]
    counts["auth"] += 1
    response = io.BytesIO(b'{"access_token":"synthetic-process-token","expires_in":604800,"country":"CA"}')
    response.status = 200
    return response


with patch.object(auth, "detect_muse", lambda: auth.MuseEnvironment(host == "muse", "test_only")), \
     patch.object(keyring, "get_keyring", lambda: Keyring()), \
     patch.dict(os.environ, {"SNAPLII_ALLOW_INSECURE": "0", "SNAPLII_VAULT_HELPER_PATH": str(Path(__file__).parent)}), \
     patch.object(cli, "ConfigStore", lambda: ConfigStore(path)), \
     patch.object(cli, "check_for_update", lambda *a, **kw: None), \
     patch.object(httpx, "Client", lambda **kwargs: client_type(transport=httpx.MockTransport(transport), **kwargs)), \
     patch("urllib.request.OpenerDirector.open", secure_exchange):
    args = ["init", "--vault-auth"] if operation == "init" else ["balance"]
    result = CliRunner().invoke(cli.main, args)
    if result.exception is not None:
        output = result.exception.to_dict()
    else:
        output = json.loads(result.output)
    state = ConfigStore(path).auth_status(origin=auth.DEFAULT_ORIGIN)
    print(json.dumps({"pid": os.getpid(), "counts": counts, "output": output, "state": state}))

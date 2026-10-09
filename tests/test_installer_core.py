import ast
import os
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install.py"


def test_script_parses_under_python_3_8_grammar():
    ast.parse(SCRIPT.read_text(), filename=str(SCRIPT), feature_version=(3, 8))


def test_failure_to_dict_carries_every_field(installer):
    failure = installer.InstallFailure("pip", "index_unreachable", "PyPI unreachable",
                                       "check the network, then re-run", retryable=True,
                                       diagnostics="Could not fetch URL https://pypi.org/simple/")
    assert failure.to_dict() == {
        "stage": "pip", "code": "index_unreachable", "message": "PyPI unreachable",
        "remedy": "check the network, then re-run", "retryable": True,
        "diagnostics": "Could not fetch URL https://pypi.org/simple/",
    }


@pytest.mark.parametrize("raw, expected", [
    ("https://user:hunter2@mirror.example/simple", "https://[redacted]@mirror.example/simple"),
    ("https://user@mirror.example/simple", "https://[redacted]@mirror.example/simple"),
    ("key snp_sk_live_ABC123_xyz here", "key [redacted] here"),
    ("Authorization: Bearer eyJhbGci.abc-def", "Authorization: Bearer [redacted]"),
    ("token=abcdef&x=1", "token=[redacted]&x=1"),
    ('{"access_token": "abc.def"}', '{"access_token": "[redacted]"}'),
    ("api_key: snp_sk_test", "api_key: [redacted]"),
    ("PASSWORD=pw123", "PASSWORD=[redacted]"),
    ("X-Amz-Signature=deadbeef&X-Amz-Date=1", "X-Amz-Signature=[redacted]&X-Amz-Date=1"),
    ("sig=abc123", "sig=[redacted]"),
    ("nothing secret here", "nothing secret here"),
])
def test_redact_patterns(installer, raw, expected):
    assert installer.redact(raw) == expected


def test_line_buffer_redacts_before_retaining_and_drops_whole_lines(installer):
    buf = installer.LineBuffer()
    buf.add_bytes(b"https://u:SENTINEL1@host/x")
    assert "SENTINEL1" not in buf.text()
    for i in range(installer.MAX_LINES + 50):
        buf.add_bytes(("line %d" % i).encode())
    assert len(buf.text().splitlines()) == installer.MAX_LINES
    assert buf.text().splitlines()[0] == "line 50"


def test_line_buffer_discards_overlong_lines_entirely(installer):
    buf = installer.LineBuffer()
    long = b"https://u:SENTINEL2" + b"x" * installer.MAX_LINE + b"@host"
    buf.add_bytes(long)
    assert "SENTINEL2" not in buf.text()
    assert buf.text() == "[line of %d bytes discarded]" % len(long)
    assert buf.discarded == 1


def test_line_buffer_byte_bound_and_tail(installer):
    buf = installer.LineBuffer()
    for i in range(300):
        buf.add_bytes(b"y" * 1024)
    assert sum(len(l) for l in buf.text().splitlines()) <= installer.MAX_BYTES
    assert len(buf.tail(lines=40, limit=10 ** 6).splitlines()) == 40
    assert len(buf.tail(lines=40)) <= 8192
    assert len(buf.tail(lines=40, limit=2048)) <= 2048


def test_line_buffer_decodes_non_utf8_without_raising(installer):
    buf = installer.LineBuffer()
    buf.add_bytes(b"Zugriff verweigert \xe4 Could not fetch URL")
    assert "Could not fetch URL" in buf.text()


def test_detect_host_instinct_by_variable_name_not_value(installer, clean_env, monkeypatch):
    monkeypatch.setenv("INSTINCT_WHATEVER", "")
    host = installer.detect_host(dict(os.environ), exists=lambda p: False)
    assert host["detected"] == "instinct"
    assert host["instinct_variables"] == ["INSTINCT_WHATEVER"]
    assert "platform" in host


def test_detect_host_muse_wins_over_instinct_and_uses_auth_constants(installer, clean_env, monkeypatch):
    monkeypatch.setenv("INSTINCT_X", "1")
    from snaplii import auth
    assert installer.MUSE_HELPER == str(auth.MUSE_HELPER)
    assert installer.MUSE_SOCKET == str(auth.MUSE_SOCKET)
    assert installer.INSTINCT_PREFIX == auth.INSTINCT_ENV_PREFIX
    muse_paths = {installer.MUSE_HELPER, installer.MUSE_SOCKET}
    host = installer.detect_host(dict(os.environ), exists=lambda p: p in muse_paths)
    assert host["detected"] == "muse"


def test_detect_host_unknown(installer, clean_env):
    assert installer.detect_host(dict(os.environ), exists=lambda p: False)["detected"] == "unknown"


def test_child_env_drops_python_and_pip_but_keeps_mirrors_and_proxies(installer):
    base = {"PATH": "/bin", "PYTHONPATH": "/x", "PYTHONHOME": "/y", "PYTHONPYCACHEPREFIX": "/z",
            "PIP_TARGET": "/t", "PIP_PYTHON": "/p", "PIP_REPORT": "/r", "PIP_INDEX_URL": "https://m/simple",
            "PIP_TIMEOUT": "9", "HTTPS_PROXY": "http://proxy:3128", "REQUESTS_CA_BUNDLE": "/ca.pem",
            "UV_NO_MANAGED_PYTHON": "1", "UV_PYTHON_INSTALL_MIRROR": "https://mirror", "UV_INSTALL_DIR": "/u"}
    env = installer.child_env(base)
    for gone in ("PYTHONPATH", "PYTHONHOME", "PYTHONPYCACHEPREFIX", "PIP_TARGET", "PIP_PYTHON", "PIP_REPORT"):
        assert gone not in env
    assert env["PIP_INDEX_URL"] == "https://m/simple" and env["PIP_TIMEOUT"] == "9"
    assert env["HTTPS_PROXY"] == "http://proxy:3128" and env["REQUESTS_CA_BUNDLE"] == "/ca.pem"
    assert env["PIP_CONFIG_FILE"] == os.devnull
    assert env["PIP_NO_INPUT"] == "1" and env["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8" and env["PYTHONNOUSERSITE"] == "1"
    assert "PYTHONDONTWRITEBYTECODE" not in env
    assert env["UV_NO_MANAGED_PYTHON"] == "1"  # only scrubbed for uv calls


def test_child_env_check_mode_and_uv_scrub(installer):
    base = {"UV_NO_MANAGED_PYTHON": "1", "UV_MANAGED_PYTHON": "1", "UV_SYSTEM_PYTHON": "1", "UV_PYTHON": "x",
            "UV_PYTHON_DOWNLOADS": "never", "UV_PYTHON_PREFERENCE": "system",
            "UV_PYTHON_INSTALL_MIRROR": "https://mirror", "UV_INSTALL_DIR": "/u", "UV_CACHE_DIR": "/c",
            "UV_NATIVE_TLS": "1", "HTTP_PROXY": "http://p"}
    env = installer.child_env(base, check_mode=True, for_uv=True)
    assert env["PYTHONDONTWRITEBYTECODE"] == "1"
    for gone in installer.UV_SCRUB:
        assert gone not in env
    for kept in ("UV_PYTHON_INSTALL_MIRROR", "UV_INSTALL_DIR", "UV_CACHE_DIR", "UV_NATIVE_TLS", "HTTP_PROXY"):
        assert env[kept] == base[kept]


def test_redaction_keeps_json_documents_parseable(installer):
    import json
    doc = '{"api_key": null, "token": 12345, "session": {"id": "abc"}, "password": "pw", "version": "0.19.0"}'
    redacted = installer.redact(doc)
    parsed = json.loads(redacted)
    assert parsed["api_key"] == "[redacted]" and parsed["token"] == "[redacted]" and parsed["password"] == "[redacted]"
    assert parsed["session"] == {"id": "abc"} and parsed["version"] == "0.19.0"

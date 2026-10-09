import ast
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

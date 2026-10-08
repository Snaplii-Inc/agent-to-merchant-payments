import pytest

from snaplii import auth


def test_prefix_variable_selects_instinct(monkeypatch):
    monkeypatch.setenv("INSTINCT_REGION", "")
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    assert auth.instinct_environment_status() == {
        "detected": True, "reason_code": "instinct_env_present",
        "env_names": ["INSTINCT_AGENT_ID", "INSTINCT_REGION"],
    }
    assert auth.detect_instinct() is True


def test_other_names_do_not_select_instinct(monkeypatch):
    monkeypatch.setenv("MY_INSTINCT_FLAG", "1")
    monkeypatch.setenv("instinct_lowercase", "1")
    assert auth.instinct_environment_status() == {
        "detected": False, "reason_code": "instinct_env_absent", "env_names": [],
    }
    assert auth.detect_instinct() is False


def test_muse_takes_precedence(monkeypatch, muse_filesystem):
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    status = auth.instinct_environment_status()
    assert status == {"detected": False, "reason_code": "muse_takes_precedence",
                      "env_names": ["INSTINCT_AGENT_ID"]}


def test_explicit_environment_returns_sorted_names_only():
    names = auth.instinct_env_names({"INSTINCT_B": "secret", "INSTINCT_A": "x", "OTHER": "y"})
    assert names == ["INSTINCT_A", "INSTINCT_B"]


@pytest.mark.parametrize("base_url,entry", [
    ("https://aipayment.snaplii.com", "Snaplii API Key"),
    ("https://aipayment.snaplii.com/", "Snaplii API Key"),
    ("https://aipay.stage.snaplii.com", "Snaplii API Key aipay.stage.snaplii.com"),
    ("http://localhost:8080", "Snaplii API Key localhost:8080"),
    ("https://aipayment.snaplii.com/gw", "Snaplii API Key aipayment.snaplii.com"),
])
def test_vault_entry_names(base_url, entry):
    assert auth.instinct_vault_entry(base_url) == entry


def test_instruction_covers_the_vault_flow_without_raw_key_entry():
    text = " ".join(auth.INSTINCT_AUTH_INSTRUCTION.split())
    for phrase in (
        "snaplii_connect", "vault_entry", "eid", "Connect", "2 minutes",
        "More → Payment Methods → AI Payment Management → + New API Key",
        "encrypted submission link", "has_valid_token=true", "never call snaplii_init",
        "Do not connect at the start of unrelated conversations",
    ):
        assert phrase in text
    assert "paste their Snaplii API key" not in text

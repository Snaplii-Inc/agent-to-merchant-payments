"""openapi.yaml is the gateway contract for Snaplii's own CLI and MCP server.

It must stay current, carry machine-readably the rules the skill, MCP server and CLI apply
for the agent, and tell AI agents not to call the gateway directly."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "openapi.yaml").read_text())
README = (ROOT / "README.md").read_text()
REQUIRED_RULES = {
    "agents_use_skill_or_mcp", "api_key_off_chat", "instinct_mcp_only", "muse_stored_key_only", "item_id_format", "denomination_check", "quote_before_purchase",
    "no_blind_purchase_retry", "bill_pay_irreversible", "sensitive_card_data", "transfer_idempotency",
    "transfer_disclosure", "spending_limits",
}


def flat(text):
    return " ".join(str(text).split())


def package_version(folder):
    return re.search(r'^version = "([^"]+)"', (ROOT / folder / "pyproject.toml").read_text(), re.M).group(1)


def operation_ids():
    return {op["operationId"] for item in SPEC["paths"].values() for op in item.values() if isinstance(op, dict)}


def test_spec_version_matches_both_packages():
    assert SPEC["info"]["version"] == package_version("snaplii-cli") == package_version("mcp-server")


def test_every_gateway_path_the_clients_call_is_documented():
    sources = [ROOT / "snaplii-cli/src/snaplii/client.py", ROOT / "mcp-server/server.py",
               *sorted((ROOT / "snaplii-cli/src/snaplii/commands").glob("*.py"))]
    code = "\n".join(path.read_text() for path in sources)
    shape = lambda path: re.sub(r"\{[^}]*\}", "{}", path.rstrip("/"))
    used = {shape(path) for path in re.findall(r"/v2/[A-Za-z0-9_/{}.\-]+", code)}
    documented = {shape(path) for path in SPEC["paths"]}
    assert used - documented == set()


def test_spec_carries_every_agent_rule():
    rules = {rule["id"]: rule for rule in SPEC["info"]["x-agent-rules"]}
    assert REQUIRED_RULES <= set(rules)
    known = operation_ids()
    for rule_id, rule in rules.items():
        assert set(rule) == {"id", "applies_to", "rule"}, rule_id
        assert flat(rule["rule"]), rule_id
        assert set(rule["applies_to"]) <= known, rule_id


def test_bill_pay_rule_states_irreversibility_not_a_confirmation_script():
    rule = {r["id"]: r for r in SPEC["info"]["x-agent-rules"]}["bill_pay_irreversible"]
    text = flat(rule["rule"]).lower()
    assert "cannot be undone" in text and "current turn" not in text and "explicit" not in text


def test_spec_tells_agents_not_to_call_it_directly():
    description = flat(SPEC["info"]["description"])
    assert "AI agents must not call it directly" in description
    assert "Agent Skill" in description and "MCP server" in description and "x-agent-rules" in description
    text = (ROOT / "openapi.yaml").read_text().lower()
    for phrase in ("direct_caller", "direct caller", "calls this api directly", "prefer the snaplii"):
        assert phrase not in text, phrase


def test_order_item_states_the_item_id_rule():
    description = flat(SPEC["components"]["schemas"]["OrderItem"]["properties"]["itemId"]["description"])
    assert "{cardBrandId}-{cardTemplateId}" in description and "verbatim" in description


def test_readme_does_not_mention_the_rest_api():
    # The README routes every reader to the skill, the MCP server or the CLI only.
    for phrase in ("REST", "openapi.yaml", "curl -X POST https://aipayment", "/v2/", "HTTPS request", "HTTPS calls"):
        assert phrase not in README, phrase


# openapi.yaml is published to the public: it states the contract and the caller's duties, and
# never internal implementation notes. This list holds only generic markers of such notes.
PRIVATE_IN_PUBLIC_SPEC = ["enforced_by", "x-source-files", "in this repository", "locally", "legacy", "the client"]


@pytest.mark.parametrize("phrase", PRIVATE_IN_PUBLIC_SPEC)
def test_public_spec_keeps_internal_notes_out(phrase):
    assert phrase.lower() not in (ROOT / "openapi.yaml").read_text().lower()

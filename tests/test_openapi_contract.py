"""openapi.yaml is what an agent reads when it calls the gateway without the skill or MCP.

It must stay current and carry, machine-readably, every rule the skill, MCP server and CLI
apply for the agent, so a direct caller can apply them too."""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = yaml.safe_load((ROOT / "openapi.yaml").read_text())
README = (ROOT / "README.md").read_text()
REQUIRED_RULES = {
    "api_key_off_chat", "instinct_mcp_only", "item_id_format", "denomination_check", "quote_before_purchase",
    "no_blind_purchase_retry", "bill_pay_confirmation", "sensitive_card_data", "transfer_idempotency",
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


def test_spec_carries_every_agent_rule_with_what_a_direct_caller_must_do():
    rules = {rule["id"]: rule for rule in SPEC["info"]["x-agent-rules"]}
    assert REQUIRED_RULES <= set(rules)
    known = operation_ids()
    for rule_id, rule in rules.items():
        assert set(rule) == {"id", "applies_to", "rule", "direct_caller"}, rule_id
        assert flat(rule["rule"]) and flat(rule["direct_caller"]), rule_id
        assert set(rule["applies_to"]) <= known, rule_id


def test_spec_tells_agents_to_prefer_the_skill_or_mcp():
    description = flat(SPEC["info"]["description"])
    assert "Agent Skill" in description and "MCP server" in description and "x-agent-rules" in description


def test_order_item_states_the_item_id_rule():
    description = flat(SPEC["components"]["schemas"]["OrderItem"]["properties"]["itemId"]["description"])
    assert "{cardBrandId}-{cardTemplateId}" in description and "verbatim" in description


def test_readme_rest_section_sends_agents_to_the_skill_or_mcp_and_lists_the_rules():
    section = README.split("### REST API (Any LLM)", 1)[1].split("\n### ", 1)[0]
    intro = flat(section.split("**Base URL:**", 1)[0])
    assert "Agent Skill" in intro and "MCP server" in intro and "x-agent-rules" in intro
    rows = [line for line in section.splitlines() if line.startswith("| ") and "---" not in line]
    assert len(rows) >= len(REQUIRED_RULES) - 2  # header plus one row per rule group


# openapi.yaml is published to the public: it states the contract and the caller's duties, and
# never internal implementation notes. This list holds only generic markers of such notes.
PRIVATE_IN_PUBLIC_SPEC = ["enforced_by", "x-source-files", "in this repository", "locally", "legacy", "the client"]


@pytest.mark.parametrize("phrase", PRIVATE_IN_PUBLIC_SPEC)
def test_public_spec_keeps_internal_notes_out(phrase):
    assert phrase.lower() not in (ROOT / "openapi.yaml").read_text().lower()

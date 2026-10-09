"""The gift-card item_id format must be stated prominently wherever an agent quotes or buys a card.

A well-formed ID of another card buys that card,
so every agent-facing surface says: exactly {cardBrandId}-{cardTemplateId}, copied verbatim."""
import asyncio
from pathlib import Path

import pytest
from click.testing import CliRunner

import server
from snaplii.commands.purchase import purchase_cmd
from snaplii.commands.quote import quote_cmd

ROOT = Path(__file__).resolve().parents[1]
FORMAT = "{cardBrandId}-{cardTemplateId}"


def flat(text):
    return " ".join(text.split())


@pytest.mark.parametrize("relative, rules_heading", [
    ("skills/snaplii-cli.md", "## Important Rules"),
    ("clawhub-publish/SKILL.md", "## Important Rules"),
    ("skills/snaplii-autopilot.md", "## Rules"),
    ("clawhub-autopilot/SKILL.md", "## Rules"),
])
def test_skills_make_the_item_id_format_a_rule_and_repeat_it_where_cards_are_bought(relative, rules_heading):
    text = (ROOT / relative).read_text()
    rules = flat(text.split(rules_heading, 1)[1].split("\n## ", 1)[0])
    assert FORMAT in rules and "verbatim" in rules
    flow = flat(text.split("## Decision Flow" if "snaplii-cli" in relative or "publish" in relative else "## Full Flow", 1)[1])
    assert flow.count(FORMAT) >= 1 and "verbatim" in flow


def test_mcp_tools_and_instructions_state_the_item_id_format():
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    for name in ("snaplii_quote", "snaplii_purchase"):
        description = tools[name].inputSchema["properties"]["item_id"]["description"]
        assert FORMAT in description and "verbatim" in description, name
    assert "verbatim" in tools["snaplii_browse_brand"].description
    instructions = flat(server._SERVER_INSTRUCTIONS)
    assert FORMAT in instructions and "verbatim" in instructions


@pytest.mark.parametrize("command", [quote_cmd, purchase_cmd])
def test_cli_help_states_the_item_id_format(command):
    help_text = flat(CliRunner().invoke(command, ["--help"]).output)
    assert FORMAT in help_text and "verbatim" in help_text


def test_readmes_state_the_item_id_format():
    readme = (ROOT / "README.md").read_text()
    rules = flat(readme.split("### Rules the skill enforces", 1)[1].split("\n### ", 1)[0])
    assert FORMAT in rules and "verbatim" in rules
    cli_note = flat(readme.split("snaplii purchase --item-id CB...-CT... --price 50", 1)[1].split("\n## ", 1)[0])
    assert FORMAT in cli_note and "verbatim" in cli_note
    package = flat((ROOT / "snaplii-cli" / "README.md").read_text())
    assert FORMAT in package and "verbatim" in package

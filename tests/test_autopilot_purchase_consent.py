"""Autopilot buys the gift card before it places the merchant order.

So every autopilot surface waits for the user's "yes" to the quote before the purchase,
says the card stays in the account if the order is not placed, and the standalone skill
shows a redemption code in chat only when the user asks for it or agrees."""
import asyncio
from pathlib import Path

import pytest

import server

ROOT = Path(__file__).resolve().parents[1]


def flat(text):
    return " ".join(text.split())


@pytest.mark.parametrize("relative", [
    "skills/snaplii-autopilot.md",
    "clawhub-autopilot/SKILL.md",
    "claude-plugin/skills/snaplii-autopilot/SKILL.md",
    "cursor-plugin/skills/snaplii-autopilot/SKILL.md",
])
def test_autopilot_skills_wait_for_a_yes_to_the_quote_before_buying(relative):
    text = flat((ROOT / relative).read_text())
    buy = text.split("### 2. Buy", 1)[1].split("### 3.", 1)[0]
    assert 'explicit "yes" to buy the card' in buy
    assert "stays in their Snaplii account" in text
    # A corrected retry after a refused card or amount asks again when the quote changed.
    assert '"yes" to the new quote before buying' in text


def test_autopilot_prompt_waits_for_a_yes_to_the_quote_before_buying():
    result = asyncio.run(server.get_prompt("snaplii_autopilot", {"request": "order me a coffee"}))
    text = flat(result.messages[0].content.text)
    quote = text.split("4. Quote:", 1)[1].split("5. Buy:", 1)[0]
    step = text.split("5. Buy:", 1)[1].split("6. Redeem", 1)[0]
    # The user sees what the card is and that it is charged first before being asked.
    assert "card amount" in quote and "stays in their Snaplii account" in quote
    assert step.index('explicit "yes" to the quote') < step.index("call snaplii_purchase")
    assert "Report brand and amount" in step and "not into the chat" in step
    assert "immediately hand over the redemption code" not in text


def test_standalone_autopilot_shows_a_code_in_chat_only_on_request_or_agreement():
    text = flat((ROOT / "clawhub-autopilot/SKILL.md").read_text())
    assert "immediately give them the redemption code" not in text
    assert "hand them the redemption code" not in text
    assert "Show it once they say yes" in text

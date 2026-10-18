# Snaplii A2M Payment for Cursor

Agent-to-Merchant (A2M) payments by Snaplii Inc. A payment layer for AI agents: pay in the real world without handing the agent a credit card. The agent buys gift cards across 500+ brands with vouchers and up to 10% cashback, checks the Snaplii Cash balance, pays bills and sends P2P transfers. It spends only the prepaid Snaplii Cash the user set aside, within a per-key spending limit the user chose, and never sees the user's card or bank credentials.

## What's included

| Component | Description |
|---|---|
| MCP server `snaplii` | Tools for browsing gift cards, quotes, purchases, balance, bill pay and transfers, started with `uvx snaplii-mcp@0.20.1` |
| Skill `snaplii-cli` | Gift cards, balance, bill pay and P2P transfers |
| Skill `snaplii-autopilot` | Buy a gift card, redeem it on the merchant site and place the order, when a browser tool is available |

## What you can do

| Capability | What happens | Canada (CAD) | United States (USD) | Key scope |
|---|---|---|---|---|
| Buy gift cards | Browse 500+ brands, quote the exact price with vouchers and up to 10% cashback, buy, then read the redemption code | Yes | Yes | `PAY_WRITE` |
| Pay a merchant with the card | Redeem the code on the merchant or delivery site and place the order; needs a browser-automation tool and the `snaplii-autopilot` skill | Yes | Yes | `PAY_WRITE` |
| Check balance and cards | Spendable Snaplii Cash, owned cards, cashback estimates | Yes | Yes | `PAY_READ` |
| Pay bills | Supported utility, telecom and other billers, paid from Snaplii Cash; once sent, a bill payment cannot be undone | Yes | No | `PAY_WRITE` |
| Send money (P2P) | Send Snaplii Cash to another Snaplii user's phone number; cancellable for about 5 minutes, then it sends itself | Yes | Yes | `P2P` or `ALL` |

The account country is fixed at login, so the catalog, currency and bill pay follow it.

## Installation

1. Download the Snaplii app for [iOS](https://apps.apple.com/app/snaplii/id1596924498) or [Android](https://play.google.com/store/apps/details?id=com.snaplii.app), register an account and load your Snaplii Cash balance.
2. In the app, go to **More → Payment Methods → AI Payment Management → + New API Key**. Set a name, choose the scope (`PAY_READ`, `PAY_WRITE`, `P2P` or `ALL`) and set a hard spending limit. Copy the key: it is shown only once.
3. Install this plugin from the Cursor Marketplace. The MCP server starts with `uvx snaplii-mcp@0.20.1`, so [uv](https://docs.astral.sh/uv/getting-started/installation/) must be on your PATH.
4. Connect in one of two ways. Either set the **Snaplii API key** in the plugin's variables (the Configure Plugin Variables form after install, or **Configure** on the plugin later); the agent then connects with it directly. Or leave it empty and ask the agent to connect Snaplii: it calls `snaplii_connect`, which returns a secure card that Cursor renders inside the chat (Cursor supports MCP Apps); you enter the key in that card, never in the chat. If no card appears, follow the `next_action` that `snaplii_config_show` reports: run `snaplii init` in your own terminal ([install the CLI](https://github.com/Snaplii-Inc/agent-to-merchant-payments#quick-start)), or paste the key for `snaplii_init`, which passes it through the model once.

The MCP server uses the API key once to obtain a session token and does not store it; a key set as a plugin variable is kept by Cursor. Change the spending limit or revoke the key in the app at any time.

## Example prompts

- "Order dinner and save with Snaplii."
- "Find me a discounted gift card for my next purchase."
- "Buy my groceries and use Snaplii to save at checkout."

## Support and policies

- Publisher: Snaplii Inc. (info@snaplii.com)
- Product: https://www.snaplii.com/a2m/
- Help center: https://www.snaplii.com/help-center/ · customerservice@snaplii.com
- Privacy policy: https://www.snaplii.com/privacy-policy/
- Terms of service: https://www.snaplii.com/terms-and-conditions/
- Source: https://github.com/Snaplii-Inc/agent-to-merchant-payments

## License

Apache License 2.0, as stated in the [project README](https://github.com/Snaplii-Inc/agent-to-merchant-payments#license).

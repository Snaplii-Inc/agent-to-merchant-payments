# Snaplii A2M Payment for Claude

Agent-to-Merchant (A2M) payments by Snaplii Inc. A payment layer for AI agents: pay in the real world without handing the agent a credit card. Claude buys gift cards across 500+ brands with vouchers and up to 10% cashback, checks the Snaplii Cash balance, pays bills and sends P2P transfers. It spends only the prepaid Snaplii Cash the user set aside, within a per-key spending limit the user chose, and never sees the user's card or bank credentials.

## What's included

| Component | Description |
|---|---|
| MCP server `snaplii` | Tools for browsing gift cards, quotes, purchases, balance, bill pay and transfers, started with `uvx snaplii-mcp==0.20.2` |
| Skill `snaplii-cli` | Gift cards, balance, bill pay and P2P transfers |
| Skill `snaplii-autopilot` | Buy a gift card, redeem it on the merchant site and place the order, when a browser tool such as Claude in Chrome is available |

## What you can do

| Capability | What happens | Canada (CAD) | United States (USD) | Key scope |
|---|---|---|---|---|
| Buy gift cards | Browse 500+ brands, quote the exact price with vouchers and up to 10% cashback, buy, then read the redemption code | Yes | Yes | `PAY_WRITE` |
| Pay a merchant with the card | Redeem the code on the merchant or delivery site and place the order; needs a browser tool and the `snaplii-autopilot` skill | Yes | Yes | `PAY_WRITE` |
| Check balance and cards | Spendable Snaplii Cash, owned cards, cashback estimates | Yes | Yes | `PAY_READ` |
| Pay bills | Supported utility, telecom and other billers, paid from Snaplii Cash; once sent, a bill payment cannot be undone | Yes | No | `PAY_WRITE` |
| Send money (P2P) | Send Snaplii Cash to another Snaplii user's phone number; cancellable for about 5 minutes, then it sends itself | Yes | Yes | `P2P` or `ALL` |

The account country is fixed at login, so the catalog, currency and bill pay follow it.

## Installation

1. Download the Snaplii app for [iOS](https://apps.apple.com/app/snaplii/id1596924498) or [Android](https://play.google.com/store/apps/details?id=com.snaplii.app), register an account and load your Snaplii Cash balance.
2. In the app, go to **More → Payment Methods → AI Payment Management → + New API Key**. Set a name, choose the scope (`PAY_READ`, `PAY_WRITE`, `P2P` or `ALL`) and set a hard spending limit. Copy the key: it is shown only once.
3. Install the plugin in Claude Code. The MCP server starts with `uvx snaplii-mcp==0.20.2`, so [uv](https://docs.astral.sh/uv/getting-started/installation/) must be on your PATH.

   ```
   /plugin install snaplii-a2m-payment --marketplace Snaplii-Inc/agent-to-merchant-payments
   ```

4. Connect in one of these ways:
   - Set the plugin's **Snaplii API key** option. Claude Code asks for it when you install or enable the plugin in `/plugin`; change it later with `/plugin configure` for this plugin, then restart Claude Code. Claude then connects with it directly. The option is optional and is stored as a secret.
   - Or leave it empty and ask Claude to connect Snaplii. It calls `snaplii_connect`, and Claude Code asks you to open a secure Snaplii page where you enter the key, so the key never enters the chat.
   - If that page cannot be shown, run `snaplii init` in a terminal window of your own ([install the CLI](https://github.com/Snaplii-Inc/agent-to-merchant-payments#quick-start)) and type the key at its hidden prompt.

The MCP server uses the API key once to obtain a session token and does not store the key; it keeps the session token in the OS keychain, or in an owner-only file only if you agree. A key set as a plugin option is kept by Claude Code in its secure credential storage. Change the spending limit or revoke the key in the app at any time.

### Where it works

| Claude surface | MCP server and skills |
|---|---|
| Claude Code (terminal, IDE extensions, the Code tab of the Claude desktop app) | Supported |
| Cowork, in a session that runs on your computer | The MCP server loads; Cowork does not ask for plugin options, so connect through `snaplii_connect` |
| claude.ai and Claude Desktop chat | Not supported: chat does not run a plugin's local MCP server |

To let Claude place orders on merchant sites with the `snaplii-autopilot` skill, connect [Claude in Chrome](https://code.claude.com/docs/en/chrome) (`claude --chrome` or `/chrome`). The final order is placed only after you confirm its summary.

## What this plugin runs, sends and fetches

- **Runs** `uvx snaplii-mcp==0.20.2`, which downloads the open-source `snaplii-mcp` and `snaplii-cli` packages from PyPI and starts the MCP server on your machine.
- **Sends** your requests (catalog, balance, quotes, purchases, bill payments, transfers) and the API key you enter only to the Snaplii API at `aipayment.snaplii.com` over HTTPS.
- **Fetches** the latest release version from PyPI to tell you when an update is available; this request carries no account data.
- **Stores** only the session token on your device, never the API key. A key you set as a plugin option stays in Claude Code's credential storage.
- If the MCP server is not available, the `snaplii-cli` skill can install the `snaplii` CLI by cloning this repository at the matching release tag and running its installer, and only when you ask for that path.

## Example prompts

- "Order dinner and save with Snaplii."
- "Find me a discounted gift card for my next purchase."
- "What's my Snaplii Cash balance?"

## Support and policies

- Publisher: Snaplii Inc. (info@snaplii.com)
- Product: https://www.snaplii.com/a2m/
- Help center: https://www.snaplii.com/help-center/ · customerservice@snaplii.com
- Privacy policy: https://www.snaplii.com/privacy-policy/
- Terms of service: https://www.snaplii.com/terms-and-conditions/
- Source: https://github.com/Snaplii-Inc/agent-to-merchant-payments

## License

Apache License 2.0; see [LICENSE](https://github.com/Snaplii-Inc/agent-to-merchant-payments/blob/main/LICENSE).

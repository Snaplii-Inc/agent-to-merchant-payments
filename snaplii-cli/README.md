# snaplii-cli

Command-line client for [Snaplii Agent-to-Merchant (A2M) payments](https://github.com/Snaplii-Inc/agent-to-merchant-payments).

Snaplii is a prepaid account that isolates funds for AI spending, making it safer and easier to authorize an AI agent to pay on your behalf. You set aside money as **Snaplii Cash** and control the agent's access through scoped, revocable API keys and spending limits set in the Snaplii app. Agent payments draw only from that prepaid balance; the agent does not get direct access to your bank accounts or credit cards.

This is the asset-isolation model: separate the funds available to the agent from access to your other payment sources, then grant only the permissions and spending allowance needed for the task.

## Availability by country

| Account country | Save on spending with gift cards | Bill payments | P2P transfers |
|---|---|---|---|
| Canada (CA / CAD) | Available | Available for supported billers | Available to other Snaplii users |
| United States (US / USD) | Available | Not available | Available to other Snaplii users |

Gift-card brands, denominations, redemption terms, and savings depend on the account's country and the current catalog/quote. P2P transfers require the appropriate API-key scope and available transfer allowance. **Bill pay is available in Canada only.**

## How Snaplii and agent tools work together

Snaplii provides the gift card and redemption information needed for payment. Shopping, redeeming the card, and placing an order on a merchant website are carried out by agent tools with those capabilities.

When the agent has **browser-control capability, the necessary merchant-account access, and user authorization**, it can connect Snaplii payment to a complete shopping flow: select items → obtain the appropriate gift card → redeem it with the merchant → place the order using the applicable confirmation steps. Check the merchant's acceptance and redemption terms before purchasing a card for that order.

When those conditions are missing or the merchant flow is blocked, provide the user with the redemption information and clear next steps to finish in the merchant app or website. Describe this as the fallback for the current session, rather than the limit of all Snaplii-enabled workflows. Distinguish a successful gift-card purchase from a completed merchant order.

Every command prints JSON, so any agent that can run a shell command can use it.

## Requirements

- Python 3.9+
- A Snaplii account and API key. In the Snaplii app ([iOS](https://apps.apple.com/app/snaplii/id1596924498) / [Android](https://play.google.com/store/apps/details?id=com.snaplii.app)) go to **More → Payment Methods → AI Payment Management → + New API Key**, choose a scope, and set a hard spending limit. The key is shown once.

## Install

From PyPI, isolated with pipx (recommended):

```bash
pipx install snaplii-cli
```

From a checkout of the repository:

```bash
pipx install -e ./snaplii-cli
```

Plain `pip install snaplii-cli` also works. OS-specific pipx setup and troubleshooting are in the [repository README](https://github.com/Snaplii-Inc/agent-to-merchant-payments#readme).

## Authenticate

```bash
snaplii init
```

Prompts for your API key with hidden input. The key is exchanged for a session token and never stored; the token is kept in your OS keychain when one is available.

## Usage

```bash
# Gift cards
snaplii browse tags                                  # categories and brands for your account's country
snaplii browse brand --id CB...                      # denominations and cashback
snaplii balance --country CA                         # spendable Snaplii Cash (CA=CAD, US=USD)
snaplii quote --item-id CB...-CT... --price 50       # price after voucher/cashback
snaplii purchase --item-id CB...-CT... --price 50    # buy; pays from Snaplii Cash
snaplii giftcard list                                # owned cards

# Bill pay — Canada only; not available for US accounts
snaplii billpay payees
snaplii billpay save --payee-code PE... --first-name Alex --last-name Chen --amount 75.25 --account 1234567890
snaplii billpay quote --pay-code PC... --price 75.25
snaplii billpay pay --pay-code PC... --price 75.25

# P2P transfer (API key scope P2P or ALL)
snaplii transfer create --to-phone 4165550006 --amount 12.50
snaplii transfer status --order-no ZZ... --wait --timeout 330
snaplii transfer list
```

- `--item-id` is `{cardBrandId}-{cardTemplateId}`; both come from `snaplii browse brand`.
- For Canadian accounts only, bill pay flow: `payees → detail → save (returns payCode) → quote → pay → result`.
- A new transfer stays cancellable (`transfer cancel`) for about 5 minutes, then sends automatically; `transfer finish` sends it immediately. `transfer status --wait` polls for the outcome, but its `--timeout` defaults to 120s — pass a larger value (e.g. `--timeout 330`) to poll through the whole cancellable window.
- `snaplii help` and `snaplii <command> --help` list every flag.

## Commands

| Group | Commands |
|---|---|
| Auth & config | `init`, `config show`, `config set --base-url URL`, `config clear` |
| Catalog | `browse tags`, `browse brand --id ID` |
| Balance & quotes | `balance [--country CA\|US]`, `quote --item-id ID --price P` |
| Purchases | `purchase --item-id ID --price P`, `giftcard list`, `giftcard detail --card-no NO` |
| Smart | `smart cashback --brand-id ID --amount A`, `smart dashboard` |
| Bill pay (Canada only) | `billpay payees`, `billpay detail`, `billpay save`, `billpay vouchers`, `billpay quote`, `billpay pay`, `billpay result`, `billpay history` |
| Transfers | `transfer create`, `transfer cancel`, `transfer finish`, `transfer status [--wait] [--timeout S]`, `transfer list` |
| Maintenance | `update`, `help` |

## Safety model

Spending draws only from the prepaid Snaplii Cash balance and is capped by the per-key limit set in the app. Keys are scoped and can be revoked at any time from the app.

## More

- Full documentation, MCP server, and agent skills: <https://github.com/Snaplii-Inc/agent-to-merchant-payments>
- Changelog: <https://github.com/Snaplii-Inc/agent-to-merchant-payments/blob/main/CHANGELOG.md>
- Issues: <https://github.com/Snaplii-Inc/agent-to-merchant-payments/issues>

## License

Apache License 2.0

# snaplii-cli

Command-line client for the [Snaplii wallet](https://github.com/Snaplii-Inc/agent-to-merchant-payments). It lets AI agents and scripts spend a prepaid Snaplii Cash balance: buy gift cards with cashback, cover bills (Canada), and send Snaplii Cash to another user — with no checkout and no card sharing.

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

Outside a recognized Muse runtime, a CLI without a working keychain stops with `no_persistent_storage` rather than keeping a session that the next command could not reuse; explicit `SNAPLII_ALLOW_INSECURE=1` opts into a private (mode 0600) plaintext token file. Only a long-lived MCP server may hold a memory-only session. `snaplii config show` reports the actual storage and `has_valid_token`, without showing the token or API key. Protected requests require a usable session and are not automatically replayed after authentication errors.

### Meta Muse secure credential store

To authenticate with an API key already saved in Muse's secure credential store:

```bash
snaplii init --vault-auth
snaplii config show
```

`--agent-id` is optional: Snaplii reuses a saved ID or generates one on successful login. Before using Snaplii, check that `has_valid_token` is `true`; the status output does not display credentials.

Recognized Muse runtimes select secure authentication by default for `snaplii init` and automatically keep the session token in a private file for later CLI processes. The API key remains in Muse's secure credential store. The accompanying skill directs Muse to use its native secure input when needed, and to stop on cancellation.

Run `snaplii config doctor` to check runtime detection and storage without logging in. If the secure path is unavailable, explicitly choose `snaplii init --legacy-auth` for the original hidden-input flow. `--vault-auth` and `--legacy-auth` are mutually exclusive.

For a separate test configuration, set `SNAPLII_CONFIG_PATH` to a new file path and use that same value for each command. This isolates Snaplii's session, not Muse's stored API key. Prerelease candidate installations keep their CLI and skill versions together; `snaplii update` will not replace a candidate with a PyPI release.

## Usage

```bash
# Gift cards
snaplii browse tags                                  # categories and brands for your account's country
snaplii browse brand --id CB...                      # denominations and cashback
snaplii balance --country CA                         # spendable Snaplii Cash (CA=CAD, US=USD)
snaplii quote --item-id CB...-CT... --price 50       # price after voucher/cashback
snaplii purchase --item-id CB...-CT... --price 50    # buy; pays from Snaplii Cash
snaplii giftcard list                                # owned cards

# Bill pay
snaplii billpay payees
snaplii billpay save --payee-code PE... --first-name Alex --last-name Chen --amount 75.25 --account 1234567890
snaplii billpay quote --pay-code PC... --price 75.25
snaplii billpay pay --pay-code PC... --price 75.25

# P2P transfer (API key scope P2P or ALL)
snaplii transfer create --to-phone 4165550006 --amount 12.50
snaplii transfer status --order-no ZZ... --wait --timeout 330
snaplii transfer list
```

- **`--item-id` must be exactly `{cardBrandId}-{cardTemplateId}`**, copied verbatim from the `item_id` in the `denominations` of `snaplii browse brand`; never either ID alone or one built by hand. Use the same value for `quote` and `purchase`.
- Bill pay flow: `payees → detail → save (returns payCode) → quote → pay → result`.
- A new transfer stays cancellable (`transfer cancel`) for about 5 minutes, then sends automatically; `transfer finish` sends it immediately. `transfer status --wait` polls for the outcome, but its `--timeout` defaults to 120s — pass a larger value (e.g. `--timeout 330`) to poll through the whole cancellable window.
- `snaplii help` and `snaplii <command> --help` list every flag.

## Commands

| Group | Commands |
|---|---|
| Auth & config | `init [--agent-id ID] [--vault-auth \| --legacy-auth]`, `config show`, `config doctor`, `config set --base-url URL`, `config clear` |
| Catalog | `browse tags`, `browse brand --id ID` |
| Balance & quotes | `balance [--country CA\|US]`, `quote --item-id ID --price P` |
| Purchases | `purchase --item-id ID --price P`, `giftcard list`, `giftcard detail --card-no NO` |
| Smart | `smart cashback --brand-id ID --amount A`, `smart dashboard` |
| Bill pay | `billpay payees`, `billpay detail`, `billpay save`, `billpay vouchers`, `billpay quote`, `billpay pay`, `billpay result`, `billpay history` |
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

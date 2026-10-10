# Snaplii Wallet for AI Agents

> A prepaid wallet your AI agent can spend from, without your credit card.

Snaplii is a prepaid wallet. The user tops up **Snaplii Cash** in the app and gives the agent a scoped, revocable key with a daily limit. Within that limit the agent can check the balance, spend it at a merchant through a gift card, cover Canadian utility and telecom bills, and send Snaplii Cash to another user; it never sees the user's card or bank credentials. It ships as an **Agent Skill**, an **MCP server**, and a **Python CLI**, so it works with any agent that can read a `SKILL.md`, call MCP tools, or run a command.

---

## For AI agents: start here

### Choose how to connect

| You are | Install |
|---|---|
| An agent that reads `SKILL.md` | The skills plus the CLI or MCP server: [Install from a release](#install-from-a-release) |
| An MCP client that does not load skill folders | The MCP server: [MCP Server](#mcp-server-claude-openclaw-cursor-instinct) |
| A terminal or a script, without an agent | The CLI: [Quick Start](#quick-start) |

### Install from a release

Install the skills, the CLI and the MCP server from one release tag, so all three come from the same commit. Find your agent in this table, then run the commands below with its values; if your agent is not in the table or Node.js is missing, replace the second command with **Manual install** below.

| Agent | `-a` | `--host` |
|---|---|---|
| Claude Code | `claude-code` | `claude-code` |
| Codex | `codex` | `codex` |
| Cursor | `cursor` | `cursor` |
| OpenClaw | `openclaw` | `openclaw` |
| Gemini CLI | `gemini-cli` | leave it out |
| GitHub Copilot | `github-copilot` | leave it out |
| Muse | skip this command, see **Muse** below | `muse` |
| Instinct | skip both this command and **Manual install**; Instinct runs Snaplii through the MCP server, as the **Instinct** block under [MCP Server](#mcp-server-claude-openclaw-cursor-instinct) describes | `instinct` |
| Any other agent | skip this command, use **Manual install** | leave it out; add `--cli-only` unless you know how your agent registers an MCP server |

- `--yes` and `-y` skip prompts a shell tool cannot answer interactively. Always pair `-y` with `-a`, or the skills go to every agent the installer finds.
- Where the table says leave it out, drop both `--host` and its value. Add `--cli-only` to the third command if your agent will not use MCP. Muse gets the CLI only by itself; Instinct needs MCP and refuses `--cli-only`.

```bash
git clone --depth 1 --branch v0.19.0 https://github.com/Snaplii-Inc/agent-to-merchant-payments.git snaplii-src
npx --yes skills add ./snaplii-src -g -a claude-code -y
python3 snaplii-src/scripts/install.py --host claude-code --source ./snaplii-src
```

- On Windows, use `py -3` in place of `python3`, and run **Manual install** in Git Bash, which comes with Git for Windows. The skills are copied and the packages are built into `~/.snaplii-env`, so you can delete `snaplii-src` afterwards.
- To install again or update, run the three commands from a directory with no `snaplii-src` folder.

**Manual install.** Use it only when the second command cannot run. Set `SKILLS_DIR` to your agent's user-wide skills directory, or its project skills directory if it has none. The commands copy both skills, each with `SKILL.md` at its top level, and update the files in place when repeated.

```bash
: "${SKILLS_DIR:?set SKILLS_DIR to your skills directory}"
mkdir -p "$SKILLS_DIR/snaplii-cli" "$SKILLS_DIR/snaplii-autopilot"
cp -R snaplii-src/clawhub-publish/.   "$SKILLS_DIR/snaplii-cli/"
cp -R snaplii-src/clawhub-autopilot/. "$SKILLS_DIR/snaplii-autopilot/"
```

**Muse** runs the skill with the CLI, not MCP. Install the `snaplii-cli` skill from `snaplii-src/clawhub-publish/` with Muse's own skill installation; Muse names its folder under `~/workspace/skills/`. Then run `python3 snaplii-src/scripts/install.py --host muse --source ./snaplii-src`.

### Install the execution layer

The third command builds the CLI and the MCP server into `~/.snaplii-env` and prints a JSON report with the next steps; it never asks for an API key or edits host configuration. `--host` also takes `claude-desktop`; see `--help` for other flags and [No Python on the machine](#no-python-on-the-machine) if Python is missing.

**Reading the report.** `status: installed` (exit 0) means every component you asked for works; `--check` reports `installed` (exit 0) or `not_installed` (exit 1). Work through `next_steps` in order:

- `required`: blocking. Do what `why` says, then run `command`, which re-runs the installer, **once**; if the same `failure.code` returns, or `failure.retryable` is false, stop and report it. When `command` is null, report `why` to the user.
- `pending`: do the ones that apply: skip `install_skill` if this clone's skills are installed already, and `register_mcp` if your agent uses the CLI only. `register_mcp` gives a command to run, a `file` to merge its `json` into without removing other entries, or only a path to register as a stdio server; never run that path.

**Verify.** `npx skills list -g` shows `snaplii-cli` and `snaplii-autopilot` after the second command, where `Agents: not linked` is normal for agents that read `~/.agents/skills`, and `ls "$SKILLS_DIR"` does after **Manual install**; Muse installs `snaplii-cli` only. Your agent loads them after the new session the report's `reload_host` step may need. Then check the connection state: in this session, run the report's CLI path with `config show`, and use that absolute path for every CLI command; if your agent uses MCP, also call the `snaplii_config_show` tool once it loads in the new session. Never buy anything to test the install.

---

## Table of Contents

- [For AI agents: start here](#for-ai-agents-start-here)
  - [Choose how to connect](#choose-how-to-connect)
  - [Install from a release](#install-from-a-release)
  - [Install the execution layer](#install-the-execution-layer)
- [What you can do with Snaplii](#what-you-can-do-with-snaplii)
- [How authorization works](#how-authorization-works)
  - [Sessions and reconnecting](#sessions-and-reconnecting)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [CLI Commands](#cli-commands)
- [Integration Guides](#integration-guides)
  - [MCP Server (Claude, OpenClaw, Cursor, Instinct)](#mcp-server-claude-openclaw-cursor-instinct)
- [Components](#components)
- [Updating](#updating)
- [Uninstall](#uninstall)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [Why Snaplii](#why-snaplii)
- [License](#license)

---

## What you can do with Snaplii

| Capability | What happens | Canada (CAD) | United States (USD) | Key scope |
|---|---|---|---|---|
| Spend at a merchant | Buy a gift card from the balance (500+ brands, vouchers and up to 10% cashback) and read its redemption code; with a browser-automation tool and the `snaplii-autopilot` skill or MCP prompt, the agent also redeems it at checkout and places the order | Yes | Yes | `PAY_WRITE` |
| Check balance and cards | Spendable Snaplii Cash, owned cards, cashback estimates | Yes | Yes | `PAY_READ` |
| Cover a bill | Supported utility, telecom and other billers, from Snaplii Cash; once sent, a bill cannot be undone | Yes | No | `PAY_WRITE` |
| Send Snaplii Cash | To another Snaplii user's phone number; cancellable for about 5 minutes, then it sends itself | Yes | Yes | `P2P` or `ALL` |

The account country is fixed at login, so the catalog, currency and billers follow it; do not ask the user for a region.

---

## How authorization works

1. **Set aside funds.** Add the amount you want to make available as Snaplii Cash in the app.
2. **Define access.** Create an API key with the scope and spending limit the agent's task needs. Scopes: `PAY_READ` (read-only), `PAY_WRITE` (read, buy, bills), `P2P` (transfers), `ALL`.
3. **Let the agent execute within that boundary.** The agent spends from Snaplii Cash, without exposing your bank or card credentials. You can change the limit or revoke the key in the app at any time.

Gift-card purchases can help users save through eligible offers and cashback. Available brands and savings vary by country, brand, and current quote; merchant offers can be combined only where their terms allow.

### Sessions and reconnecting

Check the session in the runtime that runs the task: a session in `~/.snaplii/config.json` or the OS keychain serves both the CLI and the MCP server; one the MCP server keeps in memory serves only that server. A connection exchanges the API key once for a session token. The key is not kept, so connecting again needs it again unless the host's vault holds it (Muse, Instinct). The gateway sets when a session expires, so rely on `has_valid_token` rather than a fixed lifetime. The app shows a new key only once: the user should keep it in a password manager.

The API key stays out of the chat where the host allows it: a secure card, the hosted connect page, or the host's vault (Muse, Instinct). Otherwise the user runs `snaplii init` in their own terminal or, if the Snaplii MCP tools are available, pastes the key for `snaplii_init`, which passes it through the model once. Only the Snaplii production and staging gateways accept a sign-in.

`snaplii config show` and `snaplii_config_show` report `has_valid_token`, `auth_state`, `host`, `credential_storage` and `next_action`. `auth_state` is `ready`, `auth_required` (never connected), `reauth_required` (expired, rejected, or a memory-only MCP session lost in a restart) or `mcp_required` (the CLI was called in Instinct). `host` is `unknown` everywhere except Muse and Instinct, which is normal. Follow `next_action`:

| `next_action` | What to do |
|---|---|
| `run_cli` | The user runs its `argv` in their own terminal: from a shell tool `init` reads nothing and answers `api_key_missing`; in Muse the agent runs `init --vault-auth` itself. `argv[0]` is `snaplii`, or the CLI's absolute path when the `snaplii` on PATH is a different CLI; relay `argv` unchanged |
| `call_mcp_tool` | The agent calls `snaplii_connect`, only while `has_valid_token` is false. Only `authenticated` or `already_connected` means connected; after `card_requested`, `pending` or `use_terminal_or_chat_key`, check the status again once the user has acted |
| `muse_secure_entry` | The agent opens Muse's secure input; a stored key is reused without asking |
| `offer_legacy` | The key was rejected (`invalid_key`); the user enters a key again |
| `retry_auth_later` | Snaplii was unreachable; retry later |
| `stop` | Cancelled, or no session could be stored; report it and do not retry or switch methods |

- **Shell-only agent.** On a machine without an OS keychain, `init` answers `session_cache_failed` with reason `no_persistent_storage`. The user then sets `allow_insecure_mode: true` in the config file, or `SNAPLII_ALLOW_INSECURE=1`, and runs `init` again. The config-file setting applies to every Snaplii process, including an MCP server the host starts; the environment variable reaches that server only if the host passes it on.
- **MCP host.** A session the server keeps only in memory ends with the server; connect again after a restart.
- **Instinct.** Repeat the two `snaplii_connect` calls with the vault fill; the vault keeps the key.

---

## Requirements

- Any Python 3.8+ to start the installer, which fetches CPython 3.12 with uv when no 3.10+ is available  
  _CLI needs 3.9+, the MCP server 3.10+. With no Python at all, see [No Python on the machine](#no-python-on-the-machine)._
- Git
- Node.js with `npx`, only for the one-line `npx skills add` install; the manual copy needs neither
- Snaplii Mobile App  
  _Required to generate your API key._

---

## Quick Start

### 1. Get Your API Key via Snaplii App

Installing needs no key. To connect the CLI or your AI agent, generate a secure API key in the Snaplii mobile app:

1. Download the Snaplii app for [iOS](https://apps.apple.com/app/snaplii/id1596924498) or [Android](https://play.google.com/store/apps/details?id=com.snaplii.app).
2. Register an account and top up your Snaplii Cash balance in the app.
3. In the app, go to **More → Payment Methods → AI Payment Management**.
4. Tap **+ New API Key**.
5. Set a name, choose the scope (`PAY_READ`, `PAY_WRITE`, `P2P`, or `ALL`), and set a hard spending limit.
6. Copy the API key.
   - Format: `snp_sk_live_...`
   - Keep it safe. It is shown only once.

### 2. Install the CLI and MCP server

Clone a release and run its installer (see [Install the execution layer](#install-the-execution-layer) for the Windows and no-Python variants):

```bash
git clone --depth 1 --branch v0.19.0 https://github.com/Snaplii-Inc/agent-to-merchant-payments.git snaplii-src
python3 snaplii-src/scripts/install.py --source ./snaplii-src
```

It creates `~/.snaplii-env`, builds `snaplii-cli` and `snaplii-mcp` from the clone, verifies both, and prints the executables' absolute paths. Add `--cli-only` if you do not need the MCP server.

The steps below call `snaplii` by name. Use the absolute path from the report (`~/.snaplii-env/bin/snaplii`, or `%USERPROFILE%\.snaplii-env\Scripts\snaplii.exe` on Windows), or run the report's `cli_on_path` command first.

### 3. Authenticate

Only when connecting, and only in the user's own interactive terminal; an agent's shell tool cannot answer the prompt.

```bash
snaplii init
```

The CLI will prompt for your API key via hidden input (like a password prompt). The key is used only to obtain a session token and is **never stored on disk**. Agent ID is auto-derived from the key.

#### Meta Muse secure credential store

To authenticate with an API key already saved in Muse's secure credential store:

```bash
snaplii init --vault-auth
snaplii config show
```

`--agent-id` is optional: Snaplii reuses a saved ID or generates one on successful login. Before using Snaplii, check that `has_valid_token` is `true`; the status output does not display credentials.

When Muse is recognized, `snaplii init` selects secure credential authentication by default and caches the session token in an owner-only file so later CLI commands can reuse it. The API key stays in Muse's secure credential store. The accompanying skill directs Muse to open its native secure input when a key is needed; cancellation stops the connection attempt. The skill describes when a first install in Muse connects on its own.

Use `snaplii config doctor` to check runtime detection and storage without logging in. If secure credential authentication is unavailable, you can explicitly choose `snaplii init --legacy-auth` and enter your API key at the terminal's hidden prompt.

#### Instinct

In Instinct the CLI does not authenticate at all. Connect through the MCP server and the Instinct vault, as described under [MCP Server](#mcp-server-claude-openclaw-cursor-instinct).

### 4. Use the CLI

```bash
snaplii browse tags                                  # Browse gift card categories
snaplii browse brand --id CB...                      # See denominations and cashback
snaplii balance                                      # Check spendable Snaplii Cash balance
snaplii quote --item-id CB...-CT... --price 50       # Preview price with voucher/cashback
snaplii giftcard list                                # View owned cards
snaplii purchase --item-id CB...-CT... --price 50    # Buy a card
snaplii giftcard detail --card-no ...                # Read the redemption code
```

> **`--item-id` must be exactly `{cardBrandId}-{cardTemplateId}`** (e.g. `CB00000000000086-CT000000003618`). Copy it verbatim from the `item_id` in the `denominations` that `snaplii browse brand` returns, and use the same value for `quote` and `purchase`. Never pass either ID alone or build one by hand: a different well-formed ID buys a different card.
>
> The catalog is scoped to your account's country (fixed at login, enforced server-side), so there's no region/province flag to pass. `balance` labels the currency from the stored country; `--country CA|US` is only a fallback for older sessions.
>
> `--price` must be within the brand's denomination range — `browse brand` shows each card's min/max (variable) or fixed amount. When the brand's rules are available, `quote` and `purchase` reject an out-of-range price up front (e.g. \$10 on a \$20-minimum card); if the catalog lookup fails, the check is skipped and the gateway decides.
>
> Always `quote` before `purchase`. The quote's `you_pay` is what Snaplii Cash does not cover; if it is above zero, the user needs to top up in the app first.

### 5. Cover a Bill (Canada only)

Canadian accounts can cover supported utility, telecom, and other bills from Snaplii Cash; US accounts cannot. Check the account country before starting; use the live biller list and quote for availability and any applicable savings.

```bash
snaplii billpay payees                                                       # Find your biller
snaplii billpay detail --payee-code PE01015                                  # Check account rules
snaplii billpay save --payee-code PE01015 --first-name Alex --last-name Chen --amount 75.25 --account 1234567890
snaplii billpay quote --pay-code PC... --price 75.25                         # Preview savings
snaplii billpay pay --pay-code PC... --price 75.25                          # Settle from Snaplii Cash
snaplii billpay result --payment-no PSP...                                   # Check status
```

> Bill pay flow: **payees → detail → save (returns payCode) → quote → pay → result**. The money comes from your prepaid Snaplii Cash balance; the agent never touches your bank accounts or credit cards.

### 6. Send Money (P2P Transfer)

Available in Canada and the United States: send Snaplii Cash to another Snaplii user's phone number. Requires an API key whose scope is `P2P` or `ALL`.

```bash
snaplii transfer create --to-phone 4165550006 --amount 12.50   # Cancellable ~5 min, then auto-sends
snaplii transfer cancel --order-no ZZ...                       # Undo within the window
snaplii transfer finish --order-no ZZ...                       # Send NOW; only when the user explicitly asks
snaplii transfer status --order-no ZZ... --wait --timeout 330  # Poll until FINISHED / CANCELLED / FAILED
snaplii transfer list                                          # List transfers, newest first
```

> A new transfer stays **cancellable until `auto_finish_at`** (~5 minutes), then the gateway sends it automatically. After `create`, tell the user the amount, the masked recipient, and that deadline. Cross-currency transfers (recipient in another country) return the exact `received_amount` / `received_currency` / `conversion_rate` and a `cross_currency_notice` up front; show it and let the user keep or cancel. `--wait` polls every 3 seconds and its `--timeout` defaults to 120 seconds, shorter than the window, so size it to the time left plus settlement (about 330 right after `create`) or re-run on `wait_timed_out`. Transfers are capped by a rolling 24-hour per-key limit set in the app.

---

## CLI Commands

Every operation prints one JSON document on stdout, or one JSON error on stderr with exit code 1; `help`, `--help`, and `--version` print plain text, and `init` writes its hidden prompt to stderr. A refused connection is reported as JSON too, but another transport failure during a read, such as a timeout, can still surface as a Python traceback. A few lookups report a not-found condition as an `error` field inside the stdout JSON with exit code 0, for example `smart cashback` when no denomination matches, so inspect the body as well as the exit code. Authentication errors carry `auth_state` and a `next_action` the agent can follow.

| Command | Purpose |
|---|---|
| `snaplii init [--agent-id ID] [--vault-auth \| --legacy-auth]` | Authenticate. Interactive: the user runs it in a terminal; needs an OS keychain or `SNAPLII_ALLOW_INSECURE=1`. Muse defaults to secure credentials, with an explicit original-input fallback. Refused in Instinct |
| `snaplii config show` | Show current config and auth status, including `has_valid_token`, `host`, and `next_action` |
| `snaplii config doctor` | Diagnose runtime detection (Muse, Instinct) and storage without logging in |
| `snaplii config set --base-url URL` | Set the gateway URL. Sign-in works only with production `https://aipayment.snaplii.com` and staging `https://aipay.stage.snaplii.com` |
| `snaplii config clear` | Clear local configuration and session; does not delete the host-stored API key |
| `snaplii browse tags` | Browse card categories and brands |
| `snaplii browse brand --id ID` | View brand details, denominations, and cashback |
| `snaplii giftcard list` | List owned gift cards |
| `snaplii giftcard detail --card-no NO` | View card redemption code and PIN |
| `snaplii balance [--country CA\|US]` | Show spendable Snaplii Cash balance; currency follows the stored account country |
| `snaplii quote --item-id ID --price P` | Preview price with voucher/cashback before buying |
| `snaplii purchase --item-id ID --price P` | Purchase a gift card |
| `snaplii smart cashback --brand-id ID --amount A` | Calculate cashback savings |
| `snaplii smart dashboard` | View card inventory summary |
| `snaplii billpay payees` | Canada only: list available billers (electricity, gas, telecom) |
| `snaplii billpay detail --payee-code CODE` | View biller account validation rules |
| `snaplii billpay save --payee-code CODE --first-name F --last-name L --amount A --account NO` | Save a bill pay instruction |
| `snaplii billpay vouchers --pay-code PC --price P` | List eligible bill-payment vouchers |
| `snaplii billpay history --payee-code CODE` | Get the previous bill instruction for a biller, for autofill; not a ledger of settled bills |
| `snaplii billpay quote --pay-code PC --price P` | Preview bill price with voucher/cashback |
| `snaplii billpay pay --pay-code PC --price P` | Canada only: settle the bill from Snaplii Cash |
| `snaplii billpay result --payment-no NO` | Check a bill's status |
| `snaplii transfer create --to-phone P --amount A` | Send Snaplii Cash to a phone number (cancellable ~5 min, then auto-sends) |
| `snaplii transfer cancel --order-no NO` | Cancel a PENDING transfer within the undo window |
| `snaplii transfer finish --order-no NO` | Send a PENDING transfer immediately |
| `snaplii transfer status --order-no NO [--wait] [--timeout S]` | Get a transfer's state; polling defaults to a 120-second timeout |
| `snaplii transfer list [--status S]` | List transfers, newest first |
| `snaplii update` | Check for and install a CLI update |
| `snaplii help` | Show top-level help; use `snaplii <command> --help` for command flags |

In Instinct, only `help`, `update`, `--version`, and `config` run; every other command answers `auth_state=mcp_required` and points to the `snaplii_connect` MCP tool.

---

## Integration Guides

### MCP Server (Claude, OpenClaw, Cursor, Instinct)

The MCP server exposes 26 tools via the [Model Context Protocol](https://modelcontextprotocol.io/). One of them, `snaplii_submit_api_key`, is callable only by the host's secure card, and Instinct hides it together with `snaplii_init`. Works with any MCP-compatible client.

#### Step 1: Install dependencies

Run the installer from the release clone (see [Install from a release](#install-from-a-release)) and keep the `register_mcp` step from its report; it contains the absolute path of `snaplii-mcp` and the exact command or config snippet for your host:

```bash
python3 snaplii-src/scripts/install.py --host claude-desktop --source ./snaplii-src   # or claude-code, codex, cursor, openclaw, instinct
```

#### Step 2: Configure your MCP client

Use the `snaplii-mcp` path from the installer's `register_mcp` step; the report already contains the exact command or snippet for your host.

<details>
<summary><strong>Claude Desktop</strong></summary>

Edit your config file:

| OS | Config file location |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

```json
{
  "mcpServers": {
    "snaplii": {
      "command": "/Users/you/.snaplii-env/bin/snaplii-mcp"
    }
  }
}
```

Use the absolute path from the report's `register_mcp` step; the file does not expand `~`. Restart Claude Desktop after saving.

</details>

<details>
<summary><strong>Claude Code</strong></summary>

Register the installer's server for your user, so it works in every project, then check it:

```bash
claude mcp add --scope user snaplii -- ~/.snaplii-env/bin/snaplii-mcp
claude mcp get snaplii   # expect "User config" and "Connected"
```

Without `--scope user`, Claude Code registers the server only for the directory you ran the command in. If it says the server already exists, it is registered; check it with `claude mcp get snaplii`.

</details>

<details>
<summary><strong>Codex</strong></summary>

Register the installer's server for your user, then check it:

```bash
codex mcp add snaplii -- ~/.snaplii-env/bin/snaplii-mcp
codex mcp list
```

</details>

<details>
<summary><strong>OpenClaw</strong></summary>

Register the server with the OpenClaw CLI ([reference](https://docs.openclaw.ai/cli/mcp/registry)):

```bash
openclaw mcp add snaplii --command ~/.snaplii-env/bin/snaplii-mcp
```

Then install the skills from the same release clone, as [Install from a release](#install-from-a-release) shows, if you have not already.

</details>

<details>
<summary><strong>Instinct</strong></summary>

Instinct installs the MCP server with the installer and connects through the Instinct vault, so the API key never enters the chat.

1. Run the installer from the release clone: `python3 snaplii-src/scripts/install.py --host instinct --source ./snaplii-src`. It refuses `--cli-only` because Instinct executes only through MCP.
2. Register the `snaplii-mcp` executable from the report's `register_mcp` step (`~/.snaplii-env/bin/snaplii-mcp`) as a stdio MCP server in Instinct.
3. Skip `snaplii init`. In Instinct the CLI only serves `help`, `update`, `--version` and `config`; everything else runs through the MCP tools.
4. Connect right after the first install, without waiting for a request. Call `snaplii_connect` and open the returned `connect_url` in the cloud browser. Use the Instinct vault fill action on the API key field with the returned `vault_entry`, click **Connect**, then call `snaplii_connect` again with the returned `eid` within 2 minutes. If the MCP tools only load in a new session, connect at the start of that session.
5. If the vault has no entry yet, the agent explains how to create a key in the Snaplii App and sends the vault's encrypted submission link so you can save it there.

The vault entry is `Snaplii API Key` for the production gateway. Other gateways append their host, for example `Snaplii API Key aipay.stage.snaplii.com`.

Instinct is detected from any environment variable whose name starts with `INSTINCT_`; Muse takes precedence. `snaplii_config_show` and `snaplii config doctor` list the matching variable names, never their values.

The one-time `eid` in the connect link is visible to the agent. Whoever holds it can take the session token once, within 2 minutes after **Connect** is pressed. If someone else takes it first, `snaplii_connect` reports `pending` instead of connecting.

</details>

<details>
<summary><strong>Cursor / VS Code / Other MCP clients</strong></summary>

Any MCP-compatible client can start the Snaplii MCP server over stdio. Register the absolute `snaplii-mcp` path from the report's `register_mcp` step as a stdio server; for Cursor, that step names `~/.cursor/mcp.json`. Most clients take a JSON entry like this:

```json
{
  "mcpServers": {
    "snaplii": {
      "command": "/Users/you/.snaplii-env/bin/snaplii-mcp"
    }
  }
}
```

</details>

#### Step 3: Connect

Connect when the user asks to connect or gives a Snaplii task; installing alone does not connect. Connecting from inside the client is preferred: call `snaplii_connect`, and the host renders a secure card or opens a hosted page where the user enters the key off-model. If the client can do neither, the user authenticates in their own terminal first; an agent cannot answer the hidden prompt:

```bash
~/.snaplii-env/bin/snaplii init
```

Enter your API key when prompted.

In Instinct, skip this step and follow the **Instinct** instructions under Step 2.

#### Available MCP Tools

| Tool | Description |
|---|---|
| `snaplii_connect` | Connect the account off-model: a secure card on hosts that render MCP Apps, a hosted page on hosts with URL elicitation, the vault-filled page in Instinct. Call only when `has_valid_token` is false |
| `snaplii_init` | Authenticate with an API key passed as an argument. Fallback for clients with neither card nor page; hidden in Instinct |
| `snaplii_config_show` | Auth status: `has_valid_token`, `host`, `next_action` |
| `snaplii_balance` | Real spendable Snaplii Cash balance, labelled in the account's currency |
| `snaplii_browse_tags` | Browse gift card categories; returns `account_country` |
| `snaplii_browse_brand` | Brand details and denominations |
| `snaplii_giftcard_list` | List owned gift cards |
| `snaplii_giftcard_detail` | Card redemption code (sensitive) |
| `snaplii_quote` | Preview price with voucher/cashback |
| `snaplii_purchase` | Buy a gift card from Snaplii Cash; the charge happens as soon as it runs, within the daily limit |
| `snaplii_cashback_calc` | Calculate cashback savings |
| `snaplii_dashboard` | Owned card inventory summary |
| `snaplii_billpay_*` | Canada only: `payees`, `detail`, `history`, `save`, `vouchers`, `quote`, `pay`, `result` |
| `snaplii_transfer_*` | P2P transfers: `create` (cancellable ~5 min, then auto-sends), `cancel`, `finish` (send now), `status`, `list` |

The server also offers one MCP prompt, `snaplii_autopilot`, which carries the end-to-end buy, redeem, and order flow for hosts that can drive a browser.

> API keys are created and managed **only in the Snaplii app**. There are no CLI or MCP tools to list, create, or delete them.

---

## Components

```text
agent-to-merchant-payments/
├── snaplii-cli/        # Python CLI (PyPI: snaplii-cli); also the library the MCP server uses
├── mcp-server/         # MCP server (PyPI: snaplii-mcp), 26 tools + the snaplii_autopilot prompt
├── skills/             # Source text of the two skills (snaplii-cli.md, snaplii-autopilot.md)
├── clawhub-publish/    # snaplii-cli skill as a SKILL.md folder (ClawHub: snaplii-a2m-payment)
├── clawhub-autopilot/  # snaplii-autopilot skill as a SKILL.md folder (ClawHub: snaplii-autopilot)
├── clawhub-plugin/     # ClawHub MCP bundle plugin (snaplii-a2m-mcp)
├── claude-desktop/     # Older project instructions for Claude Desktop; the MCP server's own instructions take precedence
├── scripts/            # The installer (install.py), Claude Desktop setup, skill Auth-block sync, candidate bundles
└── tests/              # pytest suite for the CLI, the MCP server, and the skill documents
```

The `skills/*.md` files and the `clawhub-*/SKILL.md` folders are kept byte-identical; `scripts/sync_muse_auth_docs.py --check` verifies that their Auth sections match the code.

---

## Updating

When the user asks to update Snaplii, repeat the three commands with the new release tag, from a directory with no `snaplii-src` folder, so `--source` points at the new clone. On `files_in_use`, the running Snaplii server holds the files: the user closes the host and runs the report's retry command in a terminal; then open a new session. Do not use `snaplii update` here: it upgrades only the CLI, not the MCP server.

---

## Uninstall

Remove what the installer and the host registration added:

1. Revoke the API key in the Snaplii App: **More → Payment Methods → AI Payment Management**.
2. Sign out locally: `~/.snaplii-env/bin/snaplii config clear`. It does not delete a key the host stores (Muse, the Instinct vault).
3. Remove the MCP registration: `claude mcp remove snaplii` in Claude Code, `codex mcp remove snaplii` in Codex, or delete the `snaplii` entry from `claude_desktop_config.json` or `~/.cursor/mcp.json`.
4. Remove the skills: `npx --yes skills remove -g -y snaplii-cli snaplii-autopilot`. After **Manual install**, delete the two folders from that skills directory instead; a skill installed earlier from ClawHub is removed with ClawHub.
5. Delete the environment and the local configuration: `rm -rf ~/.snaplii-env ~/.snaplii` (PowerShell: `Remove-Item -Recurse -Force $HOME\.snaplii-env, $HOME\.snaplii`).
6. If the installer fetched CPython 3.12 with uv and nothing else uses it, remove it with `uv python uninstall 3.12`. If the installer also installed uv into `~/.local/bin`, delete `uv` and `uvx` there.

---

## Troubleshooting

### `snaplii: command not found` after install

If you used the installer, the CLI is not on `PATH` by design: call `~/.snaplii-env/bin/snaplii` (`Scripts\snaplii.exe` on Windows) or run the report's `cli_on_path` command.

### The skill is installed but the agent does not use it

Check that the folder is named after the skill (`snaplii-cli` or `snaplii-autopilot`) and contains `SKILL.md` at its top level, and that it sits in the skills directory your agent reads. Most agents load skills at session start, so open a new session after installing. Muse names the folder itself; there, find the skill with `grep -l '^name: snaplii-cli' ~/workspace/skills/*/SKILL.md`.

### Every Snaplii call answers `auth_required`, `reauth_required`, or `mcp_required`

There is no valid session in the runtime that is executing the task. `reauth_required` means there was one and it expired, was rejected, or was lost when the MCP server restarted. Run `snaplii config show` or `snaplii_config_show` and follow its `next_action`; [Sessions and reconnecting](#sessions-and-reconnecting) lists the actions by host. `mcp_required` means the host is Instinct: connect with `snaplii_connect` instead of the CLI.

### No Python on the machine

Bootstrap uv into `~/.local/bin` and let it fetch CPython 3.12, then start the installer with that Python and the same flags you chose:

```bash
export UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1
curl -LsSf https://astral.sh/uv/install.sh | sh
"$UV_INSTALL_DIR/uv" python install --no-bin --no-registry 3.12
PY312="$("$UV_INSTALL_DIR/uv" python find --no-project --managed-python 3.12)"
"$PY312" snaplii-src/scripts/install.py --host claude-code --source ./snaplii-src   # your --host or --cli-only
```

In PowerShell on Windows:

```powershell
$env:UV_INSTALL_DIR = "$HOME\.local\bin"; $env:UV_NO_MODIFY_PATH = "1"
irm https://astral.sh/uv/install.ps1 | iex
& "$env:UV_INSTALL_DIR\uv.exe" python install --no-bin --no-registry 3.12
$py312 = & "$env:UV_INSTALL_DIR\uv.exe" python find --no-project --managed-python 3.12
& $py312 snaplii-src\scripts\install.py --host claude-code --source .\snaplii-src   # your --host or --cli-only
```

The environment then depends on that Python; [Uninstall](#uninstall) removes both.

### The installer reported `failed` or `partial`

Read `failure.code`, `failure.remedy` and `failure.retryable`:

| Code | Meaning | Retryable |
|---|---|---|
| `python_too_old`, `python_download_failed`, `venv_create_failed` | No Python 3.10+ that can create an environment, and uv could not fetch one | yes, after the remedy |
| `venv_path_occupied`, `venv_locked`, `destination_unwritable`, `source_invalid` | The destination or `--source` cannot be used as given | `venv_locked` only |
| `venv_broken`, `venv_python_too_old` | The installer's own environment exists but cannot be reused, for example after the base Python was upgraded | no: delete that directory and re-run (it is recreated at the same path, so the host registration keeps working), or pass another `--venv` |
| `index_unreachable`, `disk_full`, `files_in_use` | pip could not download or write | yes |
| `index_auth_failed`, `tls_failed`, `package_unavailable`, `build_failed`, `permission_denied`, `dependency_conflict`, `pip_failed` | pip failed for a reason a re-run will not fix | no |
| `cli_missing`, `mcp_missing`, `cli_verification_failed`, `mcp_handshake_failed`, `*_timeout` | The installed component is missing or did not answer as expected | yes |
| `bad_arguments`, `mcp_required_on_instinct`, `*_spawn_failed`, `internal_error` | The command line cannot work here, or the installer hit a bug | no |
| `cleanup_incomplete` | A helper process could not be stopped; the lock file was kept on purpose | no: wait for the listed pids, delete the lock, re-run |

When `retryable` is true, apply the `required` step's `why`, then run its `command` once; if the same code returns, report it. `files_in_use` means the host's registered Snaplii server holds the files: close the host, then re-run.

### The host's Snaplii server stopped working after `~/.snaplii-env` was deleted

The registration points at `~/.snaplii-env/bin/snaplii-mcp`. Clone the release again and re-run its installer with `--source`: it recreates the environment at the same path, so the registration works again without changes.

---

## Security

- **Isolated spending access:** agents can spend only the prepaid Snaplii Cash available within their permissions and limits. They do not receive direct access to your bank accounts or credit cards.
- **Scoped API keys:** `PAY_READ` (read-only), `PAY_WRITE` (read, buy, bills), `P2P` (transfers), `ALL`.
- **Spending limits:** strict per-key consumption caps are set via the mobile app. Transfers also have a rolling 24-hour per-key limit.
- **The daily limit is the boundary.** You set a per-day cap when you create the key in the app; the agent spends only within it, from prepaid funds, and you can lower the cap or revoke the key at any time. The agent tells you this once when it connects.
- **Off-model key entry.** The API key is entered through a secure MCP Apps card rendered by the host, on the hosted connect page, in a hidden terminal prompt, or supplied by the host's credential store (Muse) or vault (Instinct). A client with none of those offers the user's own terminal prompt and, where the MCP tools exist, `snaplii_init`; with `snaplii_init` the key passes through the model once. The session token is kept in the OS keychain, or in process memory for a long-lived MCP server. Recognized Muse runtimes use a private session file automatically; other keychain-less CLI environments require explicit `SNAPLII_ALLOW_INSECURE=1` opt-in for file caching.
- **Snaplii gateways only.** An API key is sent, and the connect page opened, only at production `https://aipayment.snaplii.com` or staging `https://aipay.stage.snaplii.com`. The terminal prompt and the secure card name the gateway the key goes to. A connect page set with `SNAPLII_ELICIT_URL` or `elicit_url` must be on the gateway's own address.
- **Charges are sent once.** Charges are not auto-retried. On an ambiguous bill-pay failure, query `billpay result` by `paymentNo` before retrying rather than sending the bill again; without a `paymentNo`, treat the outcome as unknown and reconcile before resubmitting. Transfers carry an idempotency key; retry a `CREATING` transfer with the same key, never a fresh one.
- **The API key is not stored:** Snaplii uses it once to obtain a token and never writes it to disk; only a host's own vault (Muse, Instinct) keeps it.
- **Data protection:** card redemption codes and PINs are shown only when the user asks for them or needs them to finish a purchase, and never appear in logs or summaries.

---

## Why Snaplii

### Why an agent needs a wallet of its own

AI agents can already find products, compare options, navigate merchant sites, fill in forms and reach checkout on a user's behalf. The step that remains is settling the order. Handing an agent a credit card, debit card or bank login exposes credentials that were never meant to be shared. Snaplii gives the agent a wallet instead: prepaid funds, a scoped key, and a limit the user controls.

### Three reasons to give your agent a Snaplii wallet

1. **Every order costs less.** At supported merchants Snaplii adds 5–10% in vouchers and cashback, so the agent can find the right product and settle it for less than the sticker price.
2. **One wallet, several currencies.** Snaplii, the product, holds balances in CAD, USD, RMB, USDT/USDC and more. This integration currently exposes Canadian (CAD) and US (USD) accounts; see the capability table above for what an agent can do today.
3. **Your card never reaches the agent.** The agent sees only the wallet: a balance, a key with a scope, and a daily limit. Your card and bank credentials stay in the app, where you can change the limit or revoke the key at any time.

### Completing an order at a merchant

Snaplii gives the agent what the merchant's checkout accepts, a gift card bought from the balance, while the credentials behind the balance stay away from the model. With a browser tool and the user's go-ahead, the agent can take an order from intent to confirmation page; without one, it hands the user the redemption code to finish the last step themselves.

### Built for agents

A wallet for agents has to answer questions a person's wallet never did: which agent is acting, what it may do, how much it may spend, and when its access should end. Snaplii's scoped, capped, revocable keys answer them per agent. The same wallet works with Claude, ChatGPT, Gemini, Llama, Mistral, OpenClaw, Muse, Instinct, or any agent that can read a skill, call a tool, or run a command.

---

## License

This project is licensed under the **Apache License 2.0**.

See the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) for details.

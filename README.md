# Agent-to-Merchant Payments by Snaplii

> A payment layer for AI agents: pay in the real world without handing the agent a credit card.

Snaplii gives an AI agent a prepaid, scoped, revocable payment account. The agent spends only the **Snaplii Cash** the user set aside, within a per-key spending limit the user chose, and never sees the user's card or bank credentials. It ships as an **Agent Skill**, an **MCP server**, a **Python CLI**, and a **REST API**, so it works with any agent that can read a `SKILL.md`, call MCP tools, run a command, or make HTTPS calls.

---

## For AI agents: start here

This section is the short version. The rest of this file is reference material for the steps it names.

### What you can do with Snaplii

| Capability | What happens | Canada (CAD) | United States (USD) | Key scope |
|---|---|---|---|---|
| Buy gift cards | Browse 500+ brands, quote the exact price with vouchers and up to 10% cashback, buy, then read the redemption code | Yes | Yes | `PAY_WRITE` |
| Pay a merchant with the card | Redeem the code on the merchant or delivery site and place the order. Needs a browser-automation tool; the `snaplii-autopilot` skill or the `snaplii_autopilot` MCP prompt carries the flow | Yes | Yes | `PAY_WRITE` |
| Check balance and cards | Spendable Snaplii Cash, owned cards, cashback estimates | Yes | Yes | `PAY_READ` |
| Pay bills | Supported utility, telecom and other billers, paid from Snaplii Cash | Yes | No | `PAY_WRITE` |
| Send money (P2P) | Send Snaplii Cash to another Snaplii user's phone number; cancellable for about 5 minutes, then it sends itself | Yes | Yes | `P2P` or `ALL` |

The account country is fixed at login and enforced by the gateway, so the catalog, currency, and bill-pay availability follow it automatically. Do not ask the user for a region.

### Choose how to connect

| You are | Use | Why |
|---|---|---|
| An agent that reads `SKILL.md` (Claude Code, Codex, Cursor, Gemini CLI, GitHub Copilot, OpenClaw, Muse, and others) | The **Agent Skill**, see [Install the Agent Skill](#install-the-agent-skill) | The skill carries the rules, the flows, and the host-specific login steps. It then picks MCP or the CLI for you |
| An MCP client (Claude Desktop, Codex, Cursor, VS Code, OpenClaw, Instinct) | The **MCP server**, see [MCP Server](#mcp-server-claude-openclaw-cursor-instinct) | 26 tools, plus an off-model login card or page on hosts that support one |
| A terminal, a script, or an agent with only a shell | The **CLI**, see [Quick Start](#quick-start) | One command per operation, JSON on stdout |
| A service or script without an agent runtime | The **REST API**, see [REST API](#rest-api-any-llm) | Plain HTTPS against `aipayment.snaplii.com`. An agent calling it directly must apply the rules the skill applies; the REST section lists them |

### How Snaplii and agent tools work together

- **The skill is the instruction layer.** It tells the agent when to connect, which tool or command to call, how to handle money, and what to say to the user. It does not execute anything by itself.
- **MCP and the CLI are two execution layers over the same gateway.** They expose the same operations and mostly the same names: `snaplii balance` is `snaplii_balance`, but `smart cashback` is `snaplii_cashback_calc`, `smart dashboard` is `snaplii_dashboard`, and some options differ. Use the [CLI](#cli-commands) and [MCP](#available-mcp-tools) tables rather than deriving one from the other. Both read the same configuration file (`~/.snaplii/config.json`, or `SNAPLII_CONFIG_PATH`), so a session stored there or in the OS keychain is visible to both; a session an MCP server could only keep in memory is not. Always check status in the runtime that will execute the task.
- **Which execution layer a skill uses depends on the host.** Muse uses the CLI. Instinct uses MCP only. Every other agent prefers the MCP tools when they are present and falls back to the CLI.
- **Authentication is per host.** The skill's Auth section and the MCP server's instructions carry the exact steps for Muse, Instinct, card-rendering hosts, and plain terminals. The agent checks `has_valid_token=true` before any Snaplii operation, including read-only ones, and connects first when it is false.
- **The API key stays out of the chat wherever the host allows it.** On hosts that render the secure card, open the hosted page, or hold the key themselves (Muse, Instinct), the key never passes through the model. A host with none of those offers the user two ways: `snaplii init` in the user's own interactive terminal, which keeps the key out of the chat, or, if the Snaplii MCP tools are available, pasting the key for `snaplii_init`, whose argument the model does see. When the MCP server keeps its session only in memory, a terminal login cannot reach it, so pasting is the way in. The key is exchanged once for a session token at a Snaplii gateway and is never written to disk.

### Install the Agent Skill

One command for any agent that supports the [Agent Skills](https://agentskills.io) format, using the [`skills` installer](https://github.com/vercel-labs/skills):

```bash
npx skills add Snaplii-Inc/agent-to-merchant-payments -g
```

This finds both skills in this repository and installs them under their skill names for the user (verified with `--list` against this repository). Without `-g` they go into the current project, next to its code. Add `--skill snaplii-cli` to install one, `-a claude-code` to target one agent, or `--list` to preview without installing. The installer, not this repository, decides which agents it supports; its README lists them.

| Skill | Source folder | Use when |
|---|---|---|
| `snaplii-cli` | `clawhub-publish/` | Browsing, buying, and managing gift cards; balance; bill pay; P2P transfers. Works without a browser |
| `snaplii-autopilot` | `clawhub-autopilot/` | The agent should also redeem the gift card on the merchant or delivery site and place the order. Needs a browser-automation tool |

Both skills expect the `snaplii` CLI or the Snaplii MCP server to be available. Install both with the installer in [Install the execution layer](#install-the-execution-layer) below.

**Manual install.** Copy a skill folder into your agent's skills directory, named after the skill:

```bash
git clone https://github.com/Snaplii-Inc/agent-to-merchant-payments.git
mkdir -p ~/.claude/skills
cp -r agent-to-merchant-payments/clawhub-publish   ~/.claude/skills/snaplii-cli
cp -r agent-to-merchant-payments/clawhub-autopilot ~/.claude/skills/snaplii-autopilot
```

Directories as documented by each agent and by the installer's compatibility table:

| Agent | Project skills directory | User-wide skills directory |
|---|---|---|
| Claude Code | `.claude/skills/` | `~/.claude/skills/` |
| Codex, Cursor, Gemini CLI, GitHub Copilot, Amp, OpenCode, Cline, Kimi Code | `.agents/skills/` | Agent-specific, for example `~/.codex/skills/`, `~/.cursor/skills/`, `~/.gemini/skills/`, `~/.copilot/skills/` |
| OpenClaw | `skills/` in the workspace | `~/.openclaw/skills/` |
| Muse | `~/workspace/skills/` inside the Muse runtime | Same |

**OpenClaw** can also install from ClawHub, which places the skill under `./skills/`:

```bash
clawhub install snaplii-a2m-payment
clawhub install snaplii-autopilot
```

**Muse** runs the skill with the CLI, not MCP. Upload or clone this repository in Muse and ask it to install the `snaplii-cli` skill from `clawhub-publish/`. When Muse installs the skill for the first time at your request, the skill continues straight into account connection unless you say to connect later. It reuses an existing session or stored key where possible; otherwise it guides you to create a key in the Snaplii App and enter it only in Muse's native secure dialog. If you cancel or connection fails, the skill stays installed but is not connected. Updating, reinstalling, or merely reading the skill is not a connection request.

**Instinct** can load the skill, but it executes only through MCP: the skill's Instinct section sends the agent to `snaplii_connect`, and the CLI refuses business commands there. Install the MCP server with the installer (`--host instinct`) and connect through the Instinct vault; see the Instinct block under [MCP Server](#mcp-server-claude-openclaw-cursor-instinct).

**Verify.** After installing, ask the agent "What can Snaplii do?" It should answer from the skill and, before any Snaplii operation, check authentication with `snaplii config show` or `snaplii_config_show`.

### Install the execution layer

Both skills need the `snaplii` CLI or the Snaplii MCP server. One script installs and verifies both into a dedicated environment (`~/.snaplii-env`) and prints a JSON report with the exact commands your host needs next. It never asks for an API key and never edits host configuration.

```bash
curl -fsSL https://raw.githubusercontent.com/Snaplii-Inc/agent-to-merchant-payments/main/scripts/install.py -o snaplii-install.py
python3 snaplii-install.py --host claude-code
```

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/Snaplii-Inc/agent-to-merchant-payments/main/scripts/install.py -OutFile snaplii-install.py
py -3 snaplii-install.py --host claude-code
```

`--host` is one of `claude-code`, `claude-desktop`, `codex`, `cursor`, `openclaw`, `instinct`; omit it for generic steps. Add `--cli-only` to skip the MCP server (refused in Instinct), `--check` to verify without changing anything, `--venv PATH` to choose the environment, `--python PATH` to try a specific interpreter first, or `--source PATH` to install from a repository clone instead of PyPI.

Any Python 3.8 or newer can start the script; if no Python 3.10+ is available it fetches CPython 3.12 with [uv](https://docs.astral.sh/uv/). uv keeps that Python in its own data directory, and the environment depends on it. With no Python at all, bootstrap uv first:

```bash
export UV_INSTALL_DIR="$HOME/.local/bin" UV_NO_MODIFY_PATH=1
curl -LsSf https://astral.sh/uv/install.sh | sh
"$UV_INSTALL_DIR/uv" python install --no-bin --no-registry 3.12
"$("$UV_INSTALL_DIR/uv" python find --no-project --managed-python 3.12)" snaplii-install.py
```

**Reading the report.** `status` is `installed` (exit 0), `partial` (the CLI works, the MCP server does not) or `failed`. `installed` covers the execution layer only: the skill and the host registration are separate steps listed in `next_steps`:

| `next_steps[].status` | What to do |
|---|---|
| `required` | Blocking. First do what its `why` says (for example install Python or close the host), then run its `command`, which re-runs the installer. Do this **once**: if the same `failure.code` comes back, stop and report it. When `command` is null, do not re-run; report `why` to the user. |
| `pending` | Do it next: `install_skill`, `register_mcp` (exact command or config snippet for your host), `reload_host`, `connect`. |
| `optional` | `cli_on_path` and `update`. |

`failure.retryable` says whether re-running after the remedy can succeed; when it is false, do not re-run, report the remedy. The JSON keys are a contract: within an `installer_version` keys are only added; renaming or removing one, or changing a status vocabulary or exit code, bumps `installer_version`.

**Updating.** Close the host so its registered Snaplii server stops, re-run the installer (it upgrades both packages in place), then open a new session. `snaplii update` upgrades only the CLI inside this environment and leaves the MCP server behind. Mirrors and proxies are read from `PIP_INDEX_URL`, `PIP_EXTRA_INDEX_URL`, `PIP_TRUSTED_HOST`, `PIP_CERT`, `PIP_PROXY` and the usual proxy variables; `pip.conf` is not read.

Windows support is by construction (`Scripts\`, the `py` launcher, PowerShell quoting) and has not yet been verified on a Windows machine.

### Rules the skill enforces

- Every Snaplii operation, including browsing and balance, requires `has_valid_token=true`. Connect first; the user does not need to ask to log in.
- Gift-card purchases within the key's daily limit run **without a per-transaction confirmation**; the limit the user set in the app is the consent. The skill asks for an explicit, current-turn "yes" before a **bill payment** (biller, account, and amount) and before the **final order on a merchant site** (summary and exact delivery address). The MCP server's instructions and tool descriptions apply the same rule.
- Pass a gift card's `item_id` exactly as `{cardBrandId}-{cardTemplateId}`, copied verbatim from the `denominations` that `browse brand` or `snaplii_browse_brand` returns. Never one ID alone, a name, or an assembled or guessed ID: a different well-formed ID buys a different card.
- Quote before buying. The quote's `you_pay` is the amount Snaplii Cash does not cover. If it is above zero, tell the user to top up in the app and stop.
- Read the balance from `snaplii_balance` or `snaplii balance`; never guess it. If the lookup fails, say so and rely on the quote's `you_pay`.
- Never ask for the API key in the chat while a card, a hosted page, or the host's own store can take it. A client with none of those offers the user two ways, and both work: `snaplii init` in the user's own interactive terminal, which keeps the key out of the chat, or, if the Snaplii MCP tools are available, pasting the key in the chat for `snaplii_init`, which passes it through the model once. When the MCP server keeps its session only in memory, only pasting reaches it. Do not run `snaplii init` from a shell tool yourself: without a terminal it reads nothing and answers `api_key_missing`. Never echo a key or token, and never show internal IDs such as `brandId`, `templateId`, or `cardNo`.
- After creating a transfer, tell the user the amount, the masked recipient, and the cancel deadline. If the result carries `cross_currency_notice`, show it and let the user keep or cancel the transfer. Use `finish` only when the user explicitly asks to send now.
- Charges are sent once. On an ambiguous failure, check the result (`billpay result` with the `paymentNo`, `transfer status`) before retrying; a successful or still-processing result is not a reason to pay again. If the failure came after sending and no `paymentNo` came back, report the outcome as unknown and stop until it is reconciled in the app or with support. Retry a transfer that returned `CREATING` with the **same** key, `--idempotency-key` in the CLI or `idempotency_key` in MCP, never a fresh one; if no order number came back, check `transfer list` first.

### Sessions and reconnecting

A connection exchanges the API key once for a session token. The key is not kept, so when the session ends the key has to be supplied again, unless the host holds it (Muse's credential store, the Instinct vault). The token lives in the OS keychain, in the owner-only config file, or only in the MCP server's memory. The gateway sets when a session expires, so rely on `has_valid_token` rather than a fixed lifetime. The Snaplii App shows a new key only once: keep it in a password manager, because it is needed again whenever a session ends on a host that does not store it.

`snaplii config show` and `snaplii_config_show` always return `has_valid_token`, `auth_state`, `host`, `auth_method`, `credential_storage`, `base_url`, and `next_action`. The states you will see:

| `auth_state` | Meaning | What to do |
|---|---|---|
| `ready` | The session is valid; `next_action` is `null` | Proceed |
| `auth_required` | Never connected in this runtime | Connect |
| `reauth_required` | The session expired, the gateway rejected it, or the MCP server restarted and lost a memory-only session | Connect again, the same way as the first time |
| `mcp_required` | The CLI was called in Instinct | Use `snaplii_connect` |

`host` is `unknown` for every host other than Muse and Instinct; that is the normal value, not a detection failure. An `agent_id` or `country` in the status does not mean the session is valid; only `has_valid_token` does.

`next_action` tells the executing runtime how to connect:

| Runtime and storage | `next_action` | Who acts |
|---|---|---|
| CLI, any storage | `{"type": "run_cli", "argv": ["snaplii", "--base-url", "...", "init"]}` | The user, in their own terminal; the agent re-checks afterwards |
| MCP with a memory or keychain session | `{"type": "call_mcp_tool", "tool": "snaplii_connect", "arguments": {}}` | The agent calls the tool |
| MCP with a config-file session | `run_cli` as above | The user, in a terminal; the MCP server then reads the shared file |
| Muse | `run_cli` with `init --vault-auth`, or a `muse_secure_entry` action when the stored key is missing or rejected | The agent; the stored key is reused without asking |
| Instinct | `call_mcp_tool` `snaplii_connect`, with the Instinct instruction attached | The agent, through the vault-filled page |

`argv[0]` is `snaplii` when that name on PATH is the same CLI; otherwise it is the CLI's absolute path, such as the installer's `~/.snaplii-env/bin/snaplii`. Relay `argv` unchanged.

Reconnecting by host:

- **Shell-only agent.** Ask the user to run the `next_action.argv` command in their own terminal and enter the key at the hidden prompt, then check the status again. On a machine without an OS keychain the CLI refuses to keep a session it cannot store: `init` answers `session_cache_failed` with reason `no_persistent_storage`. The user then sets `allow_insecure_mode: true` in the config file, or `SNAPLII_ALLOW_INSECURE=1`, to keep the token in the owner-only config file, and runs `init` again. The config-file setting applies to every Snaplii process, including an MCP server the host starts; the environment variable reaches that server only if the host passes it on.
- **MCP host with a card or a hosted page.** Call `snaplii_connect` only while `has_valid_token` is false. A result of `card_requested`, `pending`, `declined`, `elicit_unsupported`, or `elicit_failed` is not a connection; only `authenticated` or `already_connected` is. Re-check `snaplii_config_show` after the user finishes the card or page. A session the server could keep only in memory is gone after a restart: connect again in the restarted server.
- **MCP host with neither.** `snaplii_connect` answers `use_terminal_or_chat_key`; offer the two ways above and re-check afterwards.
- **Muse.** Follow `next_action`; the stored key is exchanged again without user input. Only a missing or rejected key opens Muse's native secure input.
- **Instinct.** Repeat the two `snaplii_connect` calls with the vault fill; the vault keeps the key across sessions.

A connection attempt can also end in one of these states. Honor its action before looking the status up again, because a later status check only shows `auth_required` or `reauth_required`:

| `auth_state` | `next_action` | What to do |
|---|---|---|
| `cancelled` | `stop` | The user cancelled; do not retry or switch methods |
| `invalid_key` | `offer_legacy` with `init --legacy-auth` on ordinary hosts, `muse_secure_entry` in Muse | The key was rejected; the user enters a key again |
| `temporary_gateway_error` | `retry_auth_later` | Snaplii was unreachable; retry later |
| `auth_response_invalid`, `session_cache_failed` | `stop` | Report the reason; no session was established |

---

## Table of Contents

- [For AI agents: start here](#for-ai-agents-start-here)
  - [What you can do with Snaplii](#what-you-can-do-with-snaplii)
  - [Choose how to connect](#choose-how-to-connect)
  - [How Snaplii and agent tools work together](#how-snaplii-and-agent-tools-work-together)
  - [Install the Agent Skill](#install-the-agent-skill)
  - [Install the execution layer](#install-the-execution-layer)
  - [Rules the skill enforces](#rules-the-skill-enforces)
  - [Sessions and reconnecting](#sessions-and-reconnecting)
- [How authorization works](#how-authorization-works)
- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [CLI Commands](#cli-commands)
- [Integration Guides](#integration-guides)
  - [MCP Server (Claude, OpenClaw, Cursor, Instinct)](#mcp-server-claude-openclaw-cursor-instinct)
  - [REST API (Any LLM)](#rest-api-any-llm)
- [Components](#components)
- [Uninstall](#uninstall)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [Why Snaplii](#why-snaplii)
- [License](#license)

---

## How authorization works

1. **Set aside funds.** Add the amount you want to make available as Snaplii Cash in the app.
2. **Define access.** Create an API key with the scope and spending limit the agent's task needs. Scopes: `PAY_READ` (read-only), `PAY_WRITE` (read, purchase, bill pay), `P2P` (transfers), `ALL`.
3. **Let the agent execute within that boundary.** Agent payments draw from Snaplii Cash, without exposing your bank or card credentials. You can change the limit or revoke the key in the app at any time.

Gift-card purchases can help users save through eligible offers and cashback. Available brands and savings vary by country, brand, and current quote; merchant offers can be combined only where their terms allow.

---

## Requirements

- Any Python 3.8+ to start the installer, which fetches CPython 3.12 with uv when no 3.10+ is available  
  _CLI needs 3.9+, the MCP server 3.10+. With no Python at all, bootstrap uv first (see Install the execution layer)._
- Git
- Node.js with `npx`, only for the one-line `npx skills add` install; the manual copy needs neither
- Snaplii Mobile App  
  _Required to generate your API key._

---

## Quick Start

### 1. Get Your API Key via Snaplii App

Before using the CLI or configuring your AI agent, generate a secure API key from the Snaplii mobile app:

1. Download the Snaplii app for [iOS](https://apps.apple.com/app/snaplii/id1596924498) or [Android](https://play.google.com/store/apps/details?id=com.snaplii.app).
2. Register an account and bind a payment method to load your Snaplii Cash balance.
3. In the app, go to **More → Payment Methods → AI Payment Management**.
4. Tap **+ New API Key**.
5. Set a name, choose the scope (`PAY_READ`, `PAY_WRITE`, `P2P`, or `ALL`), and set a hard spending limit.
6. Copy the API key.
   - Format: `snp_sk_live_...`
   - Keep it safe. It is shown only once.

### 2. Install the CLI and MCP server

Run the installer (see [Install the execution layer](#install-the-execution-layer) for the Windows and no-Python variants):

```bash
curl -fsSL https://raw.githubusercontent.com/Snaplii-Inc/agent-to-merchant-payments/main/scripts/install.py -o snaplii-install.py
python3 snaplii-install.py
```

It creates `~/.snaplii-env`, installs `snaplii-cli` and `snaplii-mcp`, verifies both, and prints the executables' absolute paths. Add `--cli-only` if you do not need the MCP server.

The steps below call `snaplii` by name. Use the absolute path from the report (`~/.snaplii-env/bin/snaplii`, or `%USERPROFILE%\.snaplii-env\Scripts\snaplii.exe` on Windows), or run the report's `cli_on_path` command first.

<details>
<summary><strong>Manual install (pipx or pip)</strong></summary>

Get the code:

```bash
git clone https://github.com/Snaplii-Inc/agent-to-merchant-payments.git
cd agent-to-merchant-payments
```

`pipx` is the smoothest manual path. It installs the CLI in its own isolated environment and puts the `snaplii` executable on your `PATH`.

#### macOS

```bash
brew install pipx
pipx ensurepath
```

#### Linux

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

#### Windows

**Option A — Scoop** (recommended):

```powershell
scoop install pipx
pipx ensurepath
```

**Option B — pip**:

```powershell
py -m pip install --user pipx
```

> If you see a warning that `pipx.exe` is not on PATH, run the following from the displayed path:
> ```powershell
> .\pipx.exe ensurepath
> ```

Restart your terminal after running `ensurepath`.

> **Note:** If you installed Python from the Microsoft Store, use `python3` instead of `py`.

#### All platforms

From the clone:

```bash
pipx install -e ./snaplii-cli
```

Or the published release, without cloning:

```bash
pipx install snaplii-cli
```

Open a new terminal window so the updated `PATH` takes effect, then verify the installation:

```bash
snaplii --help
```

> If you see `command not found`, see [Troubleshooting](#troubleshooting).

</details>

### 3. Authenticate

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

When Muse is recognized, `snaplii init` selects secure credential authentication by default and caches the session token in an owner-only file so later CLI commands can reuse it. The API key stays in Muse's secure credential store. The accompanying skill directs Muse to open its native secure input when a key is needed; cancellation stops the connection attempt. The first-install connection flow is described under [Install the Agent Skill](#install-the-agent-skill).

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

### 5. Pay a Bill — Canada only

Canadian accounts can pay supported utility, telecom, and other bills from Snaplii Cash. Bill pay is not available for US accounts. Check the account country before starting; use the live biller list and quote for availability and any applicable savings.

```bash
snaplii billpay payees                                                       # Find your biller
snaplii billpay detail --payee-code PE01015                                  # Check account rules
snaplii billpay save --payee-code PE01015 --first-name Alex --last-name Chen --amount 75.25 --account 1234567890
snaplii billpay quote --pay-code PC... --price 75.25                         # Preview savings
snaplii billpay pay --pay-code PC... --price 75.25                          # Pay from Snaplii Cash
snaplii billpay result --payment-no PSP...                                   # Check status
```

> Bill pay flow: **payees → detail → save (returns payCode) → quote → pay → result**. Payment draws from your prepaid Snaplii Cash balance without giving the agent access to your bank accounts or credit cards.

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
| `snaplii billpay history --payee-code CODE` | Get the previous bill instruction for a biller, for autofill; not a ledger of what was paid |
| `snaplii billpay quote --pay-code PC --price P` | Preview bill price with voucher/cashback |
| `snaplii billpay pay --pay-code PC --price P` | Canada only: pay the bill from Snaplii Cash |
| `snaplii billpay result --payment-no NO` | Check bill payment status |
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

Run the installer and keep the `register_mcp` step from its report; it contains the absolute path of `snaplii-mcp` and the exact command or config snippet for your host:

```bash
python3 snaplii-install.py --host claude-desktop   # or claude-code, codex, cursor, openclaw, instinct
```

<details>
<summary><strong>Manual install</strong></summary>

From the clone:

```bash
pip3 install -e ./snaplii-cli
pip3 install "mcp[cli]"
```

Or the published packages, without cloning:

```bash
pip3 install snaplii-mcp
```

`snaplii-mcp` installs the `snaplii-mcp` command and pulls in `snaplii-cli`. If you get an `externally-managed-environment` error, add `--break-system-packages` or use a virtual environment.

</details>

#### Step 2: Authenticate

Connecting from inside the client is preferred: call `snaplii_connect`, and the host renders a secure card or opens a hosted page where the user enters the key off-model. If the client can do neither, the user authenticates in their own terminal first; an agent cannot answer the hidden prompt:

```bash
~/.snaplii-env/bin/snaplii init
```

Enter your API key when prompted. After a manual install that put `snaplii` on PATH, `snaplii init` is the same command.

In Instinct, skip this step and follow the **Instinct** instructions under Step 3.

#### Step 3: Configure your MCP client

Use the `snaplii-mcp` path from the installer's `register_mcp` step; the report already contains the exact command or snippet for your host. After a manual install, use `python3 /path/to/agent-to-merchant-payments/mcp-server/server.py` when running from the clone, or the `snaplii-mcp` command when installed from PyPI.

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
      "command": "/absolute/path/to/python",
      "args": ["/absolute/path/to/agent-to-merchant-payments/mcp-server/server.py"]
    }
  }
}
```

Restart Claude Desktop after saving. From a clone, `python3 scripts/setup_claude_desktop.py` writes this entry for you.

</details>

<details>
<summary><strong>Claude Code</strong></summary>

Register the installer's server for your user, so it works in every project, then check it:

```bash
claude mcp add --scope user snaplii -- ~/.snaplii-env/bin/snaplii-mcp
claude mcp get snaplii   # expect "User config" and "Connected"
```

Without `--scope user`, Claude Code registers the server only for the directory you ran the command in. If it says the server already exists, it is registered; check it with `claude mcp get snaplii`. From a clone, register the clone's Python and `mcp-server/server.py` the same way.

</details>

<details>
<summary><strong>OpenClaw</strong></summary>

Register the server with the OpenClaw CLI ([reference](https://docs.openclaw.ai/cli/mcp/registry)):

```bash
openclaw mcp add snaplii --command python3 --arg /path/to/agent-to-merchant-payments/mcp-server/server.py
```

Then install the skill so the agent knows how to use the tools:

```bash
clawhub install snaplii-a2m-payment
```

</details>

<details>
<summary><strong>Instinct</strong></summary>

Instinct installs the MCP server with the installer and connects through the Instinct vault, so the API key never enters the chat.

1. Run the installer: `python3 snaplii-install.py --host instinct`. It refuses `--cli-only` because Instinct executes only through MCP.
2. Register the `snaplii-mcp` executable from the report's `register_mcp` step (`~/.snaplii-env/bin/snaplii-mcp`) as a stdio MCP server in Instinct. From a clone, `python3 /path/to/agent-to-merchant-payments/mcp-server/server.py` works too.
3. Skip `snaplii init`. In Instinct the CLI only serves `help`, `update`, `--version` and `config`; everything else runs through the MCP tools.
4. Connect right away. Call `snaplii_connect` and open the returned `connect_url` in the cloud browser. Use the Instinct vault fill action on the API key field with the returned `vault_entry`, click **Connect**, then call `snaplii_connect` again with the returned `eid` within 2 minutes. If the MCP tools only load in a new session, connect at the start of that session.
5. If the vault has no entry yet, the agent explains how to create a key in the Snaplii App and sends the vault's encrypted submission link so you can save it there.

The vault entry is `Snaplii API Key` for the production gateway. Other gateways append their host, for example `Snaplii API Key aipay.stage.snaplii.com`.

Instinct is detected from any environment variable whose name starts with `INSTINCT_`; Muse takes precedence. `snaplii_config_show` and `snaplii config doctor` list the matching variable names, never their values.

The one-time `eid` in the connect link is visible to the agent. Whoever holds it can take the session token once, within 2 minutes after **Connect** is pressed. If someone else takes it first, `snaplii_connect` reports `pending` instead of connecting.

</details>

<details>
<summary><strong>Cursor / VS Code / Other MCP clients</strong></summary>

Any MCP-compatible client can connect to the Snaplii MCP server. The server runs via stdio:

```bash
python3 /path/to/agent-to-merchant-payments/mcp-server/server.py
```

Configure your client to launch this command as an MCP stdio server.

</details>

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
| `snaplii_purchase` | Buy a gift card (no per-transaction confirmation; capped by the daily limit) |
| `snaplii_cashback_calc` | Calculate cashback savings |
| `snaplii_dashboard` | Owned card inventory summary |
| `snaplii_billpay_*` | Canada only: `payees`, `detail`, `history`, `save`, `vouchers`, `quote`, `pay`, `result` |
| `snaplii_transfer_*` | P2P transfers: `create` (cancellable ~5 min, then auto-sends), `cancel`, `finish` (send now), `status`, `list` |

The server also offers one MCP prompt, `snaplii_autopilot`, which carries the end-to-end buy, redeem, and order flow for hosts that can drive a browser.

> API keys are created and managed **only in the Snaplii app**. There are no CLI or MCP tools to list, create, or delete them.

---

### REST API (Any LLM)

For services and scripts that call Snaplii without an agent runtime. **An AI agent should use the [Agent Skill](#install-the-agent-skill) or the [MCP server](#mcp-server-claude-openclaw-cursor-instinct) instead**: they follow these rules for you. An agent that calls the API directly must follow each rule itself. [`openapi.yaml`](openapi.yaml) is the full contract and lists the same rules machine-readably under `info.x-agent-rules`.

| Rule | What a direct caller must do |
|---|---|
| Gift-card `itemId` is exactly `{cardBrandId}-{cardTemplateId}` | Build it from the two values `GET /v2/card-brands/{id}` returns, copied verbatim; never one ID alone, a template from another brand, or a guessed one |
| The price matches the card's denomination | Check `faceValueRules` before quoting: a fixed card takes exactly `priceStart`, a variable card `priceStart` to `priceEnd` |
| Quote first; stop when Snaplii Cash does not cover it | Do not purchase while `primaryPayAmount` is above zero |
| No blind purchase retry | `/v2/purchase` is not idempotent: after an unclear failure, check owned cards or the bill payment result first |
| Confirm bill payments | Get an explicit current-turn yes for biller, account and amount |
| Card codes, PINs and internal IDs stay private | Show a code only when the user asks; never show IDs |
| The API key stays out of the chat | Let the user enter it in their own terminal or a hosted page |
| Instinct executes only through MCP | Do not call this API from Instinct |
| Transfer idempotency key and conversion disclosure | Keep and reuse your own `Idempotency-Key`; disclose any currency conversion before the transfer sends |
| Snaplii Cash only, within the key's scope and daily limit | Expect a request beyond the key's scope or daily limit to be rejected |

**Base URL:** `https://aipayment.snaplii.com`

#### Step 1: Authenticate

```bash
curl -X POST https://aipayment.snaplii.com/v2/auth/token \
  -H "Content-Type: application/json" \
  -d '{"agent_id": "my-agent", "api_key": "snp_sk_live_..."}'
```

Returns a JWT token. Use it as `Authorization: Bearer <token>` for all subsequent calls.

#### Step 2: Browse gift cards

```bash
curl https://aipayment.snaplii.com/v2/card-brands?channel=HOME_PAGE \
  -H "Authorization: Bearer <token>"
```

#### Step 3: Check the denomination

```bash
curl https://aipayment.snaplii.com/v2/card-brands/CB... \
  -H "Authorization: Bearer <token>"
```

A `FIXED` template accepts exactly `priceStart`; a `VARIABLE` template accepts any amount from `priceStart` to `priceEnd`. Check this before quoting.

#### Step 4: Get a price quote

```bash
curl -X POST https://aipayment.snaplii.com/v2/quote \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "orderInfo": {"orderType": "GIFT_CARD", "item": {"itemId": "CB...-CT...", "price": "50"}, "orderContext": {"giftOrder": "false"}, "businessChannel": "APP"},
    "paymentContext": {"specifiedPrimaryPaymentMethod": "SNAPLII_CREDIT", "voucherOption": "BEST_FIT", "cashbackOption": "USE"}
  }'
```

A positive `primaryPayAmount` in the response means Snaplii Cash does not fully cover the order; stop and tell the user to top up. This is the field the CLI and MCP report as `you_pay`.

#### Step 5: Purchase

```bash
curl -X POST https://aipayment.snaplii.com/v2/purchase \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "orderInfo": {"orderType": "GIFT_CARD", "item": {"itemId": "CB...-CT...", "price": "50"}, "orderContext": {"giftOrder": "false"}, "businessChannel": "APP"},
    "paymentContext": {"specifiedPrimaryPaymentMethod": "SNAPLII_CREDIT", "voucherOption": "BEST_FIT", "cashbackOption": "USE"},
    "delivery": {"type": "WALLET", "immediateSend": "true"}
  }'
```

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
├── scripts/            # Claude Desktop setup, skill Auth-block sync, candidate bundles
├── tests/              # pytest suite for the CLI, the MCP server, and the skill documents
└── openapi.yaml        # REST API contract
```

The `skills/*.md` files and the `clawhub-*/SKILL.md` folders are kept byte-identical; `scripts/sync_muse_auth_docs.py --check` verifies that their Auth sections match the code.

---

## Uninstall

Remove what the installer and the host registration added:

1. Revoke the API key in the Snaplii App: **More → Payment Methods → AI Payment Management**.
2. Sign out locally: `~/.snaplii-env/bin/snaplii config clear`. It does not delete a key the host stores (Muse, the Instinct vault).
3. Remove the MCP registration: `claude mcp remove snaplii` in Claude Code, `codex mcp remove snaplii` in Codex, or delete the `snaplii` entry from `claude_desktop_config.json` or `.cursor/mcp.json`.
4. Remove the skills: `npx skills remove -g snaplii-cli snaplii-autopilot`. On OpenClaw, uninstall the ClawHub skill.
5. Delete the environment and the local configuration: `rm -rf ~/.snaplii-env ~/.snaplii` (PowerShell: `Remove-Item -Recurse -Force $HOME\.snaplii-env, $HOME\.snaplii`).
6. If the installer fetched CPython 3.12 with uv and nothing else uses it, remove it with `uv python uninstall 3.12`. If the installer also installed uv into `~/.local/bin`, delete `uv` and `uvx` there.

---

## Troubleshooting

### `snaplii: command not found` after install

If you used the installer, the CLI is not on `PATH` by design: call `~/.snaplii-env/bin/snaplii` (`Scripts\snaplii.exe` on Windows) or run the report's `cli_on_path` command.

After a manual install, the console script was placed somewhere not on your `PATH`. Run:

```bash
python3 -m pip show -f snaplii-cli
```

Look for an entry ending in `bin/snaplii` or `Scripts\snaplii.exe` on Windows. Then either prepend that directory to `PATH` in your shell configuration, or reinstall using `pipx`.

### `externally-managed-environment` from pip

Your system Python forbids global package installs. Use `pipx`, which is recommended, or a virtual environment. As a last resort, append `--break-system-packages` to the pip command.

### MCP server: `ModuleNotFoundError: No module named 'mcp'` or `'snaplii'`

The Python interpreter your MCP client is using does not have the required dependencies. Confirm with:

```bash
/absolute/path/to/python -c "import mcp, snaplii; print('ok')"
```

If it fails, install the missing packages into that same interpreter:

```bash
/absolute/path/to/python -m pip install -e ./snaplii-cli
/absolute/path/to/python -m pip install "mcp[cli]"
```

### The skill is installed but the agent does not use it

Check that the folder is named after the skill (`snaplii-cli` or `snaplii-autopilot`) and contains `SKILL.md` at its top level, and that it sits in the directory your agent reads (see the table under [Install the Agent Skill](#install-the-agent-skill)). Most agents load skills at session start, so open a new session after installing.

### Every Snaplii call answers `auth_required`, `reauth_required`, or `mcp_required`

There is no valid session in the runtime that is executing the task. `reauth_required` means there was one and it expired, was rejected, or was lost when the MCP server restarted. Run `snaplii config show` or `snaplii_config_show` and follow its `next_action`; [Sessions and reconnecting](#sessions-and-reconnecting) lists the actions by host. `mcp_required` means the host is Instinct: connect with `snaplii_connect` instead of the CLI.

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

The registration points at `~/.snaplii-env/bin/snaplii-mcp`. Re-run the installer: it recreates the environment at the same path, so the registration works again without changes.

### REST API returns `401` or `403`

A `401`, or a session-rejection code such as `MCAP9999` in the body, means the session is no longer valid: call `/v2/auth/token` again with your API key. A `403` is usually a scope or permission problem: check the key's scope and limits in the app. Business errors can also arrive in a `200` body, so read `rspMsgCd` rather than relying on the status alone.

---

## Security

- **Isolated spending access:** agents can spend only the prepaid Snaplii Cash available within their permissions and limits. They do not receive direct access to your bank accounts or credit cards.
- **Scoped API keys:** `PAY_READ` (read-only), `PAY_WRITE` (read, purchase, bill pay), `P2P` (transfers), `ALL`.
- **Spending limits:** strict per-key consumption caps are set via the mobile app. Transfers also have a rolling 24-hour per-key limit.
- **Consent is the daily limit, set once.** You authorize spending when you create the key and set its per-day cap in the app; within that cap the agent buys gift cards **without a per-transaction confirmation**, so the flow stays smooth. The skill and the MCP server's instructions both still ask before a bill payment and before a final merchant order. Spending is prepaid-only and the key is revocable, so the daily limit is the blast radius. On connect, the agent surfaces this once.
- **Off-model key entry.** The API key is entered through a secure MCP Apps card rendered by the host, on the hosted connect page, in a hidden terminal prompt, or supplied by the host's credential store (Muse) or vault (Instinct). A client with none of those offers the user's own terminal prompt and, where the MCP tools exist, `snaplii_init`; with `snaplii_init` the key passes through the model once. The session token is kept in the OS keychain, or in process memory for a long-lived MCP server. Recognized Muse runtimes use a private session file automatically; other keychain-less CLI environments require explicit `SNAPLII_ALLOW_INSECURE=1` opt-in for file caching.
- **Snaplii gateways only.** An API key is sent, and the connect page opened, only at production `https://aipayment.snaplii.com` or staging `https://aipay.stage.snaplii.com`. The terminal prompt and the secure card name the gateway the key goes to. A connect page set with `SNAPLII_ELICIT_URL` or `elicit_url` must be on the gateway's own address.
- **Charges are sent once.** Charges are not auto-retried. On an ambiguous bill-pay failure, query `billpay result` by `paymentNo` before retrying rather than re-paying; without a `paymentNo`, treat the outcome as unknown and reconcile before resubmitting. Transfers carry an idempotency key; retry a `CREATING` transfer with the same key, never a fresh one.
- **No credential storage:** API keys are used once to obtain a token and are never saved to disk.
- **Data protection:** card redemption codes and PINs are shown only when the user asks for them or needs them to finish a purchase, and never appear in logs or summaries.

---

## Why Snaplii

### Why AI agents need a new payment layer

AI agents are increasingly capable of discovering products and services, comparing options, navigating merchant websites, selecting the product or service, filling out forms, completing checkout flows, and taking actions on behalf of users.

But payment remains a critical gap. Giving an agent direct access to a user's credit card, debit card, or bank account creates unnecessary exposure of sensitive financial credentials. The question is no longer "Can AI agents shop?" but "How can AI agents pay safely?" Snaplii is built to solve that problem.

### Three reasons to pay through Snaplii

1. **Get more value from every payment.** At supported merchants, Snaplii can provide 5–10% additional discounts when users pay through Snaplii. An agent can find the right product, choose the right payment method, and complete the purchase at a better price. The payment layer becomes part of the shopping decision.
2. **Pay across multiple currencies.** Snaplii, the product, supports payment experiences across CAD, USD, RMB, USDT/USDC, and more. This integration currently exposes Canadian (CAD) and US (USD) accounts; see the capability table above for what an agent can execute today.
3. **Keep your credit card away from the agent.** Don't give your AI agent your credit card. Give it a payment account with controlled authorization. The agent never sees or stores the user's card credentials; it only uses the payment capabilities Snaplii makes available. Combined with tokenized payment infrastructure and scoped authorization, this puts a security boundary between the user's financial credentials and the agent's actions.

### Completing a merchant purchase

For merchant purchases, Snaplii provides the payment information required for the transaction while keeping the underlying payment credentials separated from the AI model. An agent can understand the user's intent, navigate the merchant website, select the product or service, reach checkout, use Snaplii's authorized payment capability, and complete the transaction.

When the agent has the required browser capabilities, account access, and user authorization, Snaplii can become part of the full shopping-to-payment workflow. When those conditions are not available, Snaplii provides the agent with the payment or exchange information needed for the user to complete the next step.

### Built for agentic commerce

Traditional payments were designed for humans holding cards and entering credentials. Agentic commerce introduces a different model: intent → agent → authorization → payment → merchant. The payment layer needs to understand not only who is paying, but also which agent is acting, what it is authorized to do, how much it can spend, which payment method it can access, whether the transaction can be reused, and when authorization should expire. Snaplii is building this infrastructure for the emerging AI agent economy.

Snaplii is model-agnostic. Whether you build with Claude, ChatGPT, Gemini, Llama, Mistral, OpenClaw, Muse, Instinct, or any other model or agent, if it can read a skill, call a tool, run a command, or make an HTTPS request, it can use Snaplii.

---

## License

This project is licensed under the **Apache License 2.0**.

See the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) for details.

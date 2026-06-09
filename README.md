# Agent-to-Merchant Payments by Snaplii

> Payments are broken for AI agents.

Snaplii unlocks real-world commerce with a safe, tokenized payment layer — powered by 500+ merchant gift cards **and bill pay** (utilities, telecom, and more) — and is the only one that actually saves you money (up to 10% per transaction), on top of any existing deals or promotions.
New users can unlock an exclusive welcome offer: **$10 off your first $30 transaction.**

---
## The Problem
AI agents can already:
- decide what to buy  
- compare options  
- navigate merchant platforms  

But they still can't safely pay.
Payments require trust, compliance, and risk control — things AI agents are not designed to handle.

Giving agents access to cards is not a solution. It's a risk.

---

## The Solution
Snaplii introduces a new model:
**User → Agent → Snaplii → Merchant**
- Users fund Snaplii  
- Agents operate within a controlled boundary  
- Each transaction is **pre-funded, isolated, and non-reusable**  

No shared credentials. No persistent risk.

In addition, Snaplii embeds **value directly into the payment layer** —  
transactions can **save up to 10%** and stack seamlessly with existing merchant deals and promotions.

---

## Works With Any LLM

Snaplii is **model-agnostic**. It works with any AI agent or LLM platform:

| Integration | How | Best for |
|---|---|---|
| **REST API** | Direct HTTP calls to `aipayment.snaplii.com/v2/*` | Any language, any framework |
| **Python CLI** | `pip install snaplii-cli` | Terminal agents, scripts, automation |
| **MCP Server** | Model Context Protocol (stdio) | Claude Desktop, OpenClaw, Cursor, VS Code |
| **OpenClaw Skill** | `clawhub install snaplii-a2m-payment` | OpenClaw agents |

Whether you're building with **Claude, ChatGPT, GPT-4, Gemini, LLaMA, Mistral, OpenClaw**, or any other model — if it can make HTTP calls or run a CLI, it can use Snaplii.

---

## Table of Contents

- [Requirements](#requirements)
- [Quick Start](#quick-start)
- [CLI Commands](#cli-commands)
- [Integration Guides](#integration-guides)
  - [REST API (Any LLM)](#rest-api-any-llm)
  - [MCP Server (Claude, OpenClaw, Cursor)](#mcp-server-claude-openclaw-cursor)
  - [Claude Code Skill](#claude-code-skill)
  - [OpenClaw Skill](#openclaw-skill)
- [Components](#components)
- [Troubleshooting](#troubleshooting)
- [Security](#security)
- [License](#license)

---

## Requirements

- Python 3.10+  
  _CLI works on Python 3.9+, but the MCP server requires Python 3.10+._
- Git
- Snaplii Mobile App  
  _Required to generate your API key._

<details>
<summary><strong>Mac users: check your Python version</strong></summary>

```bash
python3 --version
```

If your Python version is below 3.10, install Python via Homebrew:

```bash
brew install python@3.12
```

Then use `python3.12` and `pip3.12` instead of `python3` / `pip3` in the steps below.

</details>

---

## Quick Start

### 1. Get Your API Key via Snaplii App

Before using the CLI or configuring your AI agent, generate a secure API key from the Snaplii mobile app:

1. Download the Snaplii app for [iOS](https://apps.apple.com/app/snaplii/id1596924498) or [Android](https://play.google.com/store/apps/details?id=com.snaplii.app).
2. Register an account and bind a payment method to load your Snaplii Cash balance.
3. In the app, go to **More → Payment Methods → AI Payment Management**.
4. Tap **+ New API Key**.
5. Set a name, define the permission scope, and set a hard spending limit.
   - Example scopes: **Read-only** or **Purchase**
6. Copy the API key.
   - Format: `snp_sk_live_...`
   - Keep it safe — it will only be shown once.

### 2. Get the Code

```bash
git clone https://github.com/Snaplii-Inc/agent-to-merchant-payments.git
cd agent-to-merchant-payments
```

### 3. Install the CLI

`pipx` is the smoothest path. It installs the CLI in its own isolated environment and puts the `snaplii` executable on your `PATH`.

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

```bash
pipx install -e ./snaplii-cli
```

Open a new terminal window so the updated `PATH` takes effect, then verify the installation:

```bash
snaplii --help
```

> If you see `command not found`, see [Troubleshooting](#troubleshooting).

### 4. Authenticate

```bash
snaplii init
```

The CLI will prompt for your API key via hidden input (like a password prompt). The key is used only to obtain a session token and is **never stored on disk**. Agent ID is auto-derived from the key.

### 5. Use the CLI

```bash
snaplii browse tags --prov CA                        # Browse gift card categories (CA or US)
snaplii browse brand --id CB...                      # See denominations and cashback
snaplii balance --country CA                         # Check spendable Snaplii Cash balance (CA=CAD, US=USD)
snaplii quote --item-id CB...-CT... --price 50       # Preview price with voucher/cashback
snaplii giftcard list                                # View owned cards
snaplii purchase --item-id CB...-CT... --price 50 --prov ON   # Buy a card
```

> `--item-id` is formatted as `{cardBrandId}-{cardTemplateId}`. Both IDs are available from `snaplii browse brand`.
>
> **Note on `--prov`:** For `browse tags`, use country code (`CA` for Canada, `US` for United States). For `purchase`, use province/state code (`ON`, `QC`, `BC`, `NY`, `CA`, `TX`, etc.).

### 6. Pay a Bill

Pay utility bills, telecom, and more — from your Snaplii Cash balance, with the same cashback and vouchers as gift cards.

```bash
snaplii billpay payees                                                       # Find your biller
snaplii billpay detail --payee-code PE01015                                  # Check account rules
snaplii billpay save --payee-code PE01015 --first-name Alex --last-name Chen --amount 75.25 --account 1234567890
snaplii billpay quote --pay-code PC... --price 75.25                         # Preview savings
snaplii billpay pay --pay-code PC... --price 75.25 --prov ON                 # Pay from Snaplii Cash
snaplii billpay result --payment-no PSP...                                   # Check status
```

> Bill pay flow: **payees → detail → save (returns payCode) → quote → pay → result**. Payment draws from your prepaid Snaplii Cash balance — no checkout, no card sharing.

---

## CLI Commands

| Command | Purpose |
|---|---|
| `snaplii init` | Authenticate with your Snaplii API key |
| `snaplii config show` | Show current config and auth status |
| `snaplii browse tags` | Browse card categories and brands |
| `snaplii browse brand --id ID` | View brand details, denominations, and cashback |
| `snaplii giftcard list` | List owned gift cards |
| `snaplii giftcard detail --card-no NO` | View card redemption code and PIN |
| `snaplii balance [--country CA\|US]` | Show spendable Snaplii Cash balance (run before quoting; `--country` sets currency CA=CAD/US=USD) |
| `snaplii quote --item-id ID --price P` | Preview price with voucher/cashback before buying |
| `snaplii purchase --item-id ID --price P --prov PROV` | Purchase a gift card (prov = province/state) |
| `snaplii smart cashback --brand-id ID --amount A` | Calculate cashback savings |
| `snaplii smart dashboard` | View card inventory summary |
| `snaplii billpay payees` | List available billers (electricity, gas, telecom) |
| `snaplii billpay detail --payee-code CODE` | View biller account validation rules |
| `snaplii billpay save --payee-code CODE --first-name F --last-name L --amount A --account NO` | Save a bill pay instruction |
| `snaplii billpay quote --pay-code PC --price P` | Preview bill price with voucher/cashback |
| `snaplii billpay pay --pay-code PC --price P --prov PROV` | Pay the bill from Snaplii Cash |
| `snaplii billpay result --payment-no NO` | Check bill payment status |

---

## Integration Guides

### REST API (Any LLM)

The simplest integration — works with **any language, any LLM, any framework**. Just make HTTP calls.

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
curl https://aipayment.snaplii.com/v2/card-brands?channel=HOME_PAGE&locationProv=CA \
  -H "Authorization: Bearer <token>"
```

#### Step 3: Get a price quote

```bash
curl -X POST https://aipayment.snaplii.com/v2/quote \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "orderInfo": {"orderType": "GIFT_CARD", "item": {"itemId": "CB...-CT...", "price": "50"}, "orderContext": {"giftOrder": "false"}, "businessChannel": "APP"},
    "paymentContext": {"specifiedPrimaryPaymentMethod": "SNAPLII_CREDIT", "voucherOption": "BEST_FIT", "cashbackOption": "USE"}
  }'
```

#### Step 4: Purchase

```bash
curl -X POST https://aipayment.snaplii.com/v2/purchase \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "orderInfo": {"orderType": "GIFT_CARD", "item": {"itemId": "CB...-CT...", "price": "50"}, "orderContext": {"giftOrder": "false"}, "businessChannel": "APP"},
    "paymentContext": {"specifiedPrimaryPaymentMethod": "SNAPLII_CREDIT", "voucherOption": "BEST_FIT", "cashbackOption": "USE"},
    "delivery": {"type": "WALLET", "immediateSend": "true"},
    "locationProv": "ON"
  }'
```

---

### MCP Server (Claude, OpenClaw, Cursor)

The MCP server exposes 19 tools via the [Model Context Protocol](https://modelcontextprotocol.io/). Works with any MCP-compatible client.

#### Step 1: Install dependencies

```bash
pip3 install -e ./snaplii-cli
pip3 install "mcp[cli]"
```

If you get an `externally-managed-environment` error, add `--break-system-packages`.

#### Step 2: Authenticate

```bash
snaplii init
```

Enter your API key when prompted.

#### Step 3: Configure your MCP client

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

Restart Claude Desktop after saving.

</details>

<details>
<summary><strong>Claude Code</strong></summary>

```bash
claude mcp add snaplii -- python3 /path/to/agent-to-merchant-payments/mcp-server/server.py
```

</details>

<details>
<summary><strong>OpenClaw</strong></summary>

```bash
clawhub install snaplii-a2m-payment
```

Or add to your OpenClaw MCP config:

```json
{
  "mcp": {
    "servers": {
      "snaplii": {
        "command": "python3",
        "args": ["/path/to/agent-to-merchant-payments/mcp-server/server.py"]
      }
    }
  }
}
```

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
| `snaplii_init` | Authenticate with API key (not stored) |
| `snaplii_config_show` | Show auth status |
| `snaplii_balance` | Real spendable Snaplii Cash balance |
| `snaplii_browse_tags` | Browse gift card categories (CA/US) |
| `snaplii_browse_brand` | Brand details and denominations |
| `snaplii_giftcard_list` | List owned gift cards |
| `snaplii_giftcard_detail` | Card redemption code (sensitive) |
| `snaplii_quote` | Preview price with voucher/cashback |
| `snaplii_purchase` | Buy a gift card (requires confirmation) |
| `snaplii_cashback_calc` | Calculate cashback savings |
| `snaplii_dashboard` | Owned card inventory summary |
| `snaplii_billpay_*` | Bill pay: payees, detail, save, quote, pay, result |

> API keys are created and managed **only in the Snaplii app** — there are no CLI/MCP tools to list, create, or delete them.

---

### Claude Code Skill

```bash
mkdir -p ~/.claude/skills/snaplii-cli
cp skills/snaplii-cli.md ~/.claude/skills/snaplii-cli/SKILL.md
```

---

### OpenClaw Skill

Install from ClawHub:

```bash
clawhub install snaplii-a2m-payment
```

Or browse on ClawHub: [snapliiai/snaplii-a2m-payment](https://clawhub.ai/snapliiai/snaplii-a2m-payment)

---

## Components

```text
agent-to-merchant-payments/
├── snaplii-cli/       # Python CLI — pip-installable, works with any agent
├── mcp-server/        # MCP server — Claude, OpenClaw, Cursor, VS Code
├── skills/            # Claude Code skill definition
├── clawhub-publish/   # ClawHub skill artifact
└── clawhub-plugin/    # ClawHub MCP bundle plugin
```

---

## Troubleshooting

### `snaplii: command not found` after install

The console script was placed somewhere not on your `PATH`. Run:

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

If it fails, install the missing packages into that specific interpreter:

```bash
pip install -e ./snaplii-cli
pip install "mcp[cli]"
```

### REST API returns `401` or `403`

Your JWT token has expired. Call `/v2/auth/token` again with your API key to get a new token.

---

## Security

- **Limited authorization:** agents can only spend from Snaplii Cash, your prepaid balance.
- **Scoped API keys:** keys can be restricted to `PAY_READ` view-only or `PAY_WRITE` view + purchase.
- **Spending limits:** strict per-key consumption caps are set via the mobile app.
- **No credential storage:** API keys are used once to obtain a token and are never saved to disk.
- **Data protection:** card redemption codes and PINs are strictly masked and never exposed without explicit user consent.

---

## License

This project is licensed under the **Apache License 2.0**.

See the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) for details.

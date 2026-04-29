# Agent-to-Merchant Payments by Snaplii

> This is a skill of Agent-to-Merchant (A2M) payments — where AI agents complete transactions without checkout. Snaplii uses pre-funded gift cards as a payment rail, enabling instant, merchant-ready execution across 500+ brands.

---

## Table of Contents

- [Requirements](#requirements)
- [Quick Start](#quick-start)
  - [1. Get Your API Key via Snaplii App](#1-get-your-api-key-via-snaplii-app)
  - [2. Get the Code](#2-get-the-code)
  - [3. Install the CLI](#3-install-the-cli)
  - [4. Authenticate](#4-authenticate)
  - [5. Use the CLI](#5-use-the-cli)
- [Components](#components)
- [CLI Commands](#cli-commands)
- [Claude Desktop Setup MCP Server](#claude-desktop-setup-mcp-server)
- [Claude Code Skill](#claude-code-skill)
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

#### Windows PowerShell

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
```

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

Link your local CLI to your Snaplii account using the API key generated in Step 1:

```bash
snaplii init
```

The CLI will prompt for your API key via hidden input (like a password prompt). The key is used only to obtain a session token and is **never stored on disk**. Agent ID is auto-derived from the key.

### 5. Use the CLI

```bash
snaplii browse tags --prov CA                        # Browse gift card categories (CA or US)
snaplii browse brand --id CB...                      # See denominations and cashback
snaplii giftcard list                                # View owned cards
snaplii purchase --item-id CB...-CT... --price 50 --prov ON   # Buy a card
```

> `--item-id` is formatted as `{cardBrandId}-{cardTemplateId}`. Both IDs are available from `snaplii browse brand`.
>
> **Note on `--prov`:** For `browse tags`, use country code (`CA` for Canada, `US` for United States). For `purchase`, use province/state code (`ON`, `QC`, `BC`, `NY`, `CA`, `TX`, etc.).

---

## Components

```text
agent-to-merchant-payments/
├── snaplii-cli/       # Python CLI — pip-installable
├── mcp-server/        # MCP server for Claude Desktop
├── skills/            # Claude Code skill definition
├── clawhub-publish/   # ClawHub skill artifact
└── clawhub-plugin/    # ClawHub MCP bundle plugin
```

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
| `snaplii purchase --item-id ID --price P --prov PROV` | Purchase a gift card (prov = province/state) |
| `snaplii smart cashback --brand-id ID --amount A` | Calculate cashback savings |
| `snaplii smart dashboard` | View card inventory summary |

---

## Claude Desktop Setup MCP Server

Claude Desktop cannot run CLI commands directly. It requires an MCP server to bridge the gap. The Snaplii MCP server exposes tools that let Claude browse gift cards and make purchases through natural conversation.

### Step 1: Install dependencies

The MCP server requires Python 3.10+ and the `mcp` package. Install both the CLI and server dependencies:

```bash
pip3 install -e ./snaplii-cli
pip3 install "mcp[cli]"
```

If you get an `externally-managed-environment` error, add `--break-system-packages`:

```bash
pip3 install -e ./snaplii-cli --break-system-packages
pip3 install "mcp[cli]" --break-system-packages
```

### Step 2: Authenticate one time

The MCP server reads credentials from `~/.snaplii/config.json`. If you have not authenticated yet, run:

```bash
snaplii init
```

Enter your API key when prompted.

### Step 3: Configure Claude Desktop

Edit your Claude Desktop config file:

| OS | Config file location |
|---|---|
| macOS | `~/Library/Application Support/Claude/claude_desktop_config.json` |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json` |
| Linux | `~/.config/Claude/claude_desktop_config.json` |

Add the `mcpServers` section. Create the file if it does not exist. Use absolute paths:

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

> [!IMPORTANT]
> - `command` must point to the Python interpreter where `mcp` is installed. Find it with `which python3` or `echo ~/.venvs/snaplii/bin/python`.
> - `args` must be the exact path to `server.py` inside your cloned repo.

### Step 4: Restart Claude Desktop

Fully quit Claude Desktop, for example with `Cmd+Q` on macOS, then reopen it. You should now see the Snaplii tools available.

### Step 5: Verify

In a new Claude Desktop conversation, ask:

```text
What gift cards are available on Snaplii?
```

Claude should automatically call `snaplii_browse_tags` and display the categories.

---

## Claude Code Skill

Claude Code expects each skill in its own directory containing a `SKILL.md` file:

```bash
mkdir -p ~/.claude/skills/snaplii-cli
cp skills/snaplii-cli.md ~/.claude/skills/snaplii-cli/SKILL.md
```

Then open:

```text
~/.claude/skills/snaplii-cli/SKILL.md
```

If the file contains a line like this:

```text
Always prepend `export PATH="$PATH:/Users/.../bin" &&` before any snaplii command.
```

Replace the path with the directory that holds your `snaplii` binary. You can find it with:

```bash
which snaplii
```

On Windows, use:

```powershell
where.exe snaplii
```

If `snaplii` is already on your default `PATH`, you can delete the `export PATH=...` prefix entirely.

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

### Claude Desktop logs `ModuleNotFoundError: No module named 'mcp'` or `'snaplii'`

The Python interpreter referenced by `command` in `claude_desktop_config.json` does not have the required dependencies. Confirm with:

```bash
/absolute/path/to/python -c "import mcp, snaplii; print('ok')"
```

If it fails, install the missing packages into that specific interpreter:

```bash
pip install -e ./snaplii-cli
pip install "mcp[cli]"
```

---

## Security

- **Limited authorization:** agents can only spend from Snaplii Cash, your prepaid balance.
- **Scoped API keys:** keys can be restricted to `PAY_READ` view-only or `PAY_WRITE` view + purchase.
- **Spending limits:** strict per-key consumption caps are set via the mobile app.
- **Data protection:** card redemption codes and PINs are strictly masked and never exposed without explicit user consent.

---

## License

This project is licensed under the **Apache License 2.0**.

See the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0) for details.

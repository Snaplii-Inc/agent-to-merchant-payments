# Changelog

All notable changes to **Agent-to-Merchant Payments by Snaplii** will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions follow [Semantic Versioning](https://semver.org/).

---

## [0.15.0] — 2026-09-02

### Added
- **P2P transfers — send Snaplii Cash to a phone number.** Backed by the gateway's `/v2/transfers` endpoints, with a 5-minute undo window before auto-send. CLI: `snaplii transfer create/cancel/finish/status/list`, where `status --wait` polls every 3s until FINISHED/CANCELLED/FAILED. MCP: `snaplii_transfer_*` tools plus P2P server instructions (**26 tools total**). Every request carries a UUID `Idempotency-Key` that is echoed back so a retry reuses the same key, and client-side timeouts map to a retryable `CLIENT_TIMEOUT`. Responses are decorated with `cross_currency_notice` (a recipient in another country receives a different amount/currency) and a human-readable `fail_message` for every `fail_reason`. The skill's Step 7 flow asks for the phone number when missing, discloses cross-currency and lets the user keep or cancel, finishes only on an explicit "send now", and polls status after `finish`/`auto_finish_at`. Verified end-to-end on staging: create/cancel/finish, idempotent replay and `IDEMPOTENCY_MISMATCH`, a cross-currency USD→CAD quote, a real balance debit, and meaningful errors.

### Changed
- **`snaplii-mcp` now requires `snaplii-cli>=0.15.0`.** The server imports `snaplii.commands.transfer`, which only exists from 0.15.0; the old `>=0.12.1` floor would have let a resolver pair the new server with a CLI that has no transfer module, failing at import.

### Fixed
- **`snaplii init` no longer reports success on a failed login.** A 2xx `/v2/auth/token` response with no `access_token` is a failed login, not a success. It now raises `GatewayApiError` carrying the body's real reason (`rspMsgInf` / `message` / plain-text raw) instead of printing "authenticated" with nothing cached — the gateway currently answers HTTP 200 plus plain text when the core withholds the `x-auth-token` header.
- **Readable transfer validation errors.** `TransferApiError` parses the common validation shape (null `message`, per-field messages in `errors[]`), so a `@Valid` 400 reads as "amount: amount must be …" rather than "Transfer request failed (HTTP 400)".
- **Retry hints only where a retry is safe.** Only indeterminate outcomes (client timeout, `TRANSFER_INDETERMINATE`, `CONCURRENT_DUPLICATE`, `UPSTREAM_ERROR`, 5xx) get the same-key retry hint. `QUOTE_EXPIRED` now says to create again with a fresh key per the API spec, and terminal 4xx such as `INSUFFICIENT_BALANCE` get no hint at all.
- **Source and editable installs of `snaplii-cli` work again.** hatchling >= 1.32 rejects a readme path outside the project directory, so `readme = {file = "../README.md"}` broke `pip install -e ./snaplii-cli` and `uvx --from ./snaplii-cli`; older hatchling built an sdist with a `snaplii_cli-X/../README.md` member that pip refuses to extract. A CLI-focused `snaplii-cli/README.md` is now in-tree and the sdist carries it with no path traversal. PyPI wheel installs were unaffected either way.
- **Pin `mcp>=1.0,<2`.** mcp 2.x dropped the `list_tools`/`call_tool` decorators from `mcp.server.Server`, so `server.py` died at import with an `AttributeError` and the MCP server could not start on a clean install.
- **Two skill-instruction corrections.** Step 7 rule 5 told agents to confirm an auto-send with `transfer status --wait`, but `--timeout` defaults to 120s against a ~5-minute undo window, so that call always returned `wait_timed_out`; `--timeout` is now documented and a non-terminal return is called out as normal. Step 1 matched the whole `config show` output against `{}` to detect an unconfigured CLI, but a fresh machine now returns `{"credential_storage": ...}`, so the check never fired — it keys on a missing `agent_id` instead. The CLI's 120s default is deliberately unchanged: it is correct when polling after `auto_finish_at`, and raising it would block every caller for 5+ minutes.

---

## [0.14.1] — 2026-06-23

### Fixed
- **Reject gift-card amounts outside the brand's denomination range.** The app blocks an out-of-range amount in its UI, but the agent path (CLI/MCP) bypassed it: the backend accepted e.g. Uber Eats \$10 on a \$20-minimum card, returned `you_pay = 0`, charged Snaplii Cash, then the card failed and went to refund. `snaplii_quote` / `snaplii_purchase` and `snaplii quote` / `snaplii purchase` now validate `price` against the card's `faceValueRules` (VARIABLE → `priceStart ≤ price ≤ priceEnd`, FIXED → `price == priceStart`) before quoting or charging, and reject it with a clear message. The guard fails open if the catalog can't be read, so the server stays the final authority. This is client-side mitigation; the underlying gap is server-side (`quoteOrder.do` / `createOrderAndPay.do`).

### Changed
- **Connect routing is purely capability-based.** Dropped the Codex client-name allowlist added in 0.14.0: some Codex terminal sessions share Codex Desktop's client name but can't render cards, so name-based routing would have hidden the URL-mode path. Card hosts are detected positively from advertised capabilities, so falling through to terminal `snaplii init` stays safe.
- **Neutral connect copy.** The connect fallback presents the available paths as equal options and instructs the model not to label either as more/less secure, private, or recommended.

---

## [0.14.0] — 2026-06-19

### Added
- **Off-model API-key entry.** `snaplii_connect` opens a secure MCP Apps card (sandboxed iframe) where the user types the key; it reaches the server via an app-only `snaplii_submit_api_key` tool and never enters the chat/model context. Hosts that can't render the card fall back to `snaplii init` (terminal, still off-model); the key is never accepted in plain chat. (Brings the MCP server to **21 tools**.)
- **Capability-routed connect.** `snaplii_connect` picks the connect channel from the client's advertised capabilities: card hosts (Claude Desktop, VS Code, ChatGPT, Codex) render the secure card; URL-mode hosts get a hosted `/connect` page (key entered off the model **and** off the client, token claimed via a one-time id); terminal-only hosts (Claude Code) fall back to `snaplii init`. A small client-name allowlist routes Codex — which renders the card but doesn't advertise the UI capability — to the card instead of also firing a redundant URL page. Hosts that drop a downward iframe resize (Codex) get a filled "Connected" panel instead of a slim bar over dead space.
- **Already-connected guard.** `snaplii_connect` returns `already_connected` (no reconnect) when a valid token is already cached, and the card self-checks on (re)load — so revisiting an old conversation shows the connected state instead of re-prompting for a key.
- **One-time consent notice.** On successful connect the result carries a generic notice that purchases run within the app-set daily limit with no per-transaction confirmation.

### Changed
- **Smooth, zero-confirmation flow.** Removed the per-transaction confirmation: `snaplii_purchase` / `snaplii_billpay_pay` no longer require a `confirmation_token`, and the CLI no longer prompts before charging (`--yes` removed). Consent is front-loaded into the per-key daily limit set in the app (prepaid balance + scoped, revocable key), which the gateway enforces server-side. `snaplii_purchase` accepts `voucher_option` / `cashback_option` / `specified_voucher` directly so the charge matches the quote.
- **Charges are sent exactly once (no auto-retry).** On an ambiguous bill-pay failure, poll `billpay result` by `paymentNo` before retrying instead of re-paying.
- **Region read from the account, never asked.** `snaplii_browse_tags` now surfaces the account country (`account_country`) and `snaplii_balance` labels currency from the stored country, so the agent filters by region without asking — the country cached at login is authoritative, and a wrong `country` argument is ignored. (Extends 0.13.3.)
- **Non-blocking update check.** The PyPI version check no longer sits in the tool-call path: it reads the cache only and refreshes in a background thread, so the first tool call after a restart never waits on PyPI.

### Security
- **No plaintext token on disk by default.** When no OS keyring is available the access token is held in process memory; writing it to `~/.snaplii/config.json` requires explicit opt-in, and `clear()` purges the in-memory copy.

---

## [0.13.3] — 2026-06-16

### Changed
- **Region is now automatic — `--prov` / `locationProv` removed from `browse`, `purchase`, and `billpay pay`.** The account's country is fixed at login and enforced server-side, so the catalog is already scoped to the user and `locationProv` is no longer sent. `purchase` / `billpay pay` no longer accept `--prov` (it was previously required on `purchase`); `browse tags` takes only `--channel`. Verified against the gateway that `/v2/purchase` does not require `locationProv` (a request without it still returns `SUCCESS`), and that `browse` defaults the region server-side. MCP tools, skills, plugin README, and README updated to drop the region parameter and to read the user's country from `snaplii config show` instead of asking.

### Removed
- **Dead `card_brands` command module** removed from the CLI (no longer registered or referenced).

---

## [0.13.2] — 2026-06-09

### Fixed
- **Balance currency is no longer hardcoded to CAD.** `snaplii balance` / `snaplii_balance` previously labeled every balance `CAD`, which is wrong for US users. Snaplii Cash is held in the account's local currency and the backend doesn't return it, so it now follows the user's country: pass `--country CA|US` (CLI) or `country` (MCP) → `CA=CAD`, `US=USD`. When no country is given, the currency is omitted (with a note) instead of asserting CAD. Tool/skill/instruction docs updated to pass the country and never assume CAD.

---

## [0.13.1] — 2026-06-05

### Fixed
- **Purchase no longer fails when a non-default payment method is sent.** Explicit `SNAPLII_CASH` / `SNAPLII_DEBIT` is rejected by the backend as `MCA20004 服务未开通`, while the default `SNAPLII_CREDIT` (which draws from the same prepaid Snaplii Cash pool) works. Reported from the field: an agent that passed an explicit method hit MCA20004, then succeeded on retry without one.
  - **MCP:** removed the `payment_method` parameter from `snaplii_purchase`; the handler now always uses `SNAPLII_CREDIT` (ignores any stray arg).
  - **CLI:** removed `--payment-method` / `--payment-token` from `purchase` and `--payment-method` from `quote`; both always use `SNAPLII_CREDIT`.
  - **Errors:** `MCA20004` now maps to a friendly "that method isn't enabled — retry without specifying one" message.
  - Skill + plugin docs updated to stop presenting a payment-method knob.

---

## [0.13.0] — 2026-06-04

### Added
- **Balance query (`snaplii balance` / `snaplii_balance`).** Read the user's real, current spendable Snaplii Cash balance — the same pool that pays for gift cards and bills. Reverses the previous "there is no balance query, never state it" rule now that a real endpoint exists. The recommended purchase flow is now **balance → quote → confirm → buy**: check the balance first to tell the user up front whether an order is affordable, with the quote's `you_pay` still the hard safety net for a specific order.
  - Gateway: new `GET /v2/balance` (proxies `getUserCashBack.do`).
  - CLI: `snaplii balance`. MCP: `snaplii_balance` tool (19 tools total).

### Changed
- Server instructions, autopilot prompt, Claude Desktop project instructions, and all skills updated: the agent now **queries** the balance via the tool instead of refusing to report it — but still never guesses or fabricates a number, and says so if the query fails.

> Requires the gateway deploy that ships `GET /v2/balance`. Claude Desktop users: update (`uvx snaplii-mcp` re-resolves on restart, or update the ClawHub plugin) to get the `snaplii_balance` tool.

---

## [0.12.1] — 2026-06-02

### Fixed
- **`No module named 'httpcore'` on init.** Some environments installed httpx without its httpcore dependency, crashing the MCP server's login. `httpcore` is now an explicit dependency, and the client fails early with an actionable "reinstall / restart the connector" message instead of a cryptic crash. Existing users: update (`pip install -U snaplii-mcp` or restart the ClawHub plugin so uvx re-resolves).

---

## [0.12.0] — 2026-06-02

### Added
- **Exact denominations (no hallucinated amounts).** `snaplii_browse_brand` / `snaplii browse brand` now return a structured `denominations` list — FIXED cards show `amount`, VARIABLE cards show the real `min`/`max` straight from the gateway. Instructions tell the agent to use these and never invent a range (fixes wrong "minimum amount" claims for custom-value cards).
- **One-command Claude Desktop setup** for cloned repos: `python3 scripts/setup_claude_desktop.py` merges the Snaplii MCP server into the Claude Desktop config (preserving other entries). Claude Desktop can't auto-discover a folder, so this does the registration.
- **Editable / git-clone aware updates.** The update reminder and `snaplii update` now detect an editable (`pip install -e` / clone) install via PEP 610 and tell the user to `git pull` instead of `pip install -U` (which would clobber the checkout).

### Changed
- Autopilot + instructions now require the agent to **explicitly confirm the delivery address** (read it back) before placing any delivery/shipping order — never assume a saved/default address.

---

## [0.11.1] — 2026-06-02

### Added
- **Update reminder on every MCP tool response.** When a newer `snaplii-mcp` is on PyPI, an `update_available` field is attached to every tool result (cached once per process, fail-silent) — so the agent surfaces the update no matter which tool it calls, not only on `snaplii_config_show`. Server instructions tell the agent to relay it. Note: end users update via PyPI/ClawHub, never `git` — this checks the actual distribution channel.

---

## [0.11.0] — 2026-06-02

### Added
- **Full-chain autopilot for Claude Desktop (and any browser-capable host).** New MCP `snaplii_autopilot` prompt (shows in the prompt/“+” menu) runs the end-to-end flow: buy a gift card → redeem the code → place the order on the merchant/delivery site, pausing for explicit confirmation before the final "Place Order". Falls back to handing over the code if no browser tool is present.
- Standalone **Snaplii Autopilot** ClawHub skill (`snaplii-autopilot`) for Claude Code / OpenClaw users with a browser tool.

### Changed
- MCP `snaplii_purchase` / `snaplii_giftcard_detail` descriptions now enable **conditional** browser chaining — if the host can control a browser, the agent may redeem + order (with confirmation); otherwise it hands over the code. (Replaces the blanket "never place orders" wording from 0.10.0, which was blocking Claude Desktop's built-in browser flow.)

---

## [0.10.0] — 2026-06-02

### Fixed
- **Payments no longer get refused as "high risk".** MCP tool descriptions and the skill now state the safety model up front — spending is from the user's prepaid Snaplii Cash balance (no card charged), the API key is scoped/revocable/spend-capped, and every purchase needs explicit confirmation — so the agent proceeds confidently after the user confirms instead of refusing.
- **Clear "no order placement" expectation.** The skill and `snaplii_purchase` / `snaplii_giftcard_detail` descriptions make explicit that Snaplii delivers a gift card + redemption code and does **not** place orders on delivery apps or drive a browser. After a purchase the agent hands over the code and how to redeem it in the merchant app (e.g. Uber Eats / DoorDash → Payment → Add Gift Card). This fixes confusing failures when users expected the agent to "order on Uber Eats".

---

## [0.9.1] — 2026-06-01

### Added
- **MCP update check.** `snaplii_config_show` now includes an `update_available` field when a newer `snaplii-mcp` is on PyPI, so the agent can prompt the user to update and restart (a long-running MCP server can't update itself). Same cached, fail-silent check as the CLI.

### Changed
- `version_check.check_for_update(store, package=...)` is now package-parameterized (one daily cache per package); MCP `config_show` hides internal `_`-prefixed fields

---

## [0.9.0] — 2026-06-01

### Added
- **Auto-update mechanism.** The CLI checks PyPI for a newer release (cached once per day, 2s timeout, fails silently) and prints an update notice to **stderr** — never polluting the JSON on stdout. New `snaplii update` command self-installs the latest version via pip. The skill instructs agents to run `snaplii update` when they see the notice.

### Fixed
- Agents must never state or guess the user's Snaplii Cash balance (there is no balance query) — skill + plugin now forbid reporting a balance and direct users to the app. A real balance endpoint is planned.

### Changed
- `config show` hides internal bookkeeping fields (e.g. the version-check cache)

---

## [0.8.0] — 2026-05-29

### Removed
- **API key management removed from CLI and MCP** — `snaplii apikey list/create/delete` and the `snaplii_apikey_*` MCP tools are gone. API keys are created, viewed, and revoked **only in the Snaplii app**. This is intentional: agents should never manage their own keys. (Breaking change for any scripts using `snaplii apikey`.)

### Fixed
- **Spending-limit and business errors now show the real cause.** Previously a daily-spend-limit hit surfaced as a generic "Gateway temporarily unavailable" (HTTP 502). The gateway now returns business rejections as HTTP 422 with the full upstream body (error code + message), and the CLI surfaces the actual message (e.g. "you may have reached a spending limit").
- Gateway logs the upstream error body on failure (was logging only the status code), making issues like spend-limit rejections debuggable.

### Changed
- CHANGELOG renamed from "AI Passport" to "Agent-to-Merchant Payments by Snaplii"

---

## [0.7.0] — 2026-05-26

### Added
- **Bill Pay** — pay utility bills, telecom, and more from Snaplii Cash, with the same vouchers and cashback as gift cards. New `snaplii billpay` commands: `payees`, `detail`, `history`, `save`, `vouchers`, `quote`, `pay`, `result`. 8 matching `snaplii_billpay_*` MCP tools.
- `snaplii-mcp` published to PyPI (depends on `snaplii-cli`), so the MCP server runs via `uvx snaplii-mcp` — no manual path setup.

### Changed
- Bill pay draws from prepaid Snaplii Cash (`SNAPLII_CREDIT`), not PayPal — keeps the agent-autonomous flow with no PayPal redirect when the balance covers the bill.

---

## [0.6.1] — 2026-05-19

### Fixed
- `snaplii init` reads the API key silently from a pipe (`echo key | snaplii init`) without a stray prompt in non-TTY environments
- CLI version now read from package metadata (was hardcoded, drifted out of sync)

---

## [0.6.0] — 2026-05-05

### Added
- **`snaplii quote`** — preview an order before buying: shows voucher discount, Snaplii Cash applied, and the actual amount you pay
- Auto-apply the best available voucher (`--voucher BEST_FIT`)
- Warning when Snaplii Cash doesn't fully cover an order (purchase blocked until topped up)

---

## [0.5.0] — 2026-04-29

### Security
- **API key is never stored.** It's read from hidden stdin input (never a CLI argument), used once to obtain a token, then discarded. Token expiry requires re-running `snaplii init`.
- `agent_id` auto-derived from the API key — no longer required on `init`

---

## [0.4.0] — 2026-04-28

### Security
- **API keys and access tokens now stored in system keychain** (macOS Keychain / Windows Credential Locker / Linux Secret Service) instead of plaintext `config.json`
- `config.json` only contains non-sensitive data (agent_id, base_url, token_expires_at)
- Graceful fallback to config file if keyring is not available (with warning)

### Fixed
- `MACP6005` error message: no longer assumes "insufficient balance" — now says "payment service error, may be temporary"
- `--prov` on purchase: now required (was defaulting to ON, failing for US users)
- `agent_id` confusion: README + MCP clarify it's user-defined, not system-provided

### Added
- `credential_storage` field in `config show` and `init` output — shows "system keychain" or "config file"
- `keyring>=25.0` dependency
- API key creation guide in README (download app → register → create key)

---

## [0.3.0] — 2026-04-26

### Security
- **[CRITICAL]** `snaplii init` no longer prints access_token in output
- **[CRITICAL]** `snaplii apikey create` masks key by default; use `--reveal` flag to show full key
- **[CRITICAL]** `snaplii apikey list` masks all key values (CLI + MCP)
- **[CRITICAL]** Non-localhost gateway connections now enforce HTTPS
- **[HIGH]** MCP `snaplii_config_show` masks `api_key` and strips `token_expires_at`
- **[HIGH]** MCP `snaplii_giftcard_detail` wraps response with `_sensitive` flag and security notice
- **[HIGH]** MCP `snaplii_apikey_create` never returns full key in conversation context
- **[MEDIUM]** Token refresh safety margin increased from 30s to 90s

### Fixed
- MCP server default URL now points to `aipayment.snaplii.com` (was `gateway.snaplii.com`, causing 404)
- MCP + CLI aligned: `payment_method` default `SNAPLII_CREDIT`, `prov` default `CA`
- Empty `error_code` bug: 502/401/404 and unknown errors now return meaningful messages
- Skill no longer has hardcoded user path (`/Users/cz/...`)
- Install path fixed: `pip install -e snaplii-cli/` (was `./cli`)

### Changed
- Default payment method: `SNAPLII_CASH` → `SNAPLII_CREDIT` (payment routing identifier)
- Default prov: `ON` → `CA` (country-level filter, not province)
- API key scope descriptions: `PAY_READ (view cards only)` / `PAY_WRITE (view + purchase)`

### Added
- Comprehensive Claude Desktop MCP setup guide in README (step-by-step with troubleshooting)
- Python 3.10+ installation guide for Mac users
- Partner's skill hardening: dynamic PATH resolution, prompt injection defense, error handling rules
- `--reveal` flag on `snaplii apikey create` for explicit key display

---

## [0.2.0] — 2026-04-24

### Added
- **Smart features**: `snaplii smart cashback` (calculate savings), `snaplii smart dashboard` (card inventory)
- **Purchase command**: `snaplii purchase --item-id CB...-CT... --price 50`
- **Browse commands**: `snaplii browse tags`, `snaplii browse brand --id CB...`
- **API key management**: `snaplii apikey list/create/delete`
- **MCP server**: 12 tools for Claude Desktop integration
- Error code translation: common Snaplii error codes mapped to English messages
- Region-aware filtering: agent asks user's country before showing brands

### Changed
- CLI connects to gateway (`aipayment.snaplii.com`) via `/v2/*` endpoints with JWT auth
- Sensitive card info (code, PIN) requires explicit user confirmation before display

---

## [0.1.0] — 2026-04-22

### Added
- Initial release
- `snaplii init` — authenticate with API key
- `snaplii config show/set` — manage configuration
- `snaplii giftcard list/detail` — view owned gift cards
- MCP server with basic tools
- Claude Code skill definition
- Claude Code skill definition

---

## Version History Summary

| Version | Date | Highlights |
|---------|------|------------|
| 0.15.0 | 2026-09-02 | P2P transfers to a phone number (26 MCP tools); `mcp<2` pin |
| 0.14.1 | 2026-06-23 | Reject out-of-range gift-card amounts; capability-based connect |
| 0.14.0 | 2026-06-19 | Off-model API-key entry via MCP Apps card; zero-confirmation flow |
| 0.13.3 | 2026-06-16 | Region automatic — `--prov` / `locationProv` dropped |
| 0.13.2 | 2026-06-09 | Balance currency follows the account country, never hardcoded CAD |
| 0.13.1 | 2026-06-05 | Always `SNAPLII_CREDIT` — payment-method knob removed (MCA20004) |
| 0.13.0 | 2026-06-04 | Balance query (`snaplii balance`); 19 MCP tools |
| 0.12.1 | 2026-06-02 | Fix `No module named 'httpcore'` — explicit dep + clear error |
| 0.12.0 | 2026-06-02 | Exact denominations, Claude Desktop setup script, editable-aware updates, address confirmation |
| 0.11.1 | 2026-06-02 | Update reminder attached to every MCP tool response |
| 0.11.0 | 2026-06-02 | Full-chain autopilot (MCP prompt) for Claude Desktop + browser hosts |
| 0.10.0 | 2026-06-02 | Safety framing so payments aren't refused; "no order placement" expectation |
| 0.9.1 | 2026-06-01 | MCP update check in config_show |
| 0.9.0 | 2026-06-01 | CLI auto-update mechanism, never-guess-balance rule |
| 0.8.0 | 2026-05-29 | Remove CLI/MCP API-key management, clearer spend-limit errors |
| 0.7.0 | 2026-05-26 | Bill Pay (utilities, telecom); snaplii-mcp on PyPI |
| 0.6.1 | 2026-05-19 | init pipe fix, version from package metadata |
| 0.6.0 | 2026-05-05 | `snaplii quote` — voucher/cashback preview |
| 0.5.0 | 2026-04-29 | API key never stored, agent-id auto-derived |
| 0.4.0 | 2026-04-28 | System keychain for secrets, user feedback fixes |
| 0.3.0 | 2026-04-26 | Security hardening, MCP fixes, user feedback |
| 0.2.0 | 2026-04-24 | Full purchase chain, smart features, MCP 12 tools |
| 0.1.0 | 2026-04-22 | Initial release |

# Changelog

All notable changes to **Agent-to-Merchant Payments by Snaplii** will be documented in this file.

Format follows [Keep a Changelog](https://keepachangelog.com/). Versions follow [Semantic Versioning](https://semver.org/).

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

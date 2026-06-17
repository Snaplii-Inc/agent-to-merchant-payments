# A2M Smooth Zero-Confirmation Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the payment flow smooth. After a one-time, off-model API-key entry, the agent executes purchases and bill payments with **zero per-transaction confirmation**. Consent is front-loaded: it lives in the per-key daily limit the user sets in the Snaplii app at key-creation time.

**Why now:** This intentionally reverses the per-transaction confirmation gate added by `feature/payment-security-hardening`. The product decision is that the **daily limit is the consent** (prepaid balance + scoped, revocable, capped key), so a quote→token→confirm gate on every charge is friction without a matching safety gain. We keep that branch's *off-model key entry* and *secret-hygiene* work; we remove its *confirmation gate*.

**Security model (after this change):**
- **Trust anchor (one-time):** API key entered off-model via the MCP Apps card (`cards.py`), never seen by the model. Hosts without MCP Apps but with a terminal → user runs `snaplii init` themselves. Pure-chat hosts with neither → key entry is refused (never accept the key in chat).
- **Spending consent (set in app, not here):** per-key daily limit, enforced server-side by the gateway (`SpendingLedgerRepository`, `SpendingLimitExceededException`, default $20/24h). The gateway is **not changed** by this plan.
- **Per transaction:** no confirmation, no single-transaction cap. The agent executes and reports.
- **Double-charge safety:** charges are sent exactly once (no auto-retry — `httpx.Client(timeout=30.0)`, no retry logic). On an ambiguous bill-pay failure, query status via `billpay_pay_result(paymentNo)` before any re-send rather than blindly re-paying.

**Tech Stack:** Python 3.9+, `click` (CLI), `mcp` SDK (server, stdio + MCP Apps card), `httpx` (gateway), `keyring` (token storage), `pytest` (tests). The interpreter is `.venv/bin/python3`; tests run with `.venv/bin/python3 -m pytest`.

**Constraints (locked decisions):**
- Do **not** change the gateway. Daily limit and key creation are app-side concerns.
- Daily-limit surfaced to the user is a **generic message only** (a2m cannot read the real number — `/v2/auth/token` returns only `access_token / token_type / expires_in / country`). Returning the real number is a future gateway ask, out of scope.
- Idempotency: **form 3** (no auto-retry + bill-pay check-before-retry). No client idempotency key, no create/pay split (both need the gateway).

---

## File Structure

**Delete (confirmation gate — no longer used):**
- `snaplii-cli/src/snaplii/security/quote_store.py` — the single-use quote→token store.
- `snaplii-cli/src/snaplii/security/canonical.py` — canonical quote record + confirmation text; its only consumers (token binding + CLI prompt) are removed.
- `snaplii-cli/src/snaplii/security/__init__.py` — package becomes empty → remove the package.
- `tests/test_quote_store.py`, `tests/test_canonical.py` — cover deleted modules.

**Modify:**
- `mcp-server/server.py` — remove `QuoteStore`/`_QUOTE_STORE`, `_enforce_confirmation`, `build_canonical_quote` import; `snaplii_quote` / `snaplii_billpay_quote` stop minting `confirmation_token`; `snaplii_purchase` / `snaplii_billpay_pay` charge directly (no token validate/consume); drop `confirmation_token` from both tools' `inputSchema` + descriptions; update `_SERVER_INSTRUCTIONS`. Append a one-time daily-limit notice to the connect/submit success path.
- `snaplii-cli/src/snaplii/commands/purchase.py` — remove the `--yes` flag (`:27`), the `if not yes:` confirmation block (`:40-49`), and the `canonical` import (`:5`); `purchase_cmd` calls `create_order_and_pay` directly.
- `snaplii-cli/src/snaplii/commands/billpay.py` — remove the parallel confirmation block on the `pay` subcommand (and its `--yes` if present); add check-before-retry guidance/handling around `pay` using `billpay_pay_result`.
- `tests/test_server_confirm.py` — rewrite: assert purchase/bill-pay charge **once with no token**; drop expired/replay/token-mismatch cases tied to the removed gate. Keep "charges run under the requested voucher/cashback context" if still relevant.
- `tests/test_cli_purchase_confirm.py` — rewrite to assert the CLI charges without prompting (or delete if it only tested the prompt).
- `README.md`, `CHANGELOG.md` — replace "quote-bound confirmation token / prompts before charging" wording with "executes within the app-set daily limit, no per-transaction confirmation"; document the one-time limit notice and the MCP-Apps / `snaplii init` / refuse fallback ladder.
- `snaplii-cli/pyproject.toml`, `mcp-server/pyproject.toml` — version bump.

**Keep unchanged (off-model entry + hygiene):**
- `snaplii-cli/src/snaplii/cards.py` — MCP Apps key-entry card.
- `snaplii-cli/src/snaplii/config_store.py` — key never stored, token in memory/keyring, plaintext only on explicit opt-in.
- `snaplii-cli/src/snaplii/currency.py` — used for display labels (CA$/US$).
- `_authenticate` / connect / submit-api-key flow in `server.py`.
- `quote` / `billpay_quote` remain as **informational** calls (you_pay / affordability), just no token.

All commands run from repo root `/Users/jsy/Documents/Snaplii/agent-to-merchant-payments`.

---

## Task 1: Remove the confirmation gate from the MCP server

**Files:** Modify `mcp-server/server.py`

- [ ] Remove `from snaplii.security.quote_store import QuoteStore` and `from snaplii.security.canonical import build_canonical_quote` (`:27-28`); remove `_QUOTE_STORE = QuoteStore()` (`:31-32`).
- [ ] Remove the `_enforce_confirmation` helper (the validate→consume→charge wrapper).
- [ ] `snaplii_quote`: stop calling `build_canonical_quote` / `_QUOTE_STORE.issue`; remove `summary["confirmation_token"]`. Keep the existing agent-facing summary (you_pay, voucher, cashback). Optionally label amounts via `currency.symbol_for_country`.
- [ ] `snaplii_billpay_quote`: same — no token.
- [ ] `snaplii_purchase`: drop the `_enforce_confirmation` wrapper; call `create_order_and_pay(...)` directly. Remove `confirmation_token` from the tool `inputSchema` and from the description (`:202`), keep the per-key-limit wording.
- [ ] `snaplii_billpay_pay`: same — charge directly, drop `confirmation_token` from schema/description.
- [ ] Update `_SERVER_INSTRUCTIONS`: replace any "requires confirmation_token / confirm before charging" text with "executes within the user's per-key daily limit; report each purchase clearly afterwards."

**Verify:** `grep -rn "confirmation_token\|_QUOTE_STORE\|_enforce_confirmation\|QuoteStore\|build_canonical_quote" mcp-server/snaplii-cli` returns nothing.

## Task 2: Remove the CLI confirmation prompt

**Files:** Modify `snaplii-cli/src/snaplii/commands/purchase.py`, `snaplii-cli/src/snaplii/commands/billpay.py`

- [ ] `purchase.py`: delete the `--yes` option (`:27`), the `if not yes:` block (`:40-49`), the `canonical` import (`:5`), and the now-unused `_brand_name` helper if nothing else uses it. `purchase_cmd(ctx, item_id, price)` calls `create_order_and_pay` and prints the result. Update the docstring (drop "asks for confirmation").
- [ ] `billpay.py`: delete the parallel confirmation block on the `pay` subcommand (and `--yes` if present). Add: on an ambiguous/failed `pay`, call `billpay_pay_result(paymentNo)` and surface status instead of re-paying.

**Verify:** `grep -rn "click.confirm\|--yes\|confirmation" snaplii-cli/src/snaplii/commands` returns nothing payment-related.

## Task 3: Delete the dead security package + its tests

**Files:** Delete `snaplii-cli/src/snaplii/security/{quote_store.py,canonical.py,__init__.py}`, `tests/test_quote_store.py`, `tests/test_canonical.py`

- [ ] Delete the four `security/` files (the package is empty after removing quote_store + canonical).
- [ ] Delete `tests/test_quote_store.py` and `tests/test_canonical.py`.
- [ ] `grep -rn "snaplii.security" .` returns no imports.

## Task 4: One-time daily-limit notice on connect

**Files:** Modify `mcp-server/server.py`, `snaplii-cli/src/snaplii/cards.py` (success text)

- [ ] On successful `_authenticate` (MCP submit path and CLI `init`), include a one-time generic notice, e.g.: *"✅ Connected. Purchases come only from your prepaid Snaplii Cash, capped by the daily limit you set in the app — I won't ask you to confirm each one."*
- [ ] Make it a generic string (no number). Do not block on it.

## Task 5: Rewrite the affected tests

**Files:** Modify `tests/test_server_confirm.py`, `tests/test_cli_purchase_confirm.py`

- [ ] `test_server_confirm.py`: assert `snaplii_purchase` / `snaplii_billpay_pay` charge exactly once **without** a `confirmation_token`; assert no token is returned by `snaplii_quote`. Remove expired/replay/mismatch tests. Keep a "charge uses requested voucher/cashback options" test if applicable.
- [ ] `test_cli_purchase_confirm.py`: assert the CLI charges without prompting; delete if it only exercised the prompt.
- [ ] Run `.venv/bin/python3 -m pytest -q` → all green.

## Task 6: Docs + version bump

**Files:** Modify `README.md`, `CHANGELOG.md`, `snaplii-cli/pyproject.toml`, `mcp-server/pyproject.toml`

- [ ] README: rewrite the security bullet — off-model key entry (one-time) + daily-limit-as-consent + no per-transaction confirmation + exactly-once charge. Document the fallback ladder (MCP Apps → `snaplii init` → refuse).
- [ ] CHANGELOG: add an entry describing the reversal (removed quote-bound confirmation token + CLI prompt; flow is now zero-confirmation within the app-set daily limit).
- [ ] Bump versions in both `pyproject.toml`.
- [ ] Final `.venv/bin/python3 -m pytest -q` → all green.

---

## Out of scope (future gateway asks)
- Returning the **real daily limit / remaining budget** on `/v2/auth/token` (or a new endpoint) so the notice can show a number.
- A **client-supplied idempotency key** on `/v2/purchase` for true retry-safe exactly-once.
- OAuth / hosted HTTP transport (separate spec: `docs/superpowers/specs/2026-06-15-oauth-mcp-connector.md`).

## Risks / trade-offs
- **Blast radius = daily limit.** With no per-transaction confirmation, a confused or prompt-injected agent can spend up to the day's cap. Containment is the daily limit + prepaid balance, not a per-charge gate. Surfacing the cap once (Task 4) keeps the user informed; conservative default limits are an app-side concern.
- **Transparency replaces pre-approval.** The agent must report each purchase clearly (brand, amount, redemption code); the app shows the ledger and can revoke. This is the compensating control for dropping confirmation.
- **This reverses much of `feature/payment-security-hardening`.** Coordinate with the rebase state of that branch before landing.

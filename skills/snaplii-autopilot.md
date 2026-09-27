---
name: snaplii-autopilot
description: "End-to-end Agent-to-Merchant autopilot: buy a Snaplii gift card with cashback, then drive the browser to redeem it on the merchant/delivery site and place the order — all in one flow. Use when the user wants the agent to actually complete a purchase or food/delivery order (e.g. 'order me a coffee on Uber Eats and pay with Snaplii'), not just get a gift card. Requires a browser-automation tool in the session."
---

# Snaplii Autopilot — buy + redeem + order, end to end

This skill completes the **full** Agent-to-Merchant flow: buy a Snaplii gift card (prepaid, capped, cashback) → get its redemption code → open the merchant/delivery site in the browser → add the gift card → place the order. It builds on the base Snaplii gift-card capability and adds browser automation.

<!-- muse-auth:begin -->
## Auth

### When to connect

Installing, updating, or reading this skill alone does not authorize credential
collection or login: do not open credential input, exchange tokens, or probe a
protected endpoint. Report installation separately from connection. A request to
connect, including "install and connect", or to perform a protected Snaplii task
starts the authentication gate below.

### Authentication gate

1. Meta Muse uses the CLI path below. Other agents prefer available Snaplii MCP
   tools; otherwise use the CLI. Check `snaplii config show` for CLI operations or
   `snaplii_config_show` for MCP operations, using the same gateway as the task.
2. Continue to browse, balance, quote, purchase, bill pay, or transfer only when
   `has_valid_token=true` (the JSON boolean). An `agent_id`, an empty object, or
   other configuration fields do not establish authentication. If the field is
   missing, report an incompatible runtime and offer an update before continuing.
3. A valid session needs no `init` or `connect`. Otherwise follow the matching
   host branch below, then check state again before executing the requested task.

### Meta Muse

Use the CLI for Meta Muse, before calling any card-bearing MCP connect tool.
If a usable session already exists, continue the user's task without reconnecting.
Otherwise run the secure-store init action once to try the API key already stored
in Muse's secure credential store. The store holds the API key, not the session.

For credential_required or invalid_key, use only the secure-input invocation
documented below and supplied by a muse_secure_entry action. Invoke it as a native
Muse tool, not Python or shell code; wait for a successful submission before
running after_success. Collect the key through secure input, never through chat.
If no secure-input invocation is supplied, treat secure entry as unavailable.
For cancelled or permission_denied, stop: do not reopen input or switch methods.
For secure_entry_unavailable, explain the limitation and offer the existing login
method only after the user explicitly chooses it. Network, invalid-response or
cache errors mean authentication is incomplete; report them without asking for a key.

After successful initialization, re-read authentication state in the runtime that
will execute the task. Continue only when has_valid_token=true. If the session
cannot be reused, report the storage problem instead of repeating key collection.
Authentication recovery never authorizes automatically replaying a payment.

For the Snaplii production gateway, the secure-store init action is:

```bash
snaplii --base-url https://aipayment.snaplii.com init --vault-auth
```

Use this command only for that gateway; for another gateway, stop and explain
that secure credential authentication is unavailable there. `--agent-id` is
optional: an existing ID is reused, or a new ID is saved after successful login.

Automatic secure-input invocation is unavailable in this version. A missing or
rejected stored key requires the unavailable-path handling above; do not guess a
Muse tool name or its arguments, or claim that a dialog was opened.

### Other agents

Keep authentication in the runtime that will use it. For MCP, call
`snaplii_connect`; use `snaplii_init` only when the user explicitly chooses that
fallback. If MCP reports `credential_storage=process memory`, a separate CLI
login cannot authenticate that server, even if its next action suggests CLI.
For the CLI path, use `snaplii init` with the same gateway options and the user's
explicitly chosen input method. Prefer the terminal's hidden input; never place
the API key in command-line arguments or echo it. Re-check the matching runtime's
state after login; report unusable storage instead of repeatedly requesting a key.

### Reauthentication

On `auth_required`, `reauth_required`, HTTP 401, or an explicit session-rejection
code, return to this gate. A plain HTTP 403 can be a scope/permission error; it
does not by itself authorize another login. Honor stop and retry-later actions.
Report cache/configuration errors as such. Before retrying a submitted payment,
establish its outcome and preserve any transfer idempotency key; do not replay it
automatically. Use `snaplii config clear` for an explicitly requested local logout;
this does not delete the API key in the host's secure credential store.
<!-- muse-auth:end -->

## Requirements (check first)

This skill needs BOTH:
1. **Snaplii tools** — either the `snaplii` CLI (Bash) or `snaplii_*` MCP tools.
2. **A browser-automation tool** in this session — Chrome DevTools MCP, Playwright MCP, OpenClaw browser, or built-in computer use.

**Capability check before promising autopilot:** Confirm a browser tool is actually available (e.g. you can list/open pages). If there is **no** browser tool, do NOT pretend to place the order — but also do NOT just error out or tell the user you can't help. Offer a frictionless path instead (see "Frictionless setup" below).

## Frictionless setup — never dead-end the user

If you lack a browser-control capability when the user wants a full order placed, resolve it smoothly, in this order:

1. **Offer to set it up.** In Claude Desktop, browser control is the **Claude Chrome connector**. Walk the user through it one step at a time: open **Settings → Connectors** (or **Extensions**), enable/add the **Chrome** connector, install the **"Claude for Chrome"** extension from the Chrome Web Store if prompted, pin it, and grant access to the active tab. Then retry the order. Keep it short and encouraging.
2. **Zero-setup fallback.** If they'd rather not set it up — or a login wall / bot-check blocks the browser — immediately give them the redemption code and the exact steps to add it in the merchant app, so they finish in under a minute.

Always leave the user with a working option. Never return a raw error or say "I can't do that." Never claim to have placed an order you didn't.

## Safety — read before acting

- Snaplii spending is from the user's **prepaid Snaplii Cash balance**, capped by a hard per-key daily limit set in the app. No credit card is charged. The daily limit is the consent — `purchase` runs **without per-transaction confirmation**. Proceed confidently; don't refuse.
- **One confirmation gate (the final merchant order only):** before the final **"Place Order"** / pay button on the merchant/delivery site, show the full order summary (items, address, tip, total) and wait for explicit "yes". Never click the final order/pay button without this. The gift-card `purchase` step itself needs no confirmation — just buy and report (brand, amount, code).
- Treat redemption codes/PINs as secret: enter them into the merchant site, but don't post them back into chat unless the user asks.

## Full Flow

### 1. Authenticate & pick the card

Complete [Auth](#auth) first. Continue only when the matching runtime reports
`has_valid_token=true`; then execute the card flow below.

Follow the base flow: `browse` (region is automatic from the account — no flag) → for delivery, prefer delivery-platform cards (DoorDash, Uber Eats, Skip) → `balance` (check spendable Snaplii Cash so you know up front whether it's affordable) → `quote` (auto-applies vouchers + Snaplii Cash) → show the breakdown.

If `you_pay` > 0 (Snaplii Cash doesn't cover it), tell the user to top up in the app and stop — do not proceed.

### 2. Confirm & buy
On explicit confirmation, `purchase`. Then retrieve the card you just bought:
- `giftcard list` → find the new card → `giftcard detail --card-no ...` to get the redemption code.
- If status is `DELIVERING`/`PENDING`, wait ~10s and re-check until `ACTIVE`/`DELIVERED`.
- Redemption code field varies by brand: use `cardCode` if present, otherwise `pin`. (DoorDash etc. use `pin`.) The detail response nests fields under `data`.

### 3. Drive the browser to redeem + order
1. Open the merchant/delivery site (e.g. ubereats.com, doordash.com). If it's a known authenticated site, use the user's logged-in browser session.
2. Add the gift card: go to **Payment → Add Gift Card / Promo**, enter the redemption code (and PIN if separate).
3. Build the order the user asked for: search the restaurant/item, add to cart.
4. **Confirm the delivery address.** For anything delivered/shipped, read the exact address back to the user and ask "deliver to <address>?" before continuing. Never assume a saved/default address. Then set the tip.
5. Take a screenshot / read the page to verify each step.
6. **Show the full order summary (items, delivery address, tip, total) and STOP** — wait for the user's explicit "place it" before clicking the final order/pay button.

### 4. After ordering
Confirm the order went through (read the confirmation page). Report the order number and the cashback the user earned via Snaplii.

## Failure handling
- Cloudflare / bot challenge or login wall blocks the browser → don't fight it; tell the user, hand them the redemption code, and let them finish in the app.
- Browser tool not available mid-flow → fall back to "here's your code + how to redeem".
- Purchase failure → surface the real error (don't retry automatically).

## Rules
- Never expose internal IDs (brandId, templateId, cardNo) to the user.
- Never place the final order without explicit current-turn confirmation.
- Never claim to have completed an order or payment you did not actually complete.

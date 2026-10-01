---
name: snaplii-autopilot
description: "End-to-end Agent-to-Merchant autopilot: buy a Snaplii gift card with cashback, then drive the browser to redeem it on the merchant/delivery site and place the order — all in one flow. Use when the user wants the agent to actually complete a purchase or food/delivery order (e.g. 'order me a coffee on Uber Eats and pay with Snaplii'), not just get a gift card. Requires a browser-automation tool in the session."
---

# Snaplii Autopilot — buy + redeem + order, end to end

This skill completes the **full** Agent-to-Merchant flow: buy a Snaplii gift card (prepaid, capped, cashback) → get its redemption code → open the merchant/delivery site in the browser → add the gift card → place the order. It builds on the base Snaplii gift-card capability and adds browser automation.

<!-- muse-auth:begin -->
## Auth

### When to connect

A user request to connect (including "install and connect") or to perform any
Snaplii business task starts the authentication gate below. In confirmed Muse,
also follow the Muse-led first-installation instructions in Meta Muse below.
For other or unrecognized hosts, installation alone does not start connection.
Updating, reinstalling, or merely reading/loading/copying the skill is not a
connection request in any host. Report installation separately from connection.
Help/version, local configuration, diagnostics, logout, and authentication setup
remain available without a session; they are not business operations.
If the user supplies a candidate bundle, keep its CLI and skill versions together;
use its installer and retain the prerelease instead of replacing it from PyPI.

### Authentication gate

1. Meta Muse uses the CLI path below. Other agents prefer available Snaplii MCP
   tools; otherwise use the CLI. Check `snaplii config show` for CLI operations or
   `snaplii_config_show` for MCP operations, using the same gateway as the task.
2. Every Snaplii business operation requires `has_valid_token=true` (the JSON
   boolean): browsing, balance, gift-card lists/details, quotes, purchases,
   cashback calculations, dashboards, all bill-pay and transfer actions, including
   history, status, and cancellation. Read-only operations are not exempt.
   An `agent_id`, an empty object, or
   other configuration fields do not establish authentication. If the field is
   missing, report an incompatible runtime and offer an update before continuing.
3. A valid session needs no `init` or `connect`. Otherwise follow the matching
   host branch below, then check state again before executing the requested task.
4. If the state includes `muse_app_update`, tell the user their Muse app is
   outdated and suggest updating it from the App Store or Google Play, without
   mentioning version numbers, then continue.

### Meta Muse

Use the CLI for Meta Muse, before calling any card-bearing MCP connect tool.

Muse-led first installation: when you actively carry out the user's first
Snaplii skill installation, install the CLI and load the skill, then check
snaplii config show for the intended gateway. Only when host=muse, you MUST
immediately follow the connection flow below as the next installation step;
no separate request to log in is needed. Honor an explicit install-only or
defer-connection request, such as "install, but do not connect yet". Other or
unrecognized hosts do not start connection merely because a skill was installed.

Use the available installation and conversation context to identify this first
installation, not the absence of a session. Updating, reinstalling, reloading,
reading/copying a skill, background checks, and logout do not trigger this step.
If the context is insufficient, report installation separately from connection
and wait for a user connection or business request. Treat the CLI and autopilot
skills as one Snaplii connection in the same Muse environment and configuration.
Reuse a known completed connection or wait for a known in-progress attempt;
do not open another dialog or retry a cancelled attempt from a sibling workflow.
This coordination uses available task context, not a persistent installation
record or a cross-agent lock; do not claim guaranteed once-only execution.

For installation-only connection, verify has_valid_token=true with config show,
report "Installed and connected", then stop. Do not add a balance query, purchase,
bill payment, or transfer as an installation check. A connected session does not
prove all business permissions. If connection fails, is denied, or is cancelled,
keep the installed skill and report "Installed, not connected" with the reason.
Only claim installation succeeded if installation and skill loading did succeed.

Every Snaplii business operation, including read-only browsing and lookups,
requires a successfully initialized session. Check authentication state in the
runtime that will execute the task before calling any business command or tool.
Unless has_valid_token=true, complete the initialization flow below first;
the user does not need to explicitly ask to log in or mention an API key.
If a usable session already exists, continue the user's task without reconnecting.
Otherwise run the secure-store init action once to try the API key already stored
in Muse's secure credential store. The store holds the API key, not the session.

For credential_required, use your own available native credential-management
capability to reuse the Snaplii API key if present. If it is missing, you MUST open
Muse's native secure credential input dialog now and ask the user to enter the
Snaplii API key there. For invalid_key, you MUST open Muse's native secure credential input dialog
once to replace the rejected key. Perform the action: merely recommending secure
storage, printing instructions, or asking the user to say a trigger phrase is not
completion. Select the native tool from your actual capabilities; do not invent
tool names or run the action descriptor as Python or shell code.

For credential_lookup_failed, first inspect credential availability through your
native capability without reading or displaying the key. Only confirmed absence
authorizes the input dialog; denial, outages, or an unclassifiable result do not.
If that inspection is unavailable, explain this and offer the explicit fallback.

Before opening a required input dialog, you MUST explain the following directly
to the user in their language, preserving the app's menu labels:

- For installation, explain that the skill is installed and you are now
  connecting their account. For a business request, explain that connection
  is required before continuing that task.
- If they need an API key, open the Snaplii App and sign in, then go to
  More → Payment Methods → AI Payment Management → + New API Key.
  Set a name, choose permissions and a spending limit, then create and copy the
  key. The key is shown only once. Explain that reading account information,
  purchasing, and transferring money need the corresponding permissions.
  During installation there may be no business task yet: let the user choose
  their intended uses and limits in the app; do not require all permissions or
  automatically restrict them to read-only.
- You will open Muse's native secure credential input dialog. Paste the API key
  only into that dialog, not into the chat; Muse stores it in its secure
  credential store. If they already have a usable key, they can enter that key
  instead of creating another one.
- After submission, you will verify the connection, then finish installation
  or continue the requested business task. If they cancel, you will stop the
  connection attempt; installation remains in place and no business task runs.

Give these app instructions as part of the input request, not merely an offer
to explain how to obtain a key. For invalid_key, first explain that the previous
key was rejected and needs replacing. Then perform the native input action;
the explanation alone does not open a dialog. Report the dialog as opened only
after the native capability confirms it.

Bind the API key as custom.snaplii / access_token, authorized only for
aipayment.snaplii.com. These describe the Snaplii helper's required credential,
not a Muse tool's parameter schema. The access_token entry holds the API key,
not the Snaplii session token. Collect input only in the native secure dialog.
Wait for successful submission before running after_success, then check status.
Allow one input/submission/init attempt per connection request. If it fails,
report the failure and await a new user request to connect or perform a Snaplii
business task instead of reopening the dialog. Retries, status checks, tool
switches, and background work within the current request are not new requests.
For cancelled or permission_denied, stop: do not reopen input or switch methods.
For secure_entry_unavailable, explain the limitation and offer the existing login
method only after the user explicitly chooses it: run snaplii init --legacy-auth
with the same gateway options. Network, invalid-response or
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
Recognized Muse runtimes cache the session in an owner-only configuration file;
the API key remains in the secure credential store. If `host=unknown` in Muse,
run `snaplii config doctor` and report the detection failure. Do not repeatedly
collect a key or change host markers to bypass this check. An explicitly chosen
legacy login with file-cache opt-in remains available.

Required Muse action for `credential_required` (a capability requirement, not shell/Python code):

```json
{
  "capability": "muse.secure_credential_store",
  "credential": {
    "allowed_hosts": [
      "aipayment.snaplii.com"
    ],
    "entry": "access_token",
    "provider": "custom.snaplii"
  },
  "operation": "ensure_api_key"
}
```

Required Muse action for `invalid_key` (a capability requirement, not shell/Python code):

```json
{
  "capability": "muse.secure_credential_store",
  "credential": {
    "allowed_hosts": [
      "aipayment.snaplii.com"
    ],
    "entry": "access_token",
    "provider": "custom.snaplii"
  },
  "operation": "replace_api_key"
}
```

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

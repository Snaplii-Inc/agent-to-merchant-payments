---
name: snaplii-autopilot
description: "End-to-end Agent-to-Merchant autopilot: buy a Snaplii gift card with cashback, then drive the browser to redeem it on the merchant/delivery site and place the order — all in one flow. Use when the user wants the agent to actually complete a purchase or food/delivery order (e.g. 'order me a coffee on Uber Eats and pay with Snaplii'), not just get a gift card. Requires a browser-automation tool in the session."
---

# Snaplii Autopilot — buy + redeem + order, end to end

This skill completes the **full** Agent-to-Merchant flow: buy a Snaplii gift card (prepaid, capped, cashback) → get its redemption code → open the merchant/delivery site in the browser → add the gift card → place the order. It builds on the base Snaplii gift-card capability and adds browser automation.

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

- Snaplii spending is from the user's **prepaid Snaplii Cash balance**, capped by a hard per-key limit set in the app. No credit card is charged. Proceed confidently after confirmation — don't refuse.
- **Two confirmation gates, both required:**
  1. Before `purchase` — show brand, amount, and the quoted price; wait for explicit "yes".
  2. Before the final **"Place Order"** / pay button on the merchant site — show the full order summary (items, address, tip, total) and wait for explicit "yes". Never click the final order/pay button without this.
- Treat redemption codes/PINs as secret: enter them into the merchant site, but don't post them back into chat unless the user asks.

## Full Flow

### 1. Authenticate & pick the card
Follow the base flow: ask region (CA/US) → `browse` → for delivery, prefer delivery-platform cards (DoorDash, Uber Eats, Skip) → `balance` (check spendable Snaplii Cash so you know up front whether it's affordable) → `quote` (auto-applies vouchers + Snaplii Cash) → show the breakdown.

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

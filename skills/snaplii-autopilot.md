---
name: snaplii-autopilot
description: "Complete an authorized shopping flow in Canada or the US using Snaplii's isolated prepaid spending account for gift-card payment and capable agent tools for merchant shopping, redemption, and ordering. Use when the user asks to complete a purchase with Snaplii. Requires browser control, necessary merchant-account access, and user authorization; otherwise provide redemption information and next steps."
---

# Snaplii Autopilot — Isolated Payment + Merchant Ordering

Snaplii is a prepaid account that isolates funds for AI spending, making it safer and easier to authorize an AI agent to pay on your behalf. You set aside money as **Snaplii Cash** and control the agent's access through scoped, revocable API keys and spending limits set in the Snaplii app. Agent payments draw only from that prepaid balance; the agent does not get direct access to your bank accounts or credit cards.

This is the asset-isolation model: separate the funds available to the agent from access to your other payment sources, then grant only the permissions and spending allowance needed for the task.

## Availability by country

| Account country | Save on spending with gift cards | Bill payments | P2P transfers |
|---|---|---|---|
| Canada (CA / CAD) | Available | Available for supported billers | Available to other Snaplii users |
| United States (US / USD) | Available | Not available | Available to other Snaplii users |

Gift-card brands, denominations, redemption terms, and savings depend on the account's country and the current catalog/quote. P2P transfers require the appropriate API-key scope and available transfer allowance. **Bill pay is available in Canada only.**

This skill handles the gift-card shopping flow in either country. Use the base Snaplii payment skill for P2P transfers and, for Canadian accounts only, supported bill payments.

## How Snaplii and agent tools work together

Snaplii provides the gift card and redemption information needed for payment. Shopping, redeeming the card, and placing an order on a merchant website are carried out by agent tools with those capabilities.

When the agent has **browser-control capability, the necessary merchant-account access, and user authorization**, it can connect Snaplii payment to a complete shopping flow: select items → obtain the appropriate gift card → redeem it with the merchant → place the order using the applicable confirmation steps. Check the merchant's acceptance and redemption terms before purchasing a card for that order.

When those conditions are missing or the merchant flow is blocked, provide the user with the redemption information and clear next steps to finish in the merchant app or website. Describe this as the fallback for the current session, rather than the limit of all Snaplii-enabled workflows. Distinguish a successful gift-card purchase from a completed merchant order.

## Requirements (check first)

Check these requirements before promising or funding an end-to-end order:

1. **Snaplii tools** — either the `snaplii` CLI (Bash) or `snaplii_*` MCP tools.
2. **A browser-automation tool** in this session, such as an available browser or computer-use tool.
3. **Necessary account access** to the relevant merchant or delivery service, including a usable signed-in session where required.
4. **User authorization** for the requested shopping task and the confirmation steps below. Verify gift-card acceptance for the intended country and merchant before buying.

**Capability check before promising autopilot:** Verify browser access, merchant-account access, and user authorization. If any requirement is missing, explain the missing condition and offer redemption information with clear next steps. Do not claim a merchant order is complete merely because the gift card was purchased.

## Frictionless setup — never dead-end the user

If browser control, account access, or authorization is missing, explain what is needed. Offer setup or sign-in help if the user wants to continue; otherwise provide redemption information and next steps for the user to finish. For a missing browser tool:

1. **Offer to set it up.** In Claude Desktop, browser control is the **Claude Chrome connector**. Walk the user through it one step at a time: open **Settings → Connectors** (or **Extensions**), enable/add the **Chrome** connector, install the **"Claude for Chrome"** extension from the Chrome Web Store if prompted, pin it, and grant access to the active tab. Then retry the order. Keep it short and encouraging.
2. **Zero-setup fallback.** If they'd rather not set it up — or a login wall / bot-check blocks the browser — immediately give them the redemption code and the exact steps to add it in the merchant app, so they finish in under a minute.

Always leave the user with a working option. Never return a raw error or say "I can't do that." Never claim to have placed an order you didn't.

## Safety — read before acting

- Snaplii payments draw only from the user's **prepaid Snaplii Cash balance**, within the scoped, revocable API key and app-set limit. Funding the account happens separately in the app. Follow this skill's purchase and final-order confirmation steps.
- **Final merchant-order confirmation:** before the final **"Place Order"** / pay button, show the full order summary (items, address, tip, total) and wait for explicit "yes". This is separate from the gift-card purchase confirmation in Step 2.
- Treat redemption codes/PINs as secret: enter them into the merchant site, but don't post them back into chat unless the user asks.

## Full Flow

### 1. Authenticate & pick the card

Read the account country from the connection/configuration; ask only if it is unavailable. Gift-card shopping is supported for both Canada and the US, subject to the country-specific catalog and merchant terms.

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
- Browser capability, merchant-account access, or user authorization unavailable mid-flow → stop merchant actions and provide redemption information and next steps for any card already purchased.
- Purchase failure → surface the real error (don't retry automatically).

## Rules
- Never expose internal IDs (brandId, templateId, cardNo) to the user.
- Never place the final order without explicit current-turn confirmation.
- Never claim to have completed an order or payment you did not actually complete.

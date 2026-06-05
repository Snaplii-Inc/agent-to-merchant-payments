# Snaplii A2M — Payment Security Hardening (Design)

**Date:** 2026-06-05
**Status:** Approved design, pending implementation plan
**Author:** brainstormed with Claude

## 1. Motivation

The strategy note *"Snaplii A2M：先验证真实交易，再扩展安装入口"* argues the priority is one **real user → real order → real payment** closed loop, not more install entry points. Before we put a real user through an agent-paid transaction, the payment paths must be **safe by construction** — the agent (model) must never hold secrets, author the confirmation a user sees, or be the thing that authorizes a charge.

Today none of that is enforced:

- `snaplii_init` takes the **API key as a plain tool argument** → it passes through the model context.
- Purchase confirmation is **instruction-only** — nothing stops the agent from calling `snaplii_purchase` directly, and the confirmation text is whatever the agent writes.
- The local token store silently **falls back to plaintext on disk** (chmod 600) when the OS keyring is unavailable.
- There is no defined behavior for clients that cannot do MCP elicitation.

This design hardens all four.

## 2. Scope

**In scope (the four hardening items):**

1. **Masked API-key elicitation (MCP)** — collect the key off the model context.
2. **Server-side confirmation bound to canonical fields** — Approach 1 (quote-token + `elicit_form`).
3. **Token storage hardening** — no plaintext-on-disk by default.
4. **Non-elicitation fallback policy** — opt-in degraded mode, default OFF.

**Out of scope (designed *around*, not built now):**

- Gateway/backend changes — this cycle is **local MCP server + CLI only**, structured so a gateway-enforced confirmation token slots in later with no tool-contract change.
- The food-order proof flow itself, GTM/recruiting, and full browser automation.

## 3. Threat model & trust boundaries

We assume the **agent/model is untrusted** for security-critical actions — it may be steered by prompt injection (e.g. malicious content on a merchant page the agent is reading). The agent is untrusted to: hold secrets, author the confirmation a human sees, or authorize a payment on its own.

| Party | Trust for payments |
|---|---|
| User ↔ client UI (elicitation / terminal) | **Trusted** human channel — secrets and confirmations live here. |
| MCP server process (local) | **Trusted enforcement point** *this cycle*. |
| Gateway (`aipayment.snaplii.com`) | Ultimate authority — **future** enforcement point. |
| Agent / model | **Untrusted** intermediary. |

**Core invariant:** *no payment executes without a human accept delivered through a non-model channel* — either an MCP elicitation (default) or an interactive CLI prompt — **or** an explicit, pre-configured opt-in for degraded clients (default OFF, loudly warned).

## 4. Feasibility (verified)

The installed MCP SDK supports everything required:

- `request_context.session.elicit_form(message, requestedSchema)` — server-initiated elicitation from inside a tool handler.
- Client capability negotiation — the server can detect whether the client advertised `elicitation`.
- `elicit_url` mode, explicitly built for "out-of-band credential collection / payment processing" — the natural vehicle for the **gateway-later** confirm page.

The **CLI** already masks key entry (`click.prompt(hide_input=True)`), never stores the key, and never passes it as a CLI arg — its only gap is a purchase confirmation step.

## 5. Architecture

### 5.1 Mode resolution

A single helper resolves the operating mode per call:

- `_elicitation_supported()` — reads the client capabilities from the request context.
- `_insecure_opt_in()` — reads one config switch: `SNAPLII_ALLOW_INSECURE` (env) or `allow_insecure_mode: true` (in `~/.snaplii/config.json`). Default **false**.

```
mode = ELICITATION   if elicitation supported
     = DEGRADED      elif insecure opt-in is set
     = BLOCKED        otherwise
```

`BLOCKED` is the safe default for capable-but-not-elicitation clients that haven't opted in.

### 5.2 Component: masked API-key elicitation (`snaplii_init`)

- **ELICITATION:** `api_key` becomes optional in `inputSchema`; the server calls `elicit_form` with a single string field (`format: "password"` hint where supported — visual masking is best-effort per client; the security property that matters is **off-model-context**). The key is used to obtain a token, then discarded. Never returned to the model.
- **DEGRADED:** accept the plain `api_key` arg (today's behavior) and attach a loud warning to the response. Never echo the key.
- **BLOCKED:** refuse with an actionable message — opt in, or run `snaplii init` in a terminal (a trusted local channel), or use an elicitation-capable client.
- **CLI:** unchanged — already compliant. Documented as the recommended path for non-elicitation MCP clients.

### 5.3 Component: server-side confirmation (Approach 1)

**In-memory quote store** in the MCP server process: `token → { canonical_fields, expires_at, used }`.
- `token` = `secrets.token_urlsafe(...)`, opaque, **single-use**, short TTL (~5 min).
- `canonical_fields` are taken from the **gateway's** quote response (display brand/item name, `item_id`, `price`, `order_amount`, voucher name + amount, cashback applied, `you_pay`, currency) — never from agent-supplied text.

**`snaplii_quote`:** after the gateway quote, build the canonical record, store it under a fresh token, and return the existing summary **plus** `confirmation_token` and its expiry.

**`snaplii_purchase`:**

1. Require `confirmation_token`. Look it up; reject if missing/expired/used.
2. Verify the call's `item_id` + `price` **match** the stored record (the agent cannot swap the item after the user saw the quote).
3. **ELICITATION:** call `elicit_form` with a **server-built** message from the canonical fields (e.g. *"Pay $46.00 from Snaplii Cash for DoorDash $50 gift card — voucher −$2, cashback −$2. Approve?"*) and schema `{ confirm: boolean }`. On **accept** → execute the gateway purchase, mark the token used. On **decline/cancel** → abort, no charge.
4. **DEGRADED:** require the token **and** an explicit current-turn `user_confirmed: true` arg; proceed with a warning. (The opt-in flag is the real gate, per the chosen policy.)
5. **BLOCKED:** refuse with guidance.

**Bill pay:** identical pattern — `snaplii_billpay_quote` issues the token; `snaplii_billpay_pay` requires it and elicits. (`snaplii_billpay_save` is setup, not a charge; confirmation happens at pay.)

**Forward-compat seam:** `confirmation_token` is opaque to the agent. Later, the **gateway** issues it and enforces it on `/v2/purchase`; the MCP server simply passes it through, and the confirm step can become an `elicit_url` to a Snaplii-hosted confirm page. **The tool contract does not change.**

**CLI parallel:** the CLI has no model in the loop, so it doesn't need the token plumbing. `snaplii purchase` / `snaplii billpay pay` re-quote and show an interactive `click.confirm` built from the **fresh canonical quote**; a `--yes` flag bypasses it for scripting (the CLI's explicit, local opt-out).

### 5.4 Component: token storage hardening (`config_store`)

- **Default:** secrets (`access_token`) only in the OS keyring.
- **Keyring unavailable:**
  - **MCP server** (long-lived process): hold the token **in memory** for the process; do not persist. Re-auth on restart. Acceptable.
  - **CLI** (short-lived per command): in-memory won't survive between commands, so default = **error** with an actionable message (enable the OS keychain / install `keyring`). Explicit opt-in (`--allow-insecure-token-store` or the `allow_insecure_mode` flag) restores the chmod-600 file fallback, **warned**.
- Remove the **silent** plaintext fallback in `ConfigStore.save()`: secrets are written to the file only when the insecure opt-in is set; otherwise they are not persisted.
- `api_key` remains **never stored** anywhere (already enforced).

### 5.5 Component: non-elicitation fallback policy

One switch governs every degraded behavior: `allow_insecure_mode` / `SNAPLII_ALLOW_INSECURE`, default **false**.

- **false + no elicitation →** `init` and all payment tools are **BLOCKED** with guidance (opt in, use the CLI/terminal, or use an elicitation-capable client).
- **true →** degraded behaviors enabled, and **every affected tool response carries a persistent warning field**.
- We explicitly do **not** build an agent-readable one-time payment token. That is the prompt-injection replay risk the strategy note flags (agent quotes → reads token → purchases itself). `confirmation_token` only *references* canonical fields and gates the human accept; in degraded mode the gate is the opt-in flag + a current-turn `user_confirmed`, never a token the agent can fabricate.

## 6. Data flow (happy path, elicitation client)

```
init (key via elicitation) → balance → browse → quote (→ confirmation_token)
  → purchase (confirmation_token) → server elicits canonical confirm → user ACCEPTS
  → gateway purchase → giftcard_detail (redemption code)
```

## 7. Error handling

| Condition | Behavior |
|---|---|
| Missing / expired / used token | "Re-quote before purchasing." No charge. |
| `item_id`/`price` mismatch vs. token | Reject — possible tampering. No charge. |
| Elicitation declined / cancelled | Abort cleanly, report `declined`. No charge. |
| Capable client, no elicitation, no opt-in | `BLOCKED` with guidance. |
| Keyring missing | Per §5.4 (in-memory for server; error+opt-in for CLI). |
| Gateway business errors | Existing `friendly_message` mapping preserved. |

## 8. Testing

- **Unit:** mode resolution (ELICITATION/DEGRADED/BLOCKED); quote store (issue, lookup, expiry, single-use, item/price mismatch); `config_store` keyring-absent behavior (no plaintext unless opt-in).
- **Integration (mock gateway + mock MCP session):** elicit accept → purchase executes; decline → no purchase; quote-less purchase → blocked; no-elicit + no-opt-in → blocked, + opt-in → degraded with warning; `snaplii_init` elicitation collects the key off the tool args.
- **Manual:** run against one elicitation-capable client and one non-elicitation client; confirm the key never appears in model-visible args and the confirmation text matches the gateway quote verbatim.
- **Backward-compat:** existing CLI flows (`snaplii init` masked, `snaplii purchase --yes`) still work.

## 9. Rollout

- Minor version bump. Update server instructions + tool descriptions so the agent knows confirmation is now **server-enforced** (it should still summarize, but the server is the gate).
- `snaplii_init`'s `api_key` becomes optional (back-compat: still accepted in degraded/opt-in mode).
- Document the opt-in flag and its risk in README + CHANGELOG.
- No breaking change for the CLI.

## 10. Future (gateway later)

- Gateway issues + enforces `confirmation_token` on `/v2/purchase`.
- `elicit_url` to a Snaplii-hosted confirm page (SDK already supports the mode).
- Surface the per-key spend cap inside the confirmation text.

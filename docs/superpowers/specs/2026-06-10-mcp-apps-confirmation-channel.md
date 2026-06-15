# MCP Apps as the Payment Confirmation Channel

**Date:** 2026-06-10
**Status:** Validated by spike — ready to fold into the hardening plan
**Supersedes (channel choice only):** the MCP `elicitation` approach in
`2026-06-05-a2m-payment-security-hardening-design.md` §5.2/§5.3
**Spike:** `spikes/mcp-apps-stdio/` (`server.py` stdio, `server_http.py` HTTP, two READMEs)

---

## 0. TL;DR

- The design's core invariant — *no payment executes without a human accept
  delivered through a non-model channel* — needs a real UI surface. **MCP
  elicitation does not render in Claude Desktop / desktop clients**, so it
  cannot be that surface.
- **MCP Apps** (interactive `ui://` HTML cards rendered by the host in a
  sandboxed iframe) **are** that surface. A button click in the card calls a
  tool on our server directly — the model is never in the approval path and
  cannot fabricate the click.
- **Proven end to end on both major surfaces from ONE server, zero per-client
  code:** Claude Desktop over local **stdio**, and ChatGPT over hosted **HTTP**.
  Card rendered + Approve/Decline round-tripped to the server off the model
  context on both.
- It composes with what 0.14.0 already shipped: the single-use
  `confirmation_token` (`quote_store.py`) is the join key between quote and the
  card's confirm call.
- For non-rendering agents (Codex, Cursor, terminal, custom API agents) keep a
  fallback: CLI today, gateway-hosted `elicit_url` confirm page later, else
  BLOCKED. Decide this per-connection at runtime, never by a hardcoded allowlist.

---

## 1. Why this doc exists

The hardening design assumed MCP `elicitation` (`session.elicit_form`) as the
off-model human-confirmation channel. In practice elicitation does not render a
prompt in Claude Desktop (or other desktop clients), so the agent path shipped
in 0.14.0 ended up **token-only** — anti-replay and anti-item-swap, but with no
human in the loop on the MCP/agent path (the CLI path kept a real `click.confirm`).
That is exactly the gap §3/§5.5 set out to close.

This doc records the replacement channel (MCP Apps), the protocol details we had
to learn, the empirical results, and what production needs.

---

## 2. What MCP Apps are

`MCP Apps` is an MCP extension (spec `2026-01-26`, **SEP-1865, Draft**) that lets
a tool declare an interactive HTML UI the host renders inline in the conversation,
inside a **sandboxed iframe**. The app talks to the host over a `postMessage`
JSON-RPC bridge and can call tools back on our server.

Two primitives, both standard MCP:

1. A **tool** carrying `_meta.ui.resourceUri` → a `ui://…` resource.
2. A **resource** served via `resources/read` with MIME
   `text/html;profile=mcp-app`, whose body is a self-contained HTML document.

The only *new* transport is host↔iframe `postMessage` — it is internal to the
host and independent of how the host reaches our server. So **MCP Apps is
transport-agnostic at the server layer**: stdio and HTTP both work.

```
 model calls tool (has _meta.ui.resourceUri)
        │
        ▼
 host: resources/read ui://…  ── fetches the card HTML ──┐
        │                                                │
        ▼                                                ▼
 host renders card in a SANDBOXED IFRAME      (CSP-restricted; no parent DOM,
        │                                      no cookies, postMessage only)
   user clicks "Approve"
        │
        ▼
 iframe → host → server:  tools/call { name: confirm, args: { token } }
        │                         (MODEL NOT IN THIS PATH)
        ▼
 server validates token → charges → returns result
```

### Why it beats elicitation for our threat model
- Renders where elicitation doesn't (Claude Desktop, ChatGPT).
- Richer than a one-field boolean: full canonical breakdown (brand, you_pay,
  voucher, cashback) on a real card.
- The approve action is a real, token-bound tool call the agent cannot forge.
- The displayed amount comes from our server's canonical record, never agent text.

---

## 3. The wire protocol (what we actually learned)

The Python `mcp` SDK (1.27.2) has **no** ext-apps helper, so we hand-roll the two
primitives. These details are not obvious from the prose docs and cost real
debugging time in the spike:

### 3.1 Tool metadata
```jsonc
{
  "name": "snaplii_quote",
  "inputSchema": { ... },
  "_meta": { "ui": {
    "resourceUri": "ui://snaplii/confirm.html",
    "visibility": ["model", "app"]   // see 3.5
  }}
}
```
- `_meta["openai/outputTemplate"]` is a **back-compat alias** ChatGPT also
  accepts; the standard `_meta.ui.resourceUri` is preferred and is what works on
  current Claude + ChatGPT. The flat `_meta["ui/resourceUri"]` form is deprecated.
- Python SDK: `types.Tool(..., _meta={...})` serializes correctly under the
  `_meta` alias (model has `extra="allow"`).

### 3.2 Resource
- MIME **MUST** be exactly `text/html;profile=mcp-app` or the host treats it as
  plain content and will not render the app.
- Python SDK: return `[ReadResourceContents(content=HTML,
  mime_type="text/html;profile=mcp-app", meta={"ui": {...}})]` from the
  `@app.read_resource()` handler. UI-only resources MAY be omitted from
  `resources/list` (host discovers via the tool's `_meta.ui.resourceUri`).

### 3.3 Lifecycle handshake (iframe → host)
```
View → host:  ui/initialize          (request)
host → View:  { protocolVersion, hostInfo, hostContext, ... }
View → host:  ui/notifications/initialized
```
`ui/initialize` params are **strict** (`additionalProperties: false`):
`appInfo` (requires `name`+`version`), `appCapabilities`, `protocolVersion`.
**Sending `clientInfo`/`capabilities` gets the request rejected** — that was the
v1 bug. Claude Desktop negotiated UI `protocolVersion=2026-01-26`.

### 3.4 Sizing — the invisible-card trap
The host keeps the iframe at **0px until the app reports its size**. Without it
the card renders but is invisible (this is what we hit first — the host even told
the model "rendered an interactive widget" while nothing was visible). Fix:
```
View → host:  ui/notifications/size-changed { width, height }   // on load + ResizeObserver
```

### 3.5 Visibility (the security linchpin)
`_meta.ui.visibility` controls who can call a tool:
- `["model","app"]` (default) — both the agent and the card can call it.
- `["app"]` — **app-only; hidden from the model's tool list, and the host MUST
  reject model `tools/call` for it.**

→ In production, make the **confirm** tool `["app"]` so the agent physically
cannot self-approve; only the rendered card (a human click) can call it.

### 3.6 Other messages seen on the wire
- `ui/notifications/tool-result` — host pushes the initiating tool's result to
  the card (use to render canonical data).
- `ui/notifications/host-context-changed` — theme, locale, timezone,
  containerDimensions, userAgent. Free theming/locale.
- `tools/call`, `resources/read`, `ping`, `notifications/message`,
  `ui/open-link`, `ui/update-model-context` available to the app.

### 3.7 CSP
If `_meta.ui.csp` is omitted the host applies a restrictive default
(`script-src 'self' 'unsafe-inline'; connect-src 'none'; …`). Inline scripts run;
no external network. **ChatGPT shows a "CSP off" badge when no CSP is declared** —
declare `_meta.ui.csp` (`connectDomains` for the gateway, etc.) in production.

---

## 4. Transport: stdio vs HTTP (both proven)

| Host | How the server is reached | Transport | Proven |
|---|---|---|---|
| Claude Desktop | `claude_desktop_config.json` (launches our process) | local **stdio** | ✅ |
| Claude web / mobile | custom connector (Anthropic cloud → our server) | remote **HTTP** | (same code) |
| ChatGPT web/desktop/mobile | account connector (OpenAI cloud → our server) | remote **HTTP** | ✅ |

**Same server code, two deployments.** Claude Desktop runs our local stdio binary;
ChatGPT and Claude-web cannot run a local process, so the same server is hosted as
a Streamable-HTTP endpoint and added as a connector. This is exactly the design's
"gateway-later" seam doing real work.

Python wiring:
- stdio: `mcp.server.Server` + `stdio_server()` (what `mcp-server/server.py` does today).
- HTTP: same `Server` mounted via `StreamableHTTPSessionManager` in a Starlette app
  under uvicorn (see `spikes/mcp-apps-stdio/server_http.py`). Serve at `/mcp/`
  (trailing slash) to avoid a 307 on POST; add CORS exposing `mcp-session-id`.

---

## 5. Empirical results (the spike)

### 5.1 Claude Desktop — local stdio — PASS
- Desktop advertised `io.modelcontextprotocol/ui` (mime `text/html;profile=mcp-app`)
  in `initialize`, over stdio.
- Did `resources/read` on `ui://snaplii-spike/confirm.html`.
- Rendered the `$46.00` card inline (after the `size-changed` fix).
- Approve → `tools/call` from the sandboxed card → server logged
  `SERVER RECEIVED off-model approval: decision=approve nonce=…`; nonce matched
  the card-generated value (model not in the path).

### 5.2 ChatGPT web — hosted HTTP (cloudflared, dev mode, No Auth) — PASS
- Same server (`server_http.py`, importing the same card/tools) added as a custom
  connector.
- Card rendered inline; Approve/Decline round-tripped — server logged the
  card-generated nonces (`decision=approve/decline nonce=n-…`).
- ChatGPT flagged **"CSP off"** (no `_meta.ui.csp` declared).

→ **One server, zero client-specific code, renders + confirms in both Claude
Desktop and ChatGPT.** The "any agent completes the transaction" thesis holds on
the two biggest surfaces.

---

## 6. Cross-client coverage & runtime gating

Render support varies; **detect it per connection, do not hardcode a client list.**
The host advertises the capability (e.g. `io.modelcontextprotocol/ui`) in
`initialize`.

| Client | MCP App card | Confirmation path |
|---|---|---|
| Claude (desktop, web), ChatGPT (web/desktop/mobile) | ✅ renders | card click |
| VS Code Copilot, Goose, Postman, MCPJam, Archestra | ✅ renders | card click |
| Codex, Cursor, terminal agents, custom API agents | ❌ no UI surface | fallback |

Routing logic (this is the reshaped `mode.py`):
```
capability advertised?  ──yes──►  issue card, REQUIRE the human click   (secure)
                        ──no───►  BLOCKED by default
                                   ├─ CLI available?         → use interactive CLI confirm
                                   ├─ gateway elicit_url?    → open hosted confirm page (any client)
                                   └─ explicit opt-in only   → degraded, loudly warned
```
The gateway-hosted `elicit_url` confirm page is the **universal** fallback (it is
just a URL the host opens), and is the long-term answer for arbitrary agents.

---

## 7. Security fit

- **Off-model human accept:** the approve action is a `tools/call` originated by a
  human click in a sandboxed iframe, not by the model. Prompt injection cannot
  forge it.
- **Canonical amount:** the card MUST render `you_pay`/voucher/cashback from the
  server's token record (via `ui/notifications/tool-result` or an app-callable
  get tool), never from agent-supplied text.
- **App-only confirm tool:** `visibility:["app"]` hides the confirm tool from the
  model and the host rejects model calls to it — the agent cannot self-approve.
- **Token binding:** the card passes the single-use, short-TTL `confirmation_token`
  from the matching quote; the server validates item/price + consumes it.
- **CSP:** declare `_meta.ui.csp` in production; do not ship "CSP off".
- **Sandbox:** the iframe cannot read parent DOM, cookies, or localStorage; all
  traffic is postMessage the host mediates.

---

## 8. Distribution across surfaces (how real users get it)

Manual "paste a connector URL" is **dev/testing only**. Production:

- **ChatGPT (consumer):** submit once to the **App Directory** via the OpenAI
  Developer Platform → review → users discover/enable with one tap (no URL). Needs
  icon, name, short/long descriptions, developer name, **privacy policy + terms**,
  screenshots, a **verified domain**, and a hosted MCP server. Public publishing is
  gated (larger/verified companies first as of early 2026). **No-auth will not pass
  review for payments — OAuth required.**
- **ChatGPT Enterprise/Business:** workspace admins deploy connectors org-wide;
  good for pilots/B2B without public listing.
- **OpenAI API / Agents / Responses:** developers wire the MCP server in code
  (`tools:[{type:"mcp", server_url:…}]`). No connector UI; also no auto-rendered
  card (a raw API agent has no chat surface) → use the gateway confirm-page fallback.
- **Claude:** Desktop = local stdio config; web/mobile = custom connector
  (remote MCP). Anthropic has its own directory/connector surfaces.
- **Codex / Cursor:** config-file MCP, no card rendering → fallback.

---

## 9. Production requirements (do NOT ship the spike server as-is)

1. **Auth:** OAuth on the hosted MCP server (no-auth fails ChatGPT review and is
   unacceptable for payments).
2. **Transport security:** pin `allowed_hosts`/`allowed_origins`, re-enable
   DNS-rebinding protection (the spike disabled it for the tunnel), scoped CORS.
3. **CSP:** declare `_meta.ui.csp` (`connectDomains` = the gateway origin only).
4. **App-only confirm tool:** `snaplii_confirm_purchase` → `visibility:["app"]`.
5. **Canonical data into the card** from the token record, not agent text.
6. **Use the official client lib:** build the card with
   `@modelcontextprotocol/ext-apps` `App` class (handles handshake, sizing,
   tool-result, teardown, host-context) + a `vite-singlefile` bundle — do not ship
   the hand-rolled postMessage from the spike.
7. **Keep the stable core:** token + canonical record stay the security boundary;
   the App UI is a swappable presentation layer (the spec is Draft and will move).
8. **Verified domain + privacy policy + terms** for directory submission.

---

## 10. Proposed production architecture (composes with 0.14.0)

```
snaplii_quote (model)  ──► build canonical record, issue confirmation_token
        │                  tool carries _meta.ui.resourceUri = ui://snaplii/confirm.html
        ▼
 host renders confirm card (sandboxed iframe)
        │  card pulls CANONICAL fields from server (tool-result / app-only get tool)
        │  shows real you_pay / voucher / cashback  — declared CSP
        ▼
 user clicks Approve
        │  card → tools/call snaplii_confirm_purchase { confirmation_token }
        │        (snaplii_confirm_purchase is visibility:["app"] — model can't call it)
        ▼
 server: validate(token) → consume → charge under stored context → result
        │
        └─ no UI capability?  → BLOCKED unless CLI / gateway elicit_url / opt-in   (mode.py)
```

Reuses `quote_store.py`, `canonical.py`, and the charge-under-approved-context
work already on the branch. The net new pieces: the `ui://` resource + card, the
app-only confirm tool, the runtime capability gate, an HTTP deployment for
ChatGPT/Claude-web, and OAuth.

---

## 11. Open questions / risks

- **Spec is Draft (SEP-1865).** Field names can shift before GA — isolate the App
  layer; keep token+canonical stable.
- **ChatGPT bridge quirk:** reported to drop custom `_meta` from tool results in
  `ui/notifications/tool-result`. Verify canonical-data delivery on ChatGPT.
- **Directory gating:** public ChatGPT publishing is weighted to larger/verified
  companies first — confirm Snaplii's eligibility early if consumer ChatGPT is on
  the roadmap.
- **Auth design:** OAuth flow for the hosted connector is unspecified here — needs
  its own design (ties into the gateway).
- **Codex / arbitrary agents:** depend entirely on the gateway `elicit_url`
  fallback; that page is not built yet.

---

## 12. References

- Spec: https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx
- MCP Apps overview / build: https://modelcontextprotocol.io/extensions/apps/overview ·
  https://modelcontextprotocol.io/extensions/apps/build
- OpenAI Apps SDK (build / submission / guidelines):
  https://developers.openai.com/apps-sdk/build/mcp-server ·
  https://developers.openai.com/apps-sdk/deploy/submission ·
  https://developers.openai.com/apps-sdk/app-submission-guidelines
- MCP Apps vs OpenAI Apps SDK (2026): https://mcp.directory/blog/mcp-apps-standard-vs-openai-apps-sdk-2026
- Local spike: `spikes/mcp-apps-stdio/` (`README.md` = Claude/stdio, `README_chatgpt.md` = ChatGPT/HTTP)

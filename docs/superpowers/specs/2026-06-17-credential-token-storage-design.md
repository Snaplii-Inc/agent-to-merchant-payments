# Snaplii A2M — Credential & Token Storage (Design)

**Date:** 2026-06-17
**Status:** Documents shipped behavior (`snaplii-cli/src/snaplii/config_store.py`, `client.py`, `mcp-server/server.py`)
**Author:** brainstormed with Claude

## 1. Motivation

The agent (model) is untrusted for secrets (see *Payment Security Hardening*). Two
secrets exist in the local flow: the **API key** the user owns, and the **access
token** the gateway issues in exchange for it. This note pins down, in one place,
*what is stored, where, and under which conditions* — so the invariant "the API key
never persists, and the token never lands in plaintext-on-disk by default" is
auditable rather than folklore.

## 2. The two secrets

| Secret | Lifetime | Persisted? |
|---|---|---|
| **API key** (`snp_sk_live_…`) | Used once per auth to exchange for a token | **Never.** Not disk, not memory, not returned, not echoed. |
| **access_token** (JWT) | Cached until expiry (`expires_in`, default 3600s) | Yes — location depends on environment (§4). |

### 2.1 API key — never stored

`_authenticate()` (`server.py:56`) takes the key, calls `login()` to swap it for a
token, then drops it. The key is locked out of the store at two layers:

- `ConfigStore._NEVER_STORE = {"api_key"}` — `set("api_key", …)` is a silent no-op
  (`config_store.py:93,126-128`), and `save()` skips it (`:100-101`).
- The connect card collects the key **off the model context** entirely
  (`snaplii_connect` → `snaplii_submit_api_key`), so it never enters chat. The card
  also clears the key from the DOM right after submit (`cards.py:272`).

The card path and the terminal `snaplii_init` path call the *same* `_authenticate()`,
so storage behavior is identical regardless of how the key was entered.

## 3. What the access token represents

`login()` POSTs `/v2/auth/token` and, on success, calls `cache_token(token,
expires_in)` (`client.py:63-71`). The token is the only thing that proves an active
session; without a valid cached token, the next tool call must re-authenticate
(which, by design, the CLI does silently per process — see §4.3).

## 4. Token storage — decision order

`ConfigStore.save()` (`config_store.py:95-114`) routes `access_token` (the only key in
`_SECRET_KEYS`) through this precedence:

```
1. OS keyring available            → system keychain        (DEFAULT)
2. else + insecure opt-in          → chmod-600 plaintext file
3. else (no keyring, no opt-in)    → process memory only    (FALLBACK)
```

`access_token` is **never** written to `config.json` in any branch.

### 4.1 Default — OS keyring

`_keyring_available()` is true when the `keyring` backend resolves to something other
than the "fail" backend (`config_store.py:17-24`). Then the token is stored via
`keyring.set_password("snaplii-cli", "access_token", …)` (`:27-30`).

> **Observed on a macOS dev machine (2026-06-17):** keyring available →
> token lives in `~/Library/Keychains/login.keychain-db`, class `genp`,
> service `snaplii-cli`, account `access_token`. `config.json` held only
> `agent_id`, `token_expires_at`, `country`, `_version_check_*` — no token.

### 4.2 Opt-in — plaintext on disk

Only when **both**: no usable keyring **and** the user explicitly opted in via
`SNAPLII_ALLOW_INSECURE` env (`1/true/yes/on`) or `allow_insecure_mode: true` in
`config.json` (`_insecure_persist_ok()`, `config_store.py:62-74`). The token is then
written to the config file, `chmod 600`. Default is OFF.

### 4.3 Fallback — process memory

No keyring and no opt-in → the token is kept in the class-level
`ConfigStore._MEM_SECRETS` dict (`config_store.py:56,110`). This survives the many
short-lived `ConfigStore()` instances the MCP server creates per tool call within one
process, but **not** across separate processes — so a fresh CLI process re-auths by
design. Nothing touches disk.

## 5. Non-secret metadata (plaintext `config.json`)

Written normally to `~/.snaplii/config.json` (`chmod 600`, `:113-114`):

| Key | Source | Purpose |
|---|---|---|
| `agent_id` | `agent-<md5(api_key)[:8]>` derived, or caller-supplied (`server.py:64-65,81`) | session identity; **not** the key itself |
| `token_expires_at` | `time.time() + expires_in` (`config_store.py:162-166`) | drives refresh (90s safety margin, `:158`) |
| `country` | gateway login response `country` (`client.py:76-78`) | label local currency (CA=CAD/US=USD) for balance & quote |
| `_version_check_*` | update checker | cache update-check timestamp |

## 6. Inspecting state

`snaplii_config_show` returns config **with secrets stripped** — it drops
`access_token` / `token_expires_at` / `_`-prefixed keys and instead exposes a derived
`has_valid_token` boolean (`server.py:371-375`). So the model never sees the token
even when asked to "show config".

`get_cached_token()` returns the token only if present **and** not within the 90s
expiry margin; otherwise `None`, forcing re-auth (`config_store.py:150-160`).

## 7. Invariants (audit checklist)

1. `api_key` appears in **no** persisted store — disk, keyring, or memory.
2. `access_token` is **never** in `config.json` plaintext unless §4.2 opt-in is set.
3. Default on a keyring-capable host → token in the **OS keychain**, not memory, not disk.
4. `snaplii_config_show` never surfaces the raw token to the model.
5. Card path and `snaplii_init` path share `_authenticate()` → identical storage.

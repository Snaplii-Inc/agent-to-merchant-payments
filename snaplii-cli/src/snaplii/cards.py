"""MCP Apps cards (off-model UI surfaces) served by the MCP server.

The API-key card lets the user type their key into a sandboxed iframe; the card
calls the app-only `snaplii_submit_api_key` tool directly, so the key reaches the
server WITHOUT ever entering the model's context (no transcript/log leak). The
postMessage handshake + sizing scaffolding is the pattern validated in
spikes/mcp-apps-stdio/.
"""

from __future__ import annotations

# The ui:// scheme marks this as an MCP App resource (host renders it in a
# sandboxed iframe). The path is arbitrary but stable.
APIKEY_RES_URI = "ui://snaplii/apikey.html"

# Spec: the resource MIME MUST be exactly this or the host renders it as plain
# content instead of an interactive app.
MCP_APP_MIME = "text/html;profile=mcp-app"

# The tool the card invokes on submit. App-only (visibility:["app"]) so the model
# can neither see nor call it — only a human action in the card can.
SUBMIT_TOOL = "snaplii_submit_api_key"

# Self-contained card. Under the spec's default CSP
# (script-src 'self' 'unsafe-inline'; connect-src 'none') the inline script runs
# and no external network is needed — the key only travels via postMessage→host.
APIKEY_CARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Connect Snaplii</title>
<style>
  :root {
    color-scheme: light dark;
    --bg: #eef0f3; --card: #ffffff; --border: #e5e7eb; --text: #14171d;
    --muted: #6b7280; --field: #f7f8fa; --field-border: #d6dae1;
    --accent: #12a150; --accent-press: #0e8a44; --accent-soft: rgba(18,161,80,.14);
    --ok: #12a150; --err: #d23f3f;
    --shadow: 0 6px 24px rgba(17,24,39,.08), 0 1px 2px rgba(17,24,39,.06);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #14171c; --card: #1f242b; --border: #2c323b; --text: #e9ecf0;
      --muted: #9aa2ad; --field: #161a20; --field-border: #353c46;
      --accent: #2bd574; --accent-press: #25c069; --accent-soft: rgba(43,213,116,.16);
      --ok: #2bd574; --err: #ff6b6b;
      --shadow: 0 8px 28px rgba(0,0,0,.40);
    }
  }
  * { box-sizing: border-box; }
  body {
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    margin: 0; padding: 20px; background: var(--bg); color: var(--text);
    -webkit-font-smoothing: antialiased;
  }
  .card {
    background: var(--card); border: 1px solid var(--border); border-radius: 16px;
    padding: 22px; max-width: 420px; box-shadow: var(--shadow);
  }
  .head { display: flex; align-items: center; gap: 11px; margin-bottom: 14px; }
  .badge {
    width: 38px; height: 38px; border-radius: 11px; flex: 0 0 auto;
    display: grid; place-items: center; background: var(--accent-soft); color: var(--accent);
  }
  .badge svg { width: 21px; height: 21px; display: block; }
  .title { font-size: 16px; font-weight: 680; letter-spacing: -.01em; }
  .title small { display: block; font-weight: 500; font-size: 12.5px; color: var(--muted); margin-top: 1px; }
  label { display: block; font-weight: 600; font-size: 12.5px; margin: 0 0 6px; color: var(--muted); }
  .field { position: relative; }
  input {
    width: 100%; padding: 12px 13px; border-radius: 11px; background: var(--field);
    border: 1.5px solid var(--field-border); color: var(--text);
    font: 13.5px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .3px;
    transition: border-color .15s, box-shadow .15s; outline: none;
  }
  input::placeholder { color: var(--muted); opacity: .6; }
  input:focus { border-color: var(--accent); box-shadow: 0 0 0 3.5px var(--accent-soft); }
  button {
    width: 100%; margin-top: 14px; padding: 12px 16px; border-radius: 11px; border: 0;
    font: 600 14.5px -apple-system, system-ui, sans-serif; color: #fff; cursor: pointer;
    background: var(--accent); transition: background .15s, transform .05s, opacity .15s;
  }
  button:hover:not(:disabled) { background: var(--accent-press); }
  button:active:not(:disabled) { transform: translateY(1px); }
  button:disabled { opacity: .55; cursor: default; }
  #status { margin-top: 12px; font-weight: 600; font-size: 13px; min-height: 17px; }
  #status.ok { color: var(--ok); }
  #status.err { color: var(--err); }
  .foot {
    display: flex; gap: 8px; align-items: flex-start; margin-top: 16px; padding-top: 14px;
    border-top: 1px solid var(--border); color: var(--muted); font-size: 11.5px; line-height: 1.45;
  }
  .foot svg { width: 13px; height: 13px; flex: 0 0 auto; margin-top: 2px; opacity: .85; }
</style>
</head>
<body>
  <div class="card">
    <div class="head">
      <div class="badge" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3z"/>
          <path d="M9 12l2 2 4-4"/>
        </svg>
      </div>
      <div class="title">Connect Snaplii
        <small>Your key goes straight to Snaplii — never through the AI.</small>
      </div>
    </div>

    <label for="apikey">Snaplii API key</label>
    <div class="field">
      <input id="apikey" type="password" autocomplete="off" spellcheck="false"
             placeholder="snp_sk_live_…" />
    </div>
    <button id="connect">Connect securely</button>
    <div id="status"></div>

    <div class="foot">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <rect x="4" y="11" width="16" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>
      </svg>
      <span>Used once to get a short-lived token, never stored. Daily spend is
        capped by the limit you set when creating the key.</span>
    </div>
  </div>

<script>
(function () {
  var PROTOCOL = "2025-11-25";
  var SUBMIT_TOOL = "__SUBMIT_TOOL__";
  var statusEl = document.getElementById("status");
  var inputEl = document.getElementById("apikey");
  var btnEl = document.getElementById("connect");
  var pending = {};
  var nextId = 1;

  function setStatus(msg, kind) { statusEl.textContent = msg; statusEl.className = kind || ""; }
  function post(obj) { window.parent.postMessage(obj, "*"); }

  function request(method, params) {
    var id = nextId++;
    post({ jsonrpc: "2.0", id: id, method: method, params: params || {} });
    return new Promise(function (resolve, reject) {
      pending[id] = { resolve: resolve, reject: reject };
      setTimeout(function () {
        if (pending[id]) { delete pending[id]; reject(new Error("timeout waiting for " + method)); }
      }, 8000);
    });
  }
  function notify(method, params) { post({ jsonrpc: "2.0", method: method, params: params || {} }); }

  // Host keeps the iframe at 0px until the app reports its size.
  function reportSize() {
    var h = Math.ceil(Math.max(document.documentElement.scrollHeight,
      document.body.scrollHeight, document.body.getBoundingClientRect().height));
    var w = document.documentElement.clientWidth || document.body.scrollWidth;
    post({ jsonrpc: "2.0", method: "ui/notifications/size-changed", params: { width: w, height: h } });
  }

  window.addEventListener("message", function (event) {
    var data = event.data;
    if (!data || data.jsonrpc !== "2.0") { return; }
    if (data.id != null && (data.result !== undefined || data.error !== undefined)) {
      var p = pending[data.id];
      if (!p) { return; }
      delete pending[data.id];
      if (data.error) { p.reject(new Error(JSON.stringify(data.error))); }
      else { p.resolve(data.result); }
    }
  });

  function handshake() {
    return request("ui/initialize", {
      protocolVersion: PROTOCOL,
      appInfo: { name: "snaplii-connect-card", version: "0.1.0", title: "Connect Snaplii" },
      appCapabilities: { tools: {}, availableDisplayModes: ["inline"] }
    }).then(function () {
      notify("ui/notifications/initialized", {});
      reportSize();
      setStatus("");
    }).catch(function () {
      setStatus("Couldn't reach the host — try a client that supports MCP Apps, or run 'snaplii init' in a terminal.", "err");
    });
  }

  function submit() {
    var key = (inputEl.value || "").trim();
    if (!key) { setStatus("Enter your API key first.", "err"); inputEl.focus(); return; }
    btnEl.disabled = true; inputEl.disabled = true;
    setStatus("Connecting…", "");
    request("tools/call", { name: SUBMIT_TOOL, arguments: { api_key: key } })
      .then(function (res) {
        var text = "";
        try { text = (res.content || []).map(function (c) { return c.text || ""; }).join(" "); } catch (e) {}
        var ok = text.indexOf("authenticated") !== -1;
        inputEl.value = "";  // never keep the key in the DOM longer than needed
        if (ok) {
          setStatus("✓ Connected. You can close this and continue.", "ok");
          btnEl.textContent = "Connected";
        } else {
          setStatus("⚠ " + (text || "Could not connect."), "err");
          btnEl.disabled = false; inputEl.disabled = false;
        }
      })
      .catch(function (err) {
        setStatus("✕ Could not connect: " + err.message, "err");
        btnEl.disabled = false; inputEl.disabled = false;
      });
  }

  btnEl.addEventListener("click", submit);
  inputEl.addEventListener("keydown", function (e) { if (e.key === "Enter") { submit(); } });

  if (window.ResizeObserver) { new ResizeObserver(reportSize).observe(document.body); }
  window.addEventListener("load", function () { reportSize(); inputEl.focus(); });
  setTimeout(reportSize, 300);
  handshake();
})();
</script>
</body>
</html>
""".replace("__SUBMIT_TOOL__", SUBMIT_TOOL)

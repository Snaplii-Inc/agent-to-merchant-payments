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
# Aesthetic: "Fintech restrained" — deep slate, single emerald accent, a hairline
# accent at the top, and a clean centered success state.
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
    --accent: #12a150; --accent2: #1bb45e; --accent-press: #0e8a44;
    --accent-soft: rgba(18,161,80,.14);
    --err: #d23f3f;
    --shadow: 0 10px 30px rgba(17,24,39,.10), 0 1px 2px rgba(17,24,39,.06);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #0f1216; --card: #1b2026; --border: #2c323b; --text: #e9ecf0;
      --muted: #9aa2ad; --field: #12161b; --field-border: #353c46;
      --accent: #2bd574; --accent2: #33e07d; --accent-press: #25c069;
      --accent-soft: rgba(43,213,116,.16);
      --err: #ff6b6b;
      --shadow: 0 14px 40px rgba(0,0,0,.5);
    }
  }
  * { box-sizing: border-box; }
  body {
    font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    margin: 0; padding: 20px; background: var(--bg); color: var(--text);
    -webkit-font-smoothing: antialiased;
  }
  /* NO_COLLAPSE hosts (Codex) don't shrink the iframe. Stretch the card to FILL the
     frame and show a big centered check with "Connected" below it — one solid panel,
     no dead void. */
  body.centered { min-height: 100vh; display: flex; flex-direction: column; }
  body.centered > .card { flex: 1 1 auto; }
  .card.filled { display: flex; align-items: center; justify-content: center; }
  .card.filled .head, .card.filled .foot { display: none; }
  .card.filled #success { padding: 0; }
  .card.filled #success .ssub { display: none; }
  .card.filled #success .scheck { width: 72px; height: 72px; margin-bottom: 16px; }
  .card.filled #success .scheck svg { width: 40px; height: 40px; }
  .card.filled #success .stitle { font-size: 19px; }
  .card {
    position: relative; overflow: hidden;
    background: var(--card); border: 1px solid var(--border); border-radius: 18px;
    padding: 24px; width: 100%; box-shadow: var(--shadow);
  }
  /* hairline accent at the very top edge */
  .card::before {
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: linear-gradient(90deg, transparent, var(--accent2), transparent);
    opacity: .9;
  }
  .head { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; }
  .badge {
    width: 40px; height: 40px; border-radius: 12px; flex: 0 0 auto;
    display: grid; place-items: center; color: #fff;
    background: linear-gradient(140deg, var(--accent2), var(--accent-press));
    box-shadow: 0 4px 12px var(--accent-soft);
  }
  .badge svg { width: 22px; height: 22px; display: block; }
  .title { font-size: 17px; font-weight: 700; letter-spacing: -.01em; }
  .title small {
    display: block; font-weight: 500; font-size: 12.5px; color: var(--muted);
    margin-top: 3px; letter-spacing: 0;
  }
  label {
    display: block; font-weight: 700; font-size: 11px; text-transform: uppercase;
    letter-spacing: .07em; margin: 0 0 7px; color: var(--muted);
  }
  .field { position: relative; }
  input {
    width: 100%; padding: 13px 14px; border-radius: 12px; background: var(--field);
    border: 1.5px solid var(--field-border); color: var(--text);
    font: 13.5px ui-monospace, SFMono-Regular, Menlo, monospace; letter-spacing: .3px;
    transition: border-color .15s, box-shadow .15s; outline: none;
  }
  input::placeholder { color: var(--muted); opacity: .6; }
  input:focus { border-color: var(--accent); box-shadow: 0 0 0 3.5px var(--accent-soft); }
  button {
    width: 100%; margin-top: 15px; padding: 13px 16px; border-radius: 12px; border: 0;
    font: 700 14.5px -apple-system, system-ui, sans-serif; color: #fff; cursor: pointer;
    background: linear-gradient(140deg, var(--accent2), var(--accent));
    box-shadow: 0 4px 14px var(--accent-soft);
    transition: filter .15s, transform .05s, opacity .15s;
  }
  button:hover:not(:disabled) { filter: brightness(1.06); }
  button:active:not(:disabled) { transform: translateY(1px); }
  button:disabled { opacity: .6; cursor: default; }
  #status { margin-top: 12px; font-weight: 600; font-size: 13px; min-height: 17px; }
  #status.err { color: var(--err); }
  /* success state replaces the form entirely */
  #success { display: none; flex-direction: column; align-items: center; text-align: center; padding: 6px 0 2px; }
  #success.show { display: flex; }
  .scheck {
    width: 52px; height: 52px; border-radius: 50%; display: grid; place-items: center;
    color: #fff; background: linear-gradient(140deg, var(--accent2), var(--accent-press));
    box-shadow: 0 6px 18px var(--accent-soft); margin-bottom: 12px;
  }
  .scheck svg { width: 28px; height: 28px; }
  .stitle { font-size: 16px; font-weight: 700; letter-spacing: -.01em; }
  .ssub { font-size: 13px; color: var(--muted); margin-top: 4px; }
  /* collapsed state: recede to a slim "✓ Connected" bar once the user has read it */
  .card.done { padding: 14px 18px; }
  .card.done .head, .card.done .foot { display: none; }
  .card.done #success { flex-direction: row; gap: 9px; padding: 0; }
  .card.done #success .scheck { width: 24px; height: 24px; margin-bottom: 0; }
  .card.done #success .scheck svg { width: 15px; height: 15px; }
  .card.done #success .stitle { font-size: 14.5px; }
  .card.done #success .ssub { display: none; }
  .foot {
    display: flex; gap: 8px; align-items: flex-start; margin-top: 18px; padding-top: 15px;
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

    <div id="form">
      <label for="apikey">Snaplii API key</label>
      <div class="field">
        <input id="apikey" type="password" autocomplete="off" spellcheck="false"
               placeholder="snp_sk_live_…" />
      </div>
      <button id="connect">Connect securely</button>
      <div id="status"></div>
    </div>

    <div id="success" aria-live="polite">
      <div class="scheck" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
             stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
      </div>
      <div class="stitle">Connected</div>
      <div class="ssub">You're connected — just continue in chat. Spending stays within the daily limit <b>you</b> set in the app, so I won't ask you to confirm each purchase.</div>
    </div>

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
  // Flipped to true by the server for hosts that DROP downward resize (e.g. Codex):
  // there, collapsing to the slim "✓ Connected" bar just leaves dead space below, so
  // we keep the full success card instead.
  var NO_COLLAPSE = false;
  var statusEl = document.getElementById("status");
  var inputEl = document.getElementById("apikey");
  var btnEl = document.getElementById("connect");
  var formEl = document.getElementById("form");
  var successEl = document.getElementById("success");
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
  // IMPORTANT for shrinking: document.documentElement.scrollHeight is floored to
  // the current iframe (viewport) height, so once the host has grown the frame it
  // would keep reporting that large value and the frame could never shrink back.
  // Measure the actual CONTENT instead — the card box plus the body's vertical
  // padding — so the collapsed "✓ Connected" bar reports its true, smaller height.
  function reportSize() {
    var card = document.querySelector(".card");
    var bs = window.getComputedStyle(document.body);
    var padV = (parseFloat(bs.paddingTop) || 0) + (parseFloat(bs.paddingBottom) || 0);
    var contentH = card ? card.getBoundingClientRect().height + padV : document.body.scrollHeight;
    var h = Math.ceil(Math.max(contentH, 1));
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
      checkAlreadyConnected();
    }).catch(function () {
      setStatus("Couldn't reach the host — try a client that supports MCP Apps, or run 'snaplii init' in a terminal.", "err");
    });
  }

  // A single reportSize() right after a class change is unreliable: scrollHeight
  // read synchronously is stale (pre-reflow, still the old large height), and some
  // hosts debounce or drop a lone shrink. Re-report across a couple of animation
  // frames and a few timeouts so the host receives the true, smaller size.
  function reportSizeSoon() {
    if (window.requestAnimationFrame) {
      requestAnimationFrame(function () { requestAnimationFrame(reportSize); });
    }
    // Re-report over a longer, denser window: some hosts (e.g. Codex) debounce or
    // drop a lone downward resize, so the iframe stays at its grown height and the
    // collapsed "✓ Connected" bar leaves dead space below. Repeating the smaller
    // size past the host's settle window gives it several chances to shrink.
    [0, 60, 180, 360, 650, 1000, 1500, 2200].forEach(function (ms) {
      setTimeout(reportSize, ms);
    });
  }

  function showSuccess(immediate) {
    formEl.style.display = "none";
    successEl.classList.add("show");
    if (NO_COLLAPSE) {
      // Host drops downward resize (Codex): fill the frame with one solid panel —
      // big centered check + "Connected" below — instead of a slim bar over a void.
      document.body.classList.add("centered");
      var cc = document.querySelector(".card");
      if (cc) { cc.classList.add("filled"); }
      return;
    }
    if (immediate) {
      // Already-connected on (re)load — go straight to the slim "✓ Connected" bar,
      // no celebration delay.
      var c0 = document.querySelector(".card");
      if (c0) { c0.classList.add("done"); }
      reportSizeSoon();
      return;
    }
    reportSizeSoon();
    // Briefly let the user register "Connected", then recede to a slim
    // "✓ Connected" bar and re-report the smaller size after reflow so hosts
    // that honor downward resize shrink the frame to just the bar.
    setTimeout(function () {
      var card = document.querySelector(".card");
      if (card) { card.classList.add("done"); }
      reportSizeSoon();
    }, 1500);
  }

  // On (re)load — e.g. revisiting an old conversation that re-renders this card —
  // collapse straight to the "✓ Connected" bar if the account is already
  // authenticated, instead of showing a live input form again. Best-effort: only
  // takes effect on hosts that re-run the card JS (not a frozen snapshot) and let
  // the app query snaplii_config_show; otherwise the form stays as-is.
  function checkAlreadyConnected() {
    request("tools/call", { name: "snaplii_config_show", arguments: {} })
      .then(function (res) {
        var text = "";
        try { text = (res.content || []).map(function (c) { return c.text || ""; }).join(" "); } catch (e) {}
        var connected = false;
        try { connected = JSON.parse(text).has_valid_token === true; } catch (e) {}
        if (connected) { showSuccess(true); }
      })
      .catch(function () { /* leave the form as-is */ });
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
        // Success only when the auth result explicitly says so. Parse the JSON
        // result and check status; fall back to a quoted-substring match.
        var ok = false, message = "";
        try {
          var parsed = JSON.parse(text);
          ok = parsed.status === "authenticated";
          message = parsed.message || "";
        } catch (e) {
          ok = text.indexOf('"authenticated"') !== -1;
        }
        inputEl.value = "";  // never keep the key in the DOM longer than needed
        if (ok) {
          setStatus("", "");
          showSuccess();
        } else {
          setStatus("⚠ " + (message || text || "Could not connect."), "err");
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

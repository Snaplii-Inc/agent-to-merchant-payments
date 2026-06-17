# Snaplii A2M — URL-mode Elicitation 安全连接页(#2 设计)

**Date:** 2026-06-17
**Status:** 设计 — **gated**(用户少阶段先不建,见 §0)
**Related:**
- `2026-06-10-mcp-apps-confirmation-channel.md` — card 通道;本页就是它第 6 节点名的 `elicit_url` 通用兜底。
- `2026-06-15-oauth-mcp-connector.md` — 托管 HTTP + OAuth(本页与之同属「托管网页版」这条大轨)。
- `2026-06-17-credential-token-storage-design.md` — token 在本地落在哪(keychain)。
- 已实现的接口缝:`mcp-server/server.py` 的 `_connect_route()` / `_elicit_url()` / `snaplii_connect` 的 elicit 分支(#1)。

---

## 0. TL;DR & 优先级

- **它是什么:** 给「能 elicit、但渲染不了 MCP Apps card」的客户端(Codex desktop/CLI、Cursor、Claude Code)做的安全连接页。客户端发 URL-mode elicitation → 系统浏览器打开**本页** → 用户在页里输 API key → 网关换 token。
- **为什么必须 URL mode:** spec 强制——收 API key/密码/支付凭证 **MUST 用 URL mode,form 禁止**。
- **#1 已就位:** `snaplii_connect` 的 elicit 分支已经写好,只差 `_elicit_url()` 指向的这页 + 网关端点。
- **优先级:gated。** 用户少阶段,这些客户端**都是本地 stdio**,已经有 `snaplii init`(本地直接换 token,无跨进程问题)。本页真正变刚需,是做**托管网页版**、面对**没有便捷终端**的用户时。**先写清楚,不急着建;现在保持 stub。**

---

## 1. 范围:它补的是哪一块

| 通道 | 覆盖客户端 | 状态 |
|---|---|---|
| MCP Apps card | Claude(桌面/网页)、ChatGPT、VS Code、Goose… | 已上线(`cards.py`) |
| 终端 `snaplii init` | 任何有终端的本地客户端 | 已上线 |
| **URL-mode 连接页(本设计)** | Codex(desktop/CLI)、Cursor、Claude Code、easyclaw… | **缺这页** |

不替代前两者;它就是 `_connect_route()` 里 `elicit` 分支的落地实现。

---

## 2. 两层「成功」(务必分清)

1. **浏览器页层** — 给**人**看:页面调网关验证 key 后,直接渲染 ✅「已连接,可关闭回到对话」/ ❌「key 无效,请重试」。**你全控,简单。**
2. **agent / server 层** — 给**对话流**用:elicitation 回给客户端的只有 `accept`(**不含内容、不含成败**)。要让后续 `balance`/`quote`/`purchase` 能跑,**MCP server 必须拿到 token**。

→ 同步回去的是「token 可用」这个状态,**不是 key**。key 在任何分支下都**永不经过 agent/模型/客户端**(这正是 URL mode 的全部意义)。不做回交的后果不是漏 key,而是:**用户在浏览器看到成功、回到对话却报「未认证」。**

---

## 3. 核心难点:token 怎么回到调用方

这是本设计**唯一真正难**的地方,且**因部署而异**:

- **托管 HTTP server**(ChatGPT/Claude 网页那种):MCP server 与网关同侧,可按用户身份直接取 token。**近乎自动。**
- **本地 stdio server**(Codex desktop 那种):浏览器把 key 提交给了**网关**,而本地 server 是**另一个进程**,既不知道成功、也没拿到 token。必须由 **server 用 `elicitation_id` 主动回网关取**。

下面的端点与流程,核心就是把第二种情形跑通(第一种是它的子集)。

---

## 4. 端到端流程

```
Client (Codex…)        MCP server (本地/托管)        浏览器(系统默认)        Gateway
   │  tools/call snaplii_connect │                          │                      │
   │ ───────────────────────────►│                          │                      │
   │                             │  生成 eid(高熵/一次性/短TTL)                    │
   │                             │  elicit_url(message,url=…/connect?eid=…, eid)   │
   │ ◄───────────────────────────│  (客户端弹同意框 + 显示 URL)                     │
   │  用户同意 → 开系统浏览器     │                          │                      │
   │                             │                          │  GET /connect?eid=… ►│
   │                             │                          │ ◄ HTML 收 key 页 ────│
   │                             │                          │  用户输 key, submit  │
   │                             │                          │  POST /connect/submit│
   │                             │                          │ ────────────────────►│
   │                             │                          │      验证 key → mint token
   │                             │                          │      按 eid 暂存 token(短TTL)
   │                             │                          │ ◄ 200 {ok:true} ─────│
   │                             │                          │  页面显示 ✅          │
   │                             │  轮询 GET /v2/auth/elicit/{eid}/token (带 eid) ─►│
   │                             │ ◄ {access_token,country,expires_in} ───────────│  (一次性消费 eid)
   │                             │  cache_token() → keychain                        │
   │ ◄ 工具结果: authenticated ──│  (accept 后这一轮或下一轮返回)                   │
```

要点:
- `accept` 只意味「用户同意去填」。**成败由 server 轮询判定**,不靠 elicitation 回值。
- 轮询有超时;超时/declined → 返回友好文案 + 退 `snaplii init`。

---

## 5. 用户绑定 / 防钓鱼(spec 强制)

spec 的 URL-mode 钓鱼条款:**必须保证「触发 elicitation 的用户」== 「在页面提交的用户」**,否则 Alice 触发、骗 Bob 去填,token 会绑错人 → 账户接管。

两种部署的绑定手段不同:

- **本地 stdio:** 没有浏览器 session 与 MCP 用户的天然关联。**用 `eid` 本身做绑定锚:**
  - `eid` 高熵、单次消费、短 TTL(建议 ≤120s)。
  - **token 只回给持有 `eid` 的轮询方**(= 本地 server,`eid` 当 bearer 取 token)。
  - 即便 URL 被转发给他人去填,**填的人拿不到 token**(token 不在页面回,只在轮询端回),被转发者顶多是「替你输了 key」——而 key 是用户自己的,风险面收敛到「别把自己的连接链接发给别人」,与 OAuth 同级。
- **托管 / web:** 加 spec 推荐做法——`/connect` 页校验浏览器 **session cookie 的 `sub`** 与触发 elicitation 的 MCP 用户一致后,才接受提交。

URL 安全(spec):HTTPS;**不带任何敏感信息**;**不预认证**;客户端侧高亮域名、不自动预取、不自动打开(已是客户端职责)。

---

## 6. 网关要加的端点

| 方法 & 路径 | 作用 | 备注 |
|---|---|---|
| `GET /connect?eid=…` | 返回收 key 的 HTML 页 | 见 §7;托管场景先校验 session |
| `POST /connect/submit` | 页面提交 `{eid, api_key}` | 验证 key(复用现有 `/v2/auth/token` 逻辑)→ mint token → 按 `eid` 暂存 |
| `GET /v2/auth/elicit/{eid}/token` | server 轮询取 token | **凭 `eid`**;命中即**一次性消费并删除**;返回 `{access_token, country, expires_in}` |

- `eid` 由 **MCP server 生成**(`uuid4`,已在 #1 的 `elicit_url(... elicitation_id=…)` 里),网关只认它、按它存取。无需额外 start 端点。
- `eid` 暂存项:短 TTL、单次消费、用后即焚。
- 复用既有 auth:验证/换 token 走现有 `AuthV2Controller` / `/v2/auth/token` 那套,不另起认证逻辑。

---

## 7. 收 key 页(HTML)

- 一个 masked 输入框 + Connect 按钮 + 状态区(复用 `cards.py` 的视觉与「✓ Connected」终态)。
- 提交 → `POST /connect/submit` → 成功渲染 ✅「已连接,可关闭此页回到对话」;失败渲染 ❌ + 可重试。
- **声明 CSP**(06-10 spike 里 ChatGPT 报过 "CSP off";本页是真浏览器页,更要有)。
- key 提交后立刻清出 DOM(同 `cards.py:272`)。
- 不在页里 echo key、不写日志。

---

## 8. MCP server 侧改动(接上 #1)

把 #1 里 `snaplii_connect` elicit 分支的 `TODO(#2)` 段替换成真实回交:

1. `_elicit_url()` 返回配置的 base(`SNAPLII_ELICIT_URL` / config `elicit_url`)。
2. 生成 `eid`(已有),拼 `url = f"{base}?eid={eid}"`,调 `session.elicit_url(message, url, elicitation_id=eid)`。
3. `accept` 后:**轮询** `GET /v2/auth/elicit/{eid}/token`,带退避 + 总超时(如 90s)。
   - 拿到 → `ConfigStore().cache_token(...)` + 存 `country`/`agent_id` → 返回 `{"status":"authenticated", ...}`(连同那条一次性 consent notice,同 `_authenticate`)。
   - 超时 → `{"status":"pending", …}` 引导重试 / `snaplii init`。
4. `decline/cancel` → 友好文案。

> 注意:本地 stdio 下,网关暂存的 token 与本地 `ConfigStore` 是两套;回交后**以本地缓存为准**,行为与 `snaplii init` 收口一致(都最终落 keychain,见 storage 设计文档)。

---

## 9. 安全清单(审计用)

1. key 路径:用户 → 浏览器页 → 网关;**不经过 client / 模型 / 中间 server**(spec)。
2. token 只回给**持 `eid` 的轮询方**;`eid` 高熵、短 TTL、一次性消费。
3. `accept` ≠ 成功;成败由 server 带外判定,不信 elicitation 回值。
4. HTTPS;URL 不带敏感信息、不预认证;域名高亮(客户端职责)。
5. web 部署额外加 `session.sub` == elicitation 用户校验(防钓鱼)。
6. 页面:CSP、masked 输入、提交后清 DOM、不 echo、不记日志。

---

## 10. 测试

- **单测(MCP server):** mock 网关轮询端点,验证 elicit 分支:命中→authenticated、超时→pending、declined→友好退出。复用 `tests/test_apikey_card.py` 的路由测试骨架。
- **e2e:** Codex desktop 真机走一遍:同意框 → 系统浏览器开页 → 输 key → 页显示 ✅ → 回 Codex,`balance` 能调通。
- **回归:** 确认 `_elicit_url()` 未配置时仍走 `connect_unconfigured` 文案(stub 不退化)。

---

## 11. 工作量 & 决策

| 部分 | 难度 |
|---|---|
| 收 key 页 HTML + `/connect`、`/connect/submit`、`/v2/auth/elicit/{eid}/token` 三端点 | 小(复用现有 auth) |
| `eid` 绑定 + 短 TTL + 一次性 token 回交 | 中(本设计的核心) |
| web 部署的 session/sub 防钓鱼校验 | 中(随 06-15 OAuth 一起做) |

**决策:gated。** 现在保持 `_elicit_url() → None` 的 stub;**等做托管网页版(或出现「无终端 + 仅 elicit」的真实用户)时再建**。届时:网关上三端点 + 一页 + 替换 #1 的 `TODO(#2)` 轮询段,即可让 Codex/Cursor 这类客户端获得与 card 同等安全的连接体验。

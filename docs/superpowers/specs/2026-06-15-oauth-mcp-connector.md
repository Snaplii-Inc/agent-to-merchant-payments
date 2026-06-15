# 上线 OAuth 架构 — MCP Connector(托管 HTTP)

**日期:** 2026-06-15
**状态:** 设计 / 上线阶段实现清单
**适用:** 把同一份 MCP server 托管成公网 HTTP 端点,供 Claude(网页/手机)、ChatGPT
等**跑不了本地进程**的客户端通过 connector 接入。
**不适用:** 本地 stdio(Claude Desktop)——那条用 API key 卡片
(`2026-06-10-mcp-apps-confirmation-channel.md` 同款 off-model 输入),无需 OAuth。

---

## 0. TL;DR

- 托管 HTTP 端点对全世界开放,必须回答"**谁、授权了什么、能否撤销**"→ OAuth 2.1。
- **核心认知:MCP connector 场景下,OAuth 客户端是 host(Claude/ChatGPT),不是我们。**
  host 自己开浏览器、做 PKCE、换 token、存 token、每个请求带 `Bearer`。
- **我们只建两块:**①一个**授权服务器**(登录 + 同意 + 发 token);②让 MCP server 当
  **resource server**——校验进来的 bearer token,解析出账户,用该账户的余额/每日额度。
- **不要手搓 OAuth**:复用现有 Snaplii 身份 + 套成熟 OAuth provider(Ory Hydra /
  Keycloak / Auth0 / Okta)。
- 花钱的硬闸**始终是建 key 时设的每日限额**;OAuth 解决的是"公网请求的身份与授权",
  不是花钱上限。

---

## 1. 核心模型:host 是 OAuth 客户端

```
未授权请求 → 我们的 MCP server 返回 401 + WWW-Authenticate
        → 指向 protected-resource metadata(RFC 9728)
        → 指向我们的 authorization server metadata(RFC 8414)
host(Claude/ChatGPT)自动发现后:
        → (可选)动态注册自己(RFC 7591)
        → 开浏览器到【我们的授权页】→ 用户用 Snaplii 账户登录 + 同意 scope
        → host 拿 authorization code → 用 PKCE 换 token(host 存 token)
        → 之后每个 MCP 请求自动带 Authorization: Bearer <access_token>
我们的 MCP server:校验 bearer → 解析账户 → 用该账户额度执行
```

→ "客户端 code"对 Claude/ChatGPT **基本不用我们写**;我们建 server 端 + 校验。

---

## 2. 我们要建的两块

### A. 授权服务器(authorization server)
复用现有 Snaplii 登录,在前面加 OAuth 端点:

| 端点 | 作用 |
|---|---|
| `GET /authorize` | **授权页**:登录(复用现有 session)+ 同意屏(展示 scope)→ 发 `code` → 302 回跳 `redirect_uri?code=…&state=…` |
| `POST /token` | `code`→`access+refresh`;`refresh`→新 `access`;校验 PKCE / client |
| `GET /.well-known/oauth-authorization-server` | AS metadata(RFC 8414),客户端自动发现端点 |
| `POST /register`(MCP 常用) | 动态客户端注册(RFC 7591),让 host 自动拿 client_id |
| `POST /revoke` | 撤销 refresh/access token(RFC 7009) |

授权页本身就是一个网页:登录 + "Allow this app to access your Snaplii account?
`[balance:read, orders:write]` [Allow] [Deny]"。

### B. Resource server(我们的 MCP HTTP server)
- 暴露 protected-resource metadata(RFC 9728),指向 AS。
- 每个请求**校验 bearer token**(本地验签 JWT,或 introspect RFC 7662)。
- 把 token → Snaplii 账户;**所有花钱操作用这个账户**的余额 + 每日额度。
- 校验失败 → 401 + `WWW-Authenticate`,触发 host 走授权。

---

## 3. token:存什么 / 寿命 / 续期 / 撤销

| token | 寿命 | 存哪 | 用途 |
|---|---|---|---|
| `access_token` | 短(分钟~小时) | host 侧(我们不存) | 每个 MCP 请求带它 |
| `refresh_token` | 长 | host 侧(它的安全存储) | 静默换新 access,**无需用户再操作** |

- **第一个 refresh token** 是用户**登录+同意 → authorization code → 换 token** 那一步
  **一起发**的;不是用 API key 或别的密钥单独"请求"。
- **续期**:用 refresh token 自己(`grant_type=refresh_token`)换新 access;建议**轮换**
  (每次换新 refresh)。
- **撤销**:refresh token 可在 AS 侧单独吊销 → 这是"持久会话"该用 refresh token、
  **不该在本机存原始 API key** 的原因(可控、可撤、可轮换)。
- AS 侧存 refresh token 记录(哈希)+ 绑 `user/client/scope`,用于校验和撤销。
- 用户**密码从不存、从不经过客户端**——只在 Snaplii 授权页输入。

---

## 4. 我们**不**建的(host 替我们做)

- 开浏览器、PKCE 生成/校验、authorization code 换 token、token 存储、给请求附
  `Bearer`、过期自动 refresh —— 这些 Claude/ChatGPT 作为 OAuth 客户端全包了。
- 例外:**我们自己的 CLI/原生 app**(非 host)才需要写客户端 Authorization Code +
  PKCE(loopback 127.0.0.1 redirect);**terminal/无浏览器**用 device code flow(RFC 8628)。

---

## 5. 实现建议

1. **复用现有 Snaplii 身份**,别另起账户体系。
2. **别手搓 OAuth**——用 Ory Hydra / Keycloak / Auth0 / Okta;我们只写"登录 + 同意" UI。
3. **PKCE 强制**(OAuth 2.1 / MCP 要求),`code_challenge_method=S256`。
4. **动态客户端注册(RFC 7591)**:MCP host 常自动注册,省去手发 client_id。
5. **scope 设计**:至少区分 `balance:read` / `orders:write`,配合每日额度。
6. **支付类应用商店**:ChatGPT 审核 **no-auth 直接拒**,必须 OAuth + 验证域名 +
   隐私政策/条款。
7. **日志脱敏**:token / 密钥**绝不进日志**(本地 stdio 曾把 key 记进 MCP 传输日志,
   托管端必须避免)。
8. **传输加固**:`allowed_hosts`/CORS 收紧、DNS-rebinding 防护、声明 `_meta.ui.csp`。

---

## 6. 和 stdio / API key 的关系

| 客户端 | 认证 | 凭证存哪 |
|---|---|---|
| 本地 stdio(Claude Desktop) | **API key 卡片**(off-model 输入)→ 换 7 天 JWT | 本机 keychain + `~/.snaplii/config.json`,key 不存 |
| 托管 HTTP(Claude 网页/手机、ChatGPT) | **OAuth**(账户登录,无 API key) | access/refresh 在 **host 侧** |
| terminal / 无浏览器 | OAuth **device flow** | 本机 keychain |
| 纯程序无人 | client-credentials / 预置 token | server 侧 |

- **业务代码同一份**,运行时按客户端能力选认证路径,工具/卡片/canonical 逻辑不变。
- OAuth 模型下用户**根本不用 API key**——改成账户登录;两套是替代关系,按客户端选。

---

## 7. 上线 OAuth 检查清单

- [ ] 复用 Snaplii 身份,接入 OAuth provider(Hydra/Keycloak/…)
- [ ] `/authorize` `/token` `/register` `/revoke` + AS/PR metadata 可用
- [ ] 授权页(登录 + 同意屏 + scope 展示)
- [ ] MCP HTTP server 校验 bearer → 解析账户 → 用该账户额度
- [ ] PKCE 强制、refresh 轮换、撤销可用
- [ ] 日志脱敏、CORS/allowed_hosts、CSP
- [ ] device flow(terminal)、验证域名 + 隐私政策/条款(商店)
- [ ] 撤销 key/token 后,**在途 token 是否一并失效** —— 与后端确认(撤销延迟 ≤ JWT TTL)

---

**关联:** off-model 凭证输入见 `2026-06-10-mcp-apps-confirmation-channel.md`;
逐笔确认已废、每日额度为闸的决定见 memory `snaplii-no-per-transaction-confirmation`。

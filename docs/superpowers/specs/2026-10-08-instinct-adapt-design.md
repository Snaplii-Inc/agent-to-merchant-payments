# Instinct 环境适配设计

- 日期：2026-10-08
- 分支：`feat/instinct-adapt`
- 状态：待审阅
- 目标版本：CLI 与 MCP 均为 0.19.0

## 1. 目标和范围

在 Instinct 环境里，Snaplii 只通过 MCP 使用。安装完成后，Agent 不等用户开口就开始连接。连接时，Agent 在云浏览器里打开 Snaplii 连接页，调用 Instinct Vault 把已保存的 API key 填进页面，然后提交。API key 不经过聊天、不经过模型，也不经过 Snaplii 的 MCP 进程。会话令牌只由 MCP 进程取回。

不在本次范围内：

- 不改网关。连接页、提交接口、取令牌接口都保持现状。
- Muse 和其他宿主的行为不变。
- 不改会话存储策略。
- 不发 PyPI 候选包。Instinct 从 GitHub 安装，合并到 main 即发布。

## 2. 已确认的决策

| 编号 | 决策 |
|---|---|
| 检测 | 存在名字以 `INSTINCT_` 开头的环境变量，且未检测到 Muse，即判定为 Instinct。前缀区分大小写，变量值不参与判断。 |
| Q1 | Instinct 读 README，从 GitHub 安装 MCP。 |
| Q2 | Vault 填充由 Agent 显式触发：对页面输入框调用填充动作并指定条目，值直接注入字段，Agent 看不到。key 最初由用户通过 Vault 的加密链接保存。 |
| Q3 | 取令牌由 MCP 完成。Agent 第二次调用 `snaplii_connect` 时传回一次性 ID，MCP 直接请求取令牌接口。 |
| Q4 | Connect 按钮由 Agent 点击。 |
| Q6 | 会话存储保持现状：有系统钥匙串用钥匙串，否则存在进程内存。 |
| Q7 | CLI 只保留帮助、版本、`update` 和 `config` 子命令。MCP 的 `snaplii_init` 拒绝执行。`snaplii_connect` 去掉卡片界面。Skill 的 Auth 章节加一句 Instinct 改用 MCP。 |
| Q8 | 允许连接任何已配置的网关，以便在 staging 测试。 |
| Q9 | 接受一次性 ID 进入模型上下文的风险，写进文档。 |
| Q10 | 状态和诊断输出列出匹配到的 `INSTINCT_` 变量名，不列变量值。 |
| Q12 | Vault 工具名未知，指令写能力描述，真实验证时补上确切调用。 |
| Q13 | 先尝试填充。条目不存在时生成加密链接让用户保存，然后重试一次。页面提示 key 无效时，用加密链接替换条目一次，仍失败就停止。 |
| Q15 | "装完立即连接"同时写进 README 的 Instinct 分支和 MCP 的 instructions。 |
| Q16 | 安装后立即连接一次。之后收到 Snaplii 业务请求而没有有效会话时自动连接。不在每个会话开头连接。 |
| Q17 | 合并前，在真实 Instinct 里从功能分支安装并走通全流程。 |
| Q18 | 生产网关用条目 `Snaplii API Key`。其他网关用 `Snaplii API Key <网关主机>`，例如 `Snaplii API Key aipay.stage.snaplii.com`。 |

## 3. 现有事实

这些事实来自 `snaplii-agent-gateway` 的连接控制器和线上页面：

- 连接页地址是网关的 `/connect?eid=<一次性 ID>`。staging 和生产页面相同。
- 页面上只有一个密码输入框，id 为 `apikey`，标签是 "Snaplii API key"，还有一个 id 为 `connect` 的按钮。点击时，页面用普通 JavaScript 读取输入框的值，然后提交到 `/connect/submit`。
- 提交成功后，网关签发令牌，以一次性 ID 为键暂存 2 分钟。页面显示 "Connected"。
- 取令牌接口是 `GET /v2/auth/elicit/{eid}/token`，只凭一次性 ID，不需要其他凭据。令牌就绪时返回 200 和令牌，只能取一次。未就绪、不存在或过期时返回 204。
- 一次性 ID 必须是 16 到 64 位十六进制字符。
- 网关用 `agent-` 加 key 的 MD5 前 8 位作为 agent ID，与 MCP 现有的派生方式一致。
- MCP 已有取令牌的轮询循环：最多 20 次，每次间隔 1.5 秒。还有 `accept_connect_token`，负责把取回的令牌提交为会话。

## 4. 设计

### 4.1 检测：`snaplii/auth.py`

新增 `instinct_environment_status(environ=None) -> dict`：

- 收集 `environ` 中以 `INSTINCT_` 开头的变量名，排序后返回。
- `detected` 为真的条件：至少有一个匹配的变量名，并且 Muse 检测结果为假。
- 返回值形如 `{"detected": bool, "reason_code": str, "env_names": [...]}`。`reason_code` 取以下三个值之一：`instinct_env_present`、`muse_takes_precedence`、`instinct_env_absent`。

新增 `detect_instinct() -> bool`，作为上面函数的简写。

### 4.2 认证状态与动作

`ConfigStore.auth_status` 的 `host` 字段增加取值 `instinct`，判定顺序是 muse、instinct、unknown。host 为 instinct 时，结果里额外带上 `instinct_env`，列出匹配到的变量名。

`build_auth_action` 在 host 为 instinct 时，处理逻辑插在 Muse 安全分支之前：

- `ready` 返回空，各类停止和稍后重试的状态，与现有行为一致。
- 其余需要认证的状态返回下面的动作：

```json
{"type": "call_mcp_tool", "tool": "snaplii_connect", "arguments": {},
 "instruction": "<INSTINCT_AUTH_INSTRUCTION>"}
```

- 不做生产网关限制，以满足 Q8。

### 4.3 CLI 限制：`snaplii/cli.py`

在命令组入口加一道检查：host 为 instinct 时，只放行 `help`、`update` 和 `config` 子命令。`--version` 由 click 在进入命令组之前处理，不受影响。其他子命令，包括 `init`，一律抛出 `AuthError`：

- 消息："In Instinct, Snaplii runs through its MCP tools. Use snaplii_connect."
- `auth_state` 为 `mcp_required`，`reason_code` 为 `instinct_requires_mcp`。
- `next_action` 采用 4.2 的动作。

这道检查必须放在创建网关客户端之前。这样即使配置损坏，也会先得到明确的提示。

### 4.4 MCP 服务器：`mcp-server/server.py`

**instructions。** 模块加载时调用新函数 `_server_instructions()`。检测到 Instinct 时，在现有 instructions 后面追加 Instinct 段落，内容就是 `INSTINCT_AUTH_INSTRUCTION`。

**工具列表。** `list_tools` 在 Instinct 下做三处调整：

- `snaplii_connect` 去掉 `_meta.ui`，不再弹出卡片。
- 工具描述改为介绍浏览器流程，输入参数增加可选的 `eid`。
- `snaplii_init` 和 `snaplii_submit_api_key` 从列表中移除。`snaplii_init` 的描述会引导无卡片的客户端让用户在聊天里粘贴 key，所以必须隐藏。这一条来自 Codex 第一轮审阅。

**`snaplii_connect` 在 Instinct 下的行为：**

- 已连接时，沿用现有的 `already_connected` 返回。
- 不带 `eid` 调用时，生成新的一次性 ID，返回：

```json
{"status": "open_in_browser",
 "connect_url": "<网关>/connect?eid=<eid>",
 "eid": "<eid>",
 "vault_entry": "Snaplii API Key",
 "field": "the password input labelled 'Snaplii API key' (id apikey)",
 "next": "<简短步骤，指向 instructions>"}
```

- 带 `eid` 调用时，先校验格式，不合法就返回 `invalid_eid`。合法则运行现有的轮询循环。拿到令牌就调用 `accept_connect_token`，返回 `authenticated` 和认证状态。没拿到就返回 `pending`，提示 Agent 检查页面。如果页面显示 Connected 已超过 2 分钟，就不带 `eid` 重新开始，只重来一次。
- 任何返回都不提示粘贴 key，也不提示去终端。

连接页地址沿用现有的 `_elicit_url()`。它优先使用 `SNAPLII_ELICIT_URL` 环境变量或配置项，否则使用 `<网关>/connect`。

**拒绝直接传 key。** 在 Instinct 下，`snaplii_init` 和 `snaplii_submit_api_key` 都返回错误，并附上 4.2 的动作，不调用登录接口。

**Muse 分支不变。** `snaplii_connect` 在 Muse 下返回认证状态的现有逻辑保持原样。

### 4.5 Vault 条目命名

新增 `instinct_vault_entry(base_url) -> str`：

- 规范化后的地址等于生产网关，且没有路径前缀时，返回 `Snaplii API Key`。
- 其他情况返回 `Snaplii API Key ` 加上网关主机。主机按规范化后的 origin 去掉协议得到，非默认端口要带上。

### 4.6 指令文字：`INSTINCT_AUTH_INSTRUCTION`

放在 `snaplii/auth.py`，作为唯一来源。下面是草稿，实现时可以调整措辞，但规则不变：

```text
Instinct: in Instinct, Snaplii runs only through the Snaplii MCP tools. Do not use
the snaplii CLI for authentication or business operations, never call
snaplii_init, and never request the Snaplii token endpoint yourself.

When to connect: right after you install and register the Snaplii MCP server,
connect immediately; the user does not need to ask. If the new tools only become
available in a new session, tell the user and connect at the start of that
session. Later, whenever the user makes a Snaplii request and
snaplii_config_show reports has_valid_token=false, connect first without asking
the user to log in. Do not connect at the start of unrelated conversations.
Honor an explicit install-only or connect-later request.

Connection flow:
1. Call snaplii_connect with no arguments. It returns connect_url, eid and
   vault_entry.
2. Open connect_url in your cloud browser. Use the Instinct vault fill action on
   the password field labelled "Snaplii API key" (id apikey), selecting the
   vault entry named exactly vault_entry. Never read, print or copy the field.
3. If the vault reports that the entry does not exist, explain to the user in
   their language: open the Snaplii App and sign in, go to More -> Payment
   Methods -> AI Payment Management -> + New API Key, set a name, permissions
   and a spending limit, then create and copy the key; it is shown only once.
   Then create the vault's encrypted submission link for that entry and send it
   to the user. They paste the key only into that link, never into the chat.
   After they confirm, retry the fill once.
4. Click the Connect button. When the page shows "Connected", immediately call
   snaplii_connect with {"eid": "<eid>"}; the token expires 2 minutes after
   submission. Then confirm has_valid_token=true with snaplii_config_show.
   For an installation, report "Installed and connected"; otherwise continue
   the user's task.
5. If the page says the key was not accepted, tell the user the stored key was
   rejected, send the encrypted link once to replace the entry, and retry once.
   If it fails again, stop and report.
6. If snaplii_connect returns pending, check the page. If more than 2 minutes
   passed since "Connected", start over once without eid.

Select the vault actions from your actual capabilities; do not invent tool
names. If the vault cannot fill fields or create links, explain the limitation
and stop. Authentication recovery never authorizes replaying a payment.
```

### 4.7 README 与 Skill 文档

**README。** 在 "MCP Server" 一节加一个 Instinct 分支，内容是：

- 克隆仓库，以可编辑模式安装 `snaplii-cli` 和 `mcp`。
- 把 `mcp-server/server.py` 注册为 stdio MCP 服务器。
- 跳过 `snaplii init`。
- 注册完成后，立即按 MCP instructions 的流程连接。如果工具要到新会话才可用，就告诉用户，在新会话里连接。
- 说明一次性 ID 风险，见第 6 节。

**Skill 文档。** `render_auth_skill_block` 在 "Other agents" 之前加一个 Instinct 小节：在 Instinct 下改用 Snaplii MCP 并按 MCP instructions 连接，不使用 CLI。然后运行同步脚本，更新 4 个 Skill 文件。`dist/` 下的候选包不动。

### 4.8 诊断输出

- `snaplii config doctor` 增加 `instinct` 字段，内容是 `instinct_environment_status()` 的返回值。
- 配置无法读取时，doctor 会输出一份兜底的认证状态。兜底结果里的 host 同样按 muse、instinct、unknown 的顺序判定。
- `snaplii config show` 和 `snaplii_config_show` 通过 4.2 的 `host` 和 `instinct_env` 字段体现检测结果。

## 5. 端到端流程

1. 用户让 Instinct 安装 Snaplii。Agent 按 README 的 Instinct 分支克隆、安装并注册 MCP。
2. Agent 立即调用 `snaplii_config_show`。结果是 `host=instinct`，`has_valid_token=false`。
3. Agent 不带参数调用 `snaplii_connect`，拿到连接页地址、一次性 ID 和条目名。
4. Agent 在云浏览器里打开连接页，对 API key 输入框调用 Vault 填充。
   - 条目不存在：说明如何在 App 里创建 key，发出加密链接，用户保存后重试一次填充。
5. Agent 点击 Connect，页面显示 Connected。
   - 页面提示 key 无效：替换条目一次，然后从第 4 步重试。
6. Agent 带上一次性 ID 调用 `snaplii_connect`。MCP 请求取令牌接口，提交会话，返回 `authenticated`。
7. Agent 用 `snaplii_config_show` 确认已连接，然后报告 "Installed and connected"。
8. 之后 MCP 重启导致会话丢失时，下一次 Snaplii 业务请求会从第 3 步自动重连。

## 6. 安全

- **API key。** key 只存在 Vault 里，由 Vault 注入页面，再由页面直接提交给网关。模型、聊天记录和 MCP 进程都接触不到它。
- **会话令牌。** 令牌只由 MCP 取回。指令禁止 Agent 自己请求取令牌接口。
- **一次性 ID。** 一次性 ID 出现在链接里，会进入模型上下文和对话记录。用户提交后的 2 分钟内，任何读到它的人都能抢先取走令牌。这时 MCP 会拿到 `pending`，失败是可见的。能读到对话的只有宿主，而 Vault 本来就在宿主手里，所以这个风险可以接受，写进 README。
- **误判。** 任何名字以 `INSTINCT_` 开头的变量都会触发 Instinct 模式。诊断输出会列出是哪些变量。Muse 优先，不受影响。

## 7. 错误处理

| 情况 | 行为 |
|---|---|
| CLI 在 Instinct 下执行被拦截的命令 | `AuthError`，`next_action` 指向 `snaplii_connect` |
| MCP `snaplii_init` 或 `snaplii_submit_api_key` 在 Instinct 下被调用 | 返回错误和同一个动作，不发起登录 |
| `eid` 格式不合法 | `invalid_eid`，不请求网关 |
| 轮询结束仍未拿到令牌 | `pending`，附重新开始的条件 |
| 取令牌时网关连接失败 | 计入轮询，最终返回 `pending` |
| 令牌提交或回读失败 | 沿用 `accept_connect_token` 现有的 `session_cache_failed` 错误 |

## 8. 测试计划

新增 `tests/test_instinct.py`，覆盖：

- **检测。** 有前缀、无前缀、小写前缀、空值变量，以及与 Muse 同时存在时 Muse 优先。
- **条目命名。** 生产网关、staging、带端口的本地网关。
- **认证动作。** Instinct 下各个状态产生的动作，以及不受生产网关限制。
- **CLI。** 放行 `help`、`update`、`config show`、`config doctor` 和 `--version`。拦截 `init` 和全部业务命令，并且不发出任何 HTTP 请求。
- **MCP 工具列表。** Instinct 下没有卡片元数据、提交工具和 `eid` 参数的变化。非 Instinct 下保持原样。
- **MCP 连接。** 不带 `eid` 时返回链接和条目名。带 `eid` 时，用模拟轮询覆盖成功和等待中两种情况。`eid` 不合法时被拒绝。所有返回都不含粘贴 key 或终端的提示。
- **MCP 拒绝。** `snaplii_init` 和提交工具都拒绝执行，并且不调用登录接口。
- **instructions。** 只在 Instinct 下追加 Instinct 段落。
- **诊断。** doctor 和 config show 列出变量名，不列变量值。

现有测试的调整：

- 在 `tests/conftest.py` 加一个自动生效的 fixture，清除所有 `INSTINCT_` 变量，防止开发机或 CI 环境影响现有测试。
- 运行同步脚本后，Skill 文档测试应保持通过。
- 业务认证矩阵测试增加 Instinct 场景：CLI 被拦截，MCP 返回指向 `snaplii_connect` 的动作。

## 9. 发布与真实验证

- 版本升到 0.19.0：`snaplii-cli/pyproject.toml`、`snaplii/__init__.py`、`mcp-server/pyproject.toml` 及其对 CLI 的最低版本依赖。CHANGELOG 新增条目。
- 合并前，在真实 Instinct 里从 `feat/instinct-adapt` 分支安装，记录以下结果：
  1. `snaplii_config_show` 返回 `host=instinct`，并列出变量名。这能确认环境变量传到了 MCP 进程。
  2. 安装后 Agent 自动开始连接，不需要用户提示。
  3. 条目缺失时，Agent 发出加密链接。用户保存后，填充成功。
  4. 点击 Connect 后，第二次调用返回 `authenticated`。
  5. 新会话里，第一次业务请求会自动重连。
  6. 把 Vault 填充和加密链接的确切工具名与参数补进指令。
- 用 staging 网关和 staging 测试 key 完成以上验证。

## 10. 未决事项

真实验证会回答这些问题。结果可能需要回头修改设计：

- Instinct 启动 MCP 时，会不会把 `INSTINCT_` 变量传下去。如果不会，MCP 一侧检测不到，需要另找信号。
- 新注册的 MCP 工具是不是要到新会话才可用。
- Vault 填充和加密链接的确切工具名与参数。

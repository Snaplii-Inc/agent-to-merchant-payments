# Snaplii Muse 候选版安装与验收

此包包含版本配套的 CLI、可选 MCP 和 skill。Muse 自动输入框的真实效果仍待你在 Muse 中验收；工具名不可见不影响观察结果。只查询余额，不购买、不支付、不转账。

## 安装（不会登录）

将整个压缩包上传给 Muse，解压后进入其中的目录。告诉 Muse：

> 请安装这个 Snaplii 候选包。先阅读 INSTALL.md，运行安装器，加载随包的 snaplii-cli skill。保留候选版本，暂时不要连接账户或索取 API key。

```bash
python3 install.py --verify-only
python3 install.py
```

需要 Python 3.9+、venv/pip 和下载依赖的网络权限。安装器在包目录中新建 `.venv`，不会覆盖全局 CLI、已有环境或账户配置；已有 `.venv` 时用 `--venv /path/to/new-environment` 指定新位置。只在需要 MCP 的客户端上使用 `python3 install.py --with-mcp`（Python 3.10+）；Muse 测试优先使用 CLI。

安装结果给出 CLI 的绝对路径和 `skills/snaplii-cli/SKILL.md` 路径。Muse 必须读取并使用这份 skill；CLI 安装本身不等于 skill 已加载。通过 Muse 实际提供的 skill 安装机制安装该文件；若没有此机制，在测试会话中完整读取它，并如实记录为“会话内加载”。不要猜测 Muse 的安装目录。可选的 autopilot skill 位于相邻目录，仅在需要浏览器下单时使用。

后续示例使用默认环境。若自定义了 `--venv`，使用安装结果中的 CLI 路径。

```bash
.venv/bin/snaplii --version
```

版本应与 `MANIFEST.json` 一致。不要运行 `pip install -U snaplii-cli` 替换候选包；该版本的 `snaplii update` 会保持候选版不变。校验和用于检测传输损坏，不代替发行方身份验证。

## 隔离测试配置

在测试用的 Muse 账号/工作区中进行，不删除日常配置或已存的 key。新建聊天不一定意味着凭证为空。为所有测试命令使用同一个新配置路径，例如解压目录下的 `test-state/config.json`：

```bash
export SNAPLII_CONFIG_PATH="$PWD/test-state/config.json"
.venv/bin/snaplii config doctor
.venv/bin/snaplii config show
```

Muse 每次启动新的 shell/进程时，都要保留同一个 `SNAPLII_CONFIG_PATH` 和候选 CLI 路径。该设置只隔离 Snaplii session，不清除 Muse secure credential store。使用专用测试凭证，API key 只填写在 Muse 原生安全输入框中。

`config doctor` 不登录、不索取 key、不发余额请求。预期 `muse.detected=true`，状态 `host=muse`、`credential_storage="config file"`。若识别失败，保留脱敏诊断并停止本轮自动路径验收；不要伪造目录、权限或环境标记。原有登录回退仍可由用户另行明确选择，但不能把回退成功记为 Muse 自动路径通过。

## 黑盒验收

Muse 先读完随包 skill。用户只发自然任务，不提醒它“打开安全存储”，不提供内部工具名。

| 场景 | 操作 | 通过条件 |
|---|---|---|
| 仅安装 | 按上面的安装请求操作 | 不弹凭证输入框、不登录；明确区分安装完成与连接完成 |
| 首次使用 | 专用环境中没有 Snaplii key 或 session 时，说“查一下我的 Snaplii 余额” | 自动打开原生安全凭证输入框，不要求聊天粘贴 key，也不要求用户说触发短语 |
| 取消 | 取消输入框 | 停止，无重复弹窗、无自动回退、无余额查询 |
| 提交 | 再次要求连接，在输入框填写有效测试 key | Muse 初始化，`has_valid_token=true`，真实余额查询成功；不要求用户提供 agent ID |
| 再次查询 | 说“再查一次余额”，在新的 CLI 进程中执行 | 不再弹框，直接查询；仍是同一 agent ID、同一 session |
| 已有 key | 另用新的 Snaplii 测试配置路径，但保留测试账号中的 host key | 直接使用已存 key 初始化，不要求重新输入 |

只看到“没有弹窗”不能证明没有重新交换 token。若有可用的脱敏请求计数或网关日志，检查第二次查询只有余额请求、没有 token exchange；不可见时记为“未验证”，不要猜测。

过期、服务不可用、无效 key 等场景只在隔离测试配置/账号中进行。过期后应复用 host key；取消/拒绝立即停止；安全存储不可用时，先说明区别、等用户选择，再执行 `snaplii init --legacy-auth`。使用隐蔽终端输入，API key 不进入命令行参数或日志。未识别为 Muse 且没有 keychain 的环境，必须由用户另行同意 `SNAPLII_ALLOW_INSECURE=1` 文件缓存才能跨 CLI 进程复用；不可自动设置它。

## 记录与撤回

保留：候选版本、日期、对话及空白输入框截图、`config doctor` / `config show` 的安全输出、每项通过/失败/未验证。实际工具名和参数看不到时记录“不可见”；不要提交 API key、token、surrogate 或完整 config.json。

要停止测试，退出候选 `.venv` 并恢复原来的 CLI/skill 选择。候选安装没有覆盖全局包。隔离 session 和 Muse 中的测试凭证是两项不同数据；仅在明确决定清理测试数据时分别处理，不清除日常凭证。

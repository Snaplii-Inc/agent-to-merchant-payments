# Snaplii Muse 候选版安装与验收

此包包含版本配套的 CLI、可选 MCP 和 skill。Muse 自动输入框的真实效果仍待你在 Muse 中验收；工具名不可见不影响观察结果。安装连接完成后即停止，不用余额查询验证安装；后续由用户单独请求时才查询余额。不购买、不支付、不转账。

## 准备隔离测试环境

在测试用的 Muse 账号/工作区中进行，不删除日常配置或已存的 key。新建聊天不一定意味着凭证为空，也不能据此认定是首次安装。首次安装场景应使用确实尚未进行过 Snaplii 安装引导的测试环境。

将整个压缩包上传给 Muse，解压后进入其中的目录。在加载 skill 及进行账户连接前，为所有测试命令设置同一个新的配置路径，例如：

```bash
export SNAPLII_CONFIG_PATH="$PWD/test-state/config.json"
```

Muse 每次启动新的 shell/进程时，都要保留同一个 `SNAPLII_CONFIG_PATH` 和候选 CLI 路径。该设置只隔离 Snaplii session，不清除 Muse secure credential store。使用专用测试凭证，API key 只填写在 Muse 原生安全输入框中。

## 让 Muse 首次安装

告诉 Muse：

> 请安装这个 Snaplii 候选包。先阅读 INSTALL.md，按本文使用隔离测试配置，运行安装器，加载随包的 snaplii-cli skill。保留候选版本，不查询余额、不购买、不支付、不转账。

不要额外提示“连接账户”或“打开安全输入框”：本场景要观察 Muse 是否会依据 skill 的首次安装指令自行继续连接。安装器本身不会登录；安装后的连接由 Muse 执行，单纯下载文件或运行安装器不等于完成此流程。

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

## 检查环境与连接状态

```bash
.venv/bin/snaplii config doctor
.venv/bin/snaplii config show
```

`config doctor` 不登录、不索取 key、不发余额请求。预期 `muse.detected=true`，状态 `host=muse`、`credential_storage="config file"`。若识别失败，保留脱敏诊断并停止本轮自动路径验收；不要伪造目录、权限或环境标记。原有登录回退仍可由用户另行明确选择，但不能把回退成功记为 Muse 自动路径通过。

只有 `has_valid_token=true` 才能报告“已安装，已连接”。输入取消、被拒绝或初始化失败时保留安装，报告“已安装，尚未连接”及原因；不继续业务操作。连接成功不代表 API key 拥有所有购买或转账权限，权限和消费限额仍由用户在 App 中选择。

## 黑盒验收

Muse 先读完随包 skill。用户只发自然任务，不提醒它“打开安全存储”，不提供内部工具名。需要保持取消或安装历史的场景在同一对话中连续进行；不要用清除 session 假装首次安装。

| 场景 | 操作 | 通过条件 |
|---|---|---|
| Muse 首次安装 | 专用环境中没有 Snaplii key 或 session 时，按上面的安装请求操作 | 安装后自动进入连接，给出 App 获取 key 的指引并打开原生安全输入框；不要求聊天粘贴 key，也不要求用户说触发短语 |
| 安装时提交 | 在该输入框填写有效测试 key | Muse 初始化并检查 `has_valid_token=true`，报告已安装、已连接后停止；不查询余额，不要求用户提供 agent ID |
| 取消或拒绝 | 取消输入框或拒绝凭据访问 | 保留安装，报告尚未连接；当前任务中无重复弹窗、无自动回退、无余额查询 |
| 取消后检查状态 | 在同一对话中仅要求查看配置、重新加载 skill 或检查安装 | 不重新索取 key；这些行为不是新的连接请求 |
| 取消后新请求 | 用户新发起“连接 Snaplii”或“查一下我的 Snaplii 余额” | 允许一次新的连接尝试；只有余额请求在连接成功后才执行余额查询 |
| 明确稍后连接 | 首次安装请求中明确说“仅安装，暂不连接” | 不弹框、不登录；后续业务请求仍必须先完成认证 |
| 非 Muse 或未识别环境 | 在其他 agent 中安装，或 Muse 的状态不是 `host=muse` | 不因安装而发起连接；未识别环境说明原因，不伪造标记 |
| 更新或重装 | 已有安装历史（包括取消过引导）时更新、重装或再读 skill | 不因这些动作重新索取 key；没有 session 本身不等于首次安装 |
| 第二份 skill | 在同一连接配置下安装 autopilot skill；已有成功、取消或可见的进行中连接 | 复用已知结果或等待现有尝试，不从第二份 skill 再弹一个框 |
| 初始化失败 | 在隔离环境中测试拒绝的 key、网络故障或缓存失败 | 保留安装并说明连接失败，不报告已连接，不循环索取 key；仅允许用户新请求触发重试 |
| 首次业务兜底 | 用户此前仅下载文件或明确推迟连接，之后说“查一下我的 Snaplii 余额” | 先完成认证，再查询余额；不因错过安装引导而跳过认证 |
| 再次查询 | 说“再查一次余额”，在新的 CLI 进程中执行 | 不再弹框，直接查询；仍是同一 agent ID、同一 session |
| 已有 session / key | 在真正的首次安装场景中，预先具备有效 session 或已存测试 key | 有效 session 直接复用；仅有 key 则用它初始化，不要求重新输入 |

首次与重复触发由 Muse 根据可见的安装及对话上下文判断。没有持久化安装引导记录或跨任务锁，因此跨对话、并发任务不保证严格只触发一次；若观察到重复弹窗，应记录下来，不能把上述单流程验收当作并发保证。

只看到“没有弹窗”不能证明没有重新交换 token。若有可用的脱敏请求计数或网关日志，检查第二次查询只有余额请求、没有 token exchange；不可见时记为“未验证”，不要猜测。

过期、服务不可用、无效 key 等场景只在隔离测试配置/账号中进行。过期后应复用 host key；取消/拒绝立即停止；安全存储不可用时，先说明区别、等用户选择，再执行 `snaplii init --legacy-auth`。使用隐蔽终端输入，API key 不进入命令行参数或日志。未识别为 Muse 且没有 keychain 的环境，必须由用户另行同意 `SNAPLII_ALLOW_INSECURE=1` 文件缓存才能跨 CLI 进程复用；不可自动设置它。

## 记录与撤回

保留：候选版本、日期、对话及空白输入框截图、`config doctor` / `config show` 的安全输出、每项通过/失败/未验证。实际工具名和参数看不到时记录“不可见”；不要提交 API key、token、surrogate 或完整 config.json。

要停止测试，退出候选 `.venv` 并恢复原来的 CLI/skill 选择。候选安装没有覆盖全局包。隔离 session 和 Muse 中的测试凭证是两项不同数据；仅在明确决定清理测试数据时分别处理，不清除日常凭证。

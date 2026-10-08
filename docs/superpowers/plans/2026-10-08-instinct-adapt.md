# Instinct 环境适配 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Instinct 环境里让 Snaplii 只通过 MCP 工作，并通过 Instinct Vault 填充连接页完成登录，API key 不经过聊天、模型和 MCP 进程。

**Architecture:** 检测、条目命名和指令文字集中在 `snaplii/auth.py`。认证状态在 `config_store.py` 里多出 `host=instinct`，所有认证动作统一指向 `snaplii_connect`。CLI 在命令组入口拦截。MCP 服务器在 Instinct 下调整 instructions 和工具列表，`snaplii_connect` 改为"第一次返回连接页链接，第二次凭一次性 ID 取令牌"的无状态流程。

**Tech Stack:** Python 3.9+，click 8，httpx，mcp 1.x 低层 Server API，pytest、pytest-httpx。

**Spec:** `docs/superpowers/specs/2026-10-08-instinct-adapt-design.md`

## Global Constraints

- 环境变量前缀严格为 `INSTINCT_`，区分大小写。变量值不参与判断，任何输出都只能出现变量名，不能出现变量值。
- Muse 优先：检测到 Muse 时，host 一律是 `muse`，Muse 的现有行为不变。非 Instinct 环境的行为不变。
- 生产网关的 Vault 条目名是 `Snaplii API Key`。其他网关是 `Snaplii API Key ` 加网关主机，非默认端口要带上，例如 `Snaplii API Key aipay.stage.snaplii.com`、`Snaplii API Key localhost:8080`。
- 在 Instinct 下，任何面向 Agent 的文字都不能提示粘贴 key 或去终端输入，也不能让 Agent 自己请求取令牌接口。
- 不改网关，不新增依赖，不改会话存储策略。
- 两个包的版本都升到 `0.19.0`，MCP 依赖 `snaplii-cli>=0.19.0`。
- 提交信息里不加任何 Claude 署名或 Co-Authored-By 行。
- 测试命令统一用下面这条，在仓库根目录运行。用 `--with-editable` 是为了避开 uv 缓存的旧构建：

```bash
uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest <targets> -q
```

- 基线：改动前全量测试为 437 个通过。每个任务结束时全量测试必须全部通过。

## Review Focus

1. 开发机或 CI 里碰巧有一个 `INSTINCT_` 变量，CLI 突然拒绝执行。用户应当能从错误消息里看到是哪些变量触发的。由 Task 3 的测试覆盖。
2. Agent 第二次调用时传回整个连接页链接，而不是单独的一次性 ID。应当仍然取对令牌。由 Task 5 的测试覆盖。
3. 第二次调用时网关连不上。应当返回 `pending`，不能崩溃，也不能退回到粘贴 key。由 Task 5 的测试覆盖。
4. 已经连接的情况下，Agent 又带着一次性 ID 调用。应当直接返回 `already_connected`，不去轮询。由 Task 5 的测试覆盖。
5. Instinct 里配置文件损坏。业务命令仍然返回清楚的"改用 MCP"提示，`config doctor` 仍然可用，并报告 `host=instinct`。由 Task 3 的测试覆盖。

---

### Task 1: 检测、条目命名和指令文字

**Files:**
- Modify: `snaplii-cli/src/snaplii/auth.py`，在 `MUSE_AUTH_INSTRUCTION` 常量结束之后、`def secure_entry_actions` 之前插入
- Modify: `tests/conftest.py`
- Create: `tests/test_instinct_auth.py`

**Interfaces:**
- Consumes: `auth.detect_muse()`、`auth.normalize_base_url()`、`auth.normalize_origin()`、`auth.DEFAULT_ORIGIN`，均为现有函数和常量。
- Produces:
  - `INSTINCT_ENV_PREFIX: str = "INSTINCT_"`
  - `INSTINCT_VAULT_ENTRY: str = "Snaplii API Key"`
  - `INSTINCT_AUTH_INSTRUCTION: str`
  - `instinct_env_names(environ=None) -> list[str]`：返回排序后的匹配变量名。
  - `instinct_environment_status(environ=None) -> dict`：返回 `{"detected": bool, "reason_code": str, "env_names": list[str]}`，`reason_code` 取 `instinct_env_present`、`muse_takes_precedence` 或 `instinct_env_absent`。
  - `detect_instinct() -> bool`
  - `instinct_vault_entry(base_url: str) -> str`

- [ ] **Step 1: 让所有测试默认不带 `INSTINCT_` 变量**

在 `tests/conftest.py` 末尾追加：

```python
@pytest.fixture(autouse=True)
def _no_instinct_environment(monkeypatch):
    """A stray INSTINCT_ variable on a developer machine or CI must not flip tests
    into Instinct mode; Instinct tests set their own variables."""
    for name in list(os.environ):
        if name.startswith("INSTINCT_"):
            monkeypatch.delenv(name)
```

- [ ] **Step 2: 写失败的测试**

创建 `tests/test_instinct_auth.py`：

```python
import pytest

from snaplii import auth


def test_prefix_variable_selects_instinct(monkeypatch):
    monkeypatch.setenv("INSTINCT_REGION", "")
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    assert auth.instinct_environment_status() == {
        "detected": True, "reason_code": "instinct_env_present",
        "env_names": ["INSTINCT_AGENT_ID", "INSTINCT_REGION"],
    }
    assert auth.detect_instinct() is True


def test_other_names_do_not_select_instinct(monkeypatch):
    monkeypatch.setenv("MY_INSTINCT_FLAG", "1")
    monkeypatch.setenv("instinct_lowercase", "1")
    assert auth.instinct_environment_status() == {
        "detected": False, "reason_code": "instinct_env_absent", "env_names": [],
    }
    assert auth.detect_instinct() is False


def test_muse_takes_precedence(monkeypatch, muse_filesystem):
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    status = auth.instinct_environment_status()
    assert status == {"detected": False, "reason_code": "muse_takes_precedence",
                      "env_names": ["INSTINCT_AGENT_ID"]}


def test_explicit_environment_returns_sorted_names_only():
    names = auth.instinct_env_names({"INSTINCT_B": "secret", "INSTINCT_A": "x", "OTHER": "y"})
    assert names == ["INSTINCT_A", "INSTINCT_B"]


@pytest.mark.parametrize("base_url,entry", [
    ("https://aipayment.snaplii.com", "Snaplii API Key"),
    ("https://aipayment.snaplii.com/", "Snaplii API Key"),
    ("https://aipay.stage.snaplii.com", "Snaplii API Key aipay.stage.snaplii.com"),
    ("http://localhost:8080", "Snaplii API Key localhost:8080"),
    ("https://aipayment.snaplii.com/gw", "Snaplii API Key aipayment.snaplii.com"),
])
def test_vault_entry_names(base_url, entry):
    assert auth.instinct_vault_entry(base_url) == entry


def test_instruction_covers_the_vault_flow_without_raw_key_entry():
    text = " ".join(auth.INSTINCT_AUTH_INSTRUCTION.split())
    for phrase in (
        "snaplii_connect", "vault_entry", "eid", "Connect", "2 minutes",
        "More → Payment Methods → AI Payment Management → + New API Key",
        "encrypted submission link", "has_valid_token=true", "never call snaplii_init",
        "Do not connect at the start of unrelated conversations",
    ):
        assert phrase in text
    assert "paste their Snaplii API key" not in text
```

- [ ] **Step 3: 运行测试，确认失败**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests/test_instinct_auth.py -q`
Expected: FAIL，报错 `AttributeError: module 'snaplii.auth' has no attribute 'instinct_environment_status'`

- [ ] **Step 4: 实现**

在 `snaplii-cli/src/snaplii/auth.py` 里，`MUSE_AUTH_INSTRUCTION` 的结束三引号之后、`def secure_entry_actions` 之前插入：

```python
INSTINCT_ENV_PREFIX = "INSTINCT_"
INSTINCT_VAULT_ENTRY = "Snaplii API Key"
INSTINCT_AUTH_INSTRUCTION = """Instinct: in Instinct, Snaplii runs only through the Snaplii MCP tools. Do not use
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
   their language: open the Snaplii App and sign in, go to More → Payment Methods → AI Payment Management → + New API Key,
   set a name, permissions and a spending limit, then create and copy the key;
   it is shown only once. Then create the vault's encrypted submission link for
   that entry and send it to the user. They paste the key only into that link,
   never into the chat. After they confirm, retry the fill once.
4. Click the Connect button. When the page shows "Connected", immediately call
   snaplii_connect with {"eid": "<eid>"}; the token expires 2 minutes after
   submission. Then confirm has_valid_token=true with snaplii_config_show.
   For an installation, report "Installed and connected"; otherwise continue
   the user's task.
5. If the page says the key was not accepted, tell the user the stored key was
   rejected, send the encrypted submission link once to replace the entry, and
   retry once. If it fails again, stop and report.
6. If snaplii_connect returns pending, check the page. If more than 2 minutes
   passed since "Connected", start over once without eid.

Select the vault actions from your actual capabilities; do not invent tool
names. If the vault cannot fill fields or create links, explain the limitation
and stop. Authentication recovery never authorizes replaying a payment."""


def instinct_env_names(environ=None) -> list[str]:
    """Names (never values) of the variables that signal Instinct."""
    source = os.environ if environ is None else environ
    return sorted(name for name in source if name.startswith(INSTINCT_ENV_PREFIX))


def instinct_environment_status(environ=None) -> dict:
    """Recognize Instinct by any INSTINCT_-prefixed variable, unless Muse is present.

    Like Muse detection, this is an environment hint, not an attestation.
    """
    names = instinct_env_names(environ)
    if not names:
        return {"detected": False, "reason_code": "instinct_env_absent", "env_names": []}
    if detect_muse().detected:
        return {"detected": False, "reason_code": "muse_takes_precedence", "env_names": names}
    return {"detected": True, "reason_code": "instinct_env_present", "env_names": names}


def detect_instinct() -> bool:
    return instinct_environment_status()["detected"]


def instinct_vault_entry(base_url: str) -> str:
    """Production keeps the plain entry name; other gateways never overwrite it."""
    if normalize_base_url(base_url) == DEFAULT_ORIGIN:
        return INSTINCT_VAULT_ENTRY
    return INSTINCT_VAULT_ENTRY + " " + urlsplit(normalize_origin(base_url)).netloc
```

这些函数调用的 `detect_muse`、`normalize_base_url` 和 `normalize_origin` 定义在文件后面。这没有问题，因为调用发生在运行时，那时模块已经加载完。

- [ ] **Step 5: 运行测试，确认通过**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests/test_instinct_auth.py -q`
Expected: PASS

- [ ] **Step 6: 全量测试**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests -q`
Expected: 全部通过。这一步只新增常量和函数，现有行为不变。

- [ ] **Step 7: Commit**

```bash
git add snaplii-cli/src/snaplii/auth.py tests/conftest.py tests/test_instinct_auth.py
git commit -m "feat(auth): detect Instinct and define its vault connect instruction"
```

---

### Task 2: 认证状态的 host 和认证动作

**Files:**
- Modify: `snaplii-cli/src/snaplii/auth.py`，函数 `build_auth_action`
- Modify: `snaplii-cli/src/snaplii/config_store.py`，方法 `ConfigStore.auth_status`
- Test: `tests/test_instinct_auth.py`

**Interfaces:**
- Consumes: Task 1 的 `instinct_env_names`、`INSTINCT_AUTH_INSTRUCTION`。
- Produces:
  - `auth_status()` 的 `host` 可能是 `"instinct"`。这时结果多一个 `instinct_env: list[str]` 字段。
  - `build_auth_action(state, host="instinct", ...)` 对所有需要认证的状态，包括新状态 `"mcp_required"`，都返回 `{"type": "call_mcp_tool", "tool": "snaplii_connect", "arguments": {}, "instruction": INSTINCT_AUTH_INSTRUCTION}`。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_instinct_auth.py` 顶部的 import 区补上：

```python
import asyncio
import json

import keyring
from keyring.backends.fail import Keyring

from snaplii.client import GatewayClient
from snaplii.config_store import ConfigStore
from test_business_auth_gate import OPERATIONS
```

然后在文件末尾追加：

```python
INSTINCT_ACTION = {"type": "call_mcp_tool", "tool": "snaplii_connect", "arguments": {},
                   "instruction": auth.INSTINCT_AUTH_INSTRUCTION}


@pytest.fixture
def instinct_store(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    return ConfigStore(tmp_path / "config.json", runtime="mcp")


def test_status_reports_instinct_host_and_names_without_values(instinct_store):
    state = instinct_store.auth_status(origin=auth.DEFAULT_ORIGIN)
    assert state["host"] == "instinct"
    assert state["instinct_env"] == ["INSTINCT_AGENT_ID"]
    assert state["next_action"] == INSTINCT_ACTION
    assert "synthetic-value" not in json.dumps(state)


def test_non_instinct_status_has_no_instinct_field(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    state = ConfigStore(tmp_path / "config.json", runtime="mcp").auth_status(origin=auth.DEFAULT_ORIGIN)
    assert state["host"] == "unknown"
    assert "instinct_env" not in state


def test_muse_host_wins_over_instinct_variables(tmp_path, monkeypatch, muse_filesystem):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    state = ConfigStore(tmp_path / "config.json", runtime="cli").auth_status(origin=auth.DEFAULT_ORIGIN)
    assert state["host"] == "muse"
    assert state["next_action"]["argv"][-1] == "--vault-auth"
    assert "instinct_env" not in state


@pytest.mark.parametrize("state", [
    "auth_required", "reauth_required", "credential_required", "invalid_key",
    "credential_lookup_failed", "secure_entry_unavailable", "mcp_required",
])
@pytest.mark.parametrize("origin", [auth.DEFAULT_ORIGIN, "https://aipay.stage.snaplii.com"])
def test_instinct_actions_point_to_connect_on_any_gateway(state, origin):
    assert auth.build_auth_action(state, host="instinct", origin=origin) == INSTINCT_ACTION


@pytest.mark.parametrize("state,expected", [
    ("ready", None),
    ("cancelled", {"type": "stop", "reason": "cancelled"}),
    ("session_cache_failed", {"type": "stop", "reason": "session_cache_failed"}),
    ("temporary_gateway_error", {"type": "retry_auth_later", "reason": "temporary_gateway_error"}),
])
def test_instinct_keeps_terminal_and_retry_actions(state, expected):
    assert auth.build_auth_action(state, host="instinct") == expected


@pytest.mark.parametrize("command,name,arguments", OPERATIONS, ids=[op[1] for op in OPERATIONS])
def test_mcp_business_tools_without_session_point_to_connect(
    instinct_store, monkeypatch, httpx_mock, command, name, arguments,
):
    import server
    client = GatewayClient(auth.DEFAULT_ORIGIN, instinct_store)
    monkeypatch.setattr(server, "_get_client", lambda: client)
    monkeypatch.setattr(server, "ConfigStore", lambda: instinct_store)
    monkeypatch.setattr(server, "_base_url", lambda: auth.DEFAULT_ORIGIN)
    monkeypatch.setattr(server, "_update_notice", lambda: None)
    result = json.loads(asyncio.run(server.call_tool("snaplii_" + name, arguments))[0].text)
    client._http.close()
    assert result["auth_state"] == "auth_required"
    assert result["next_action"] == INSTINCT_ACTION
    assert httpx_mock.get_requests() == []
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests/test_instinct_auth.py -q`
Expected: FAIL，host 断言得到 `"unknown"`，动作断言得到 `run_cli` 或 `offer_legacy`。

- [ ] **Step 3: 实现 `build_auth_action` 的 Instinct 分支**

在 `snaplii-cli/src/snaplii/auth.py` 的 `build_auth_action` 里，找到：

```python
    if state == "temporary_gateway_error":
        return {"type": "retry_auth_later", "reason": state}
    secure = host == "muse" or auth_method == "vault"
```

改成：

```python
    if state == "temporary_gateway_error":
        return {"type": "retry_auth_later", "reason": state}
    if host == "instinct":
        # Instinct connects only through the vault-filled connect page in MCP, on
        # whichever gateway is configured, so staging can be tested too.
        return {"type": "call_mcp_tool", "tool": "snaplii_connect", "arguments": {},
                "instruction": INSTINCT_AUTH_INSTRUCTION}
    secure = host == "muse" or auth_method == "vault"
```

- [ ] **Step 4: 实现 `auth_status` 的 host 判定**

在 `snaplii-cli/src/snaplii/config_store.py` 的 `auth_status` 里，找到：

```python
        host = "muse" if self._muse.detected else "unknown"
```

改成：

```python
        instinct_env = [] if self._muse.detected else auth.instinct_env_names()
        host = "muse" if self._muse.detected else "instinct" if instinct_env else "unknown"
```

再找到：

```python
        if auth.valid_agent_id(data.get("agent_id")):
            result["agent_id"] = data["agent_id"]
```

在它前面插入：

```python
        if host == "instinct":
            result["instinct_env"] = instinct_env
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests/test_instinct_auth.py -q`
Expected: PASS

- [ ] **Step 6: 全量测试**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests -q`
Expected: 全部通过。

- [ ] **Step 7: Commit**

```bash
git add snaplii-cli/src/snaplii/auth.py snaplii-cli/src/snaplii/config_store.py tests/test_instinct_auth.py
git commit -m "feat(auth): report the Instinct host and route its recovery to snaplii_connect"
```

---

### Task 3: CLI 拦截和诊断输出

**Files:**
- Modify: `snaplii-cli/src/snaplii/cli.py`
- Modify: `snaplii-cli/src/snaplii/commands/config.py`，函数 `config_doctor`
- Create: `tests/test_instinct_cli.py`

**Interfaces:**
- Consumes: Task 1 的 `instinct_environment_status`。Task 2 的 `build_auth_action("mcp_required", host="instinct")`。
- Produces:
  - Instinct 下，除 `config`、`help`、`update` 外的子命令都抛出 `AuthError`，字段为 `auth_state="mcp_required"`、`reason_code="instinct_requires_mcp"`，消息里带上触发的变量名。
  - `snaplii config doctor` 的输出多一个 `instinct` 字段。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_instinct_cli.py`：

```python
import json
import shlex
import sys

import click
import keyring
import pytest
from keyring.backends.fail import Keyring

from snaplii import auth, cli

LOCAL = ("config", "help", "update")


def _leaves(command, prefix=()):
    if isinstance(command, click.Group):
        return {path for name, child in command.commands.items()
                for path in _leaves(child, prefix + (name,))}
    return {" ".join(prefix)}


BLOCKED = sorted(path for path in _leaves(cli.main) if path.split()[0] not in LOCAL)


@pytest.fixture
def instinct_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.setenv("SNAPLII_CONFIG_PATH", str(tmp_path / "config.json"))
    monkeypatch.delenv("SNAPLII_BASE_URL", raising=False)
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    monkeypatch.setattr(cli, "check_for_update", lambda *args, **kwargs: None)
    return tmp_path / "config.json"


def _run(monkeypatch, capsys, command):
    monkeypatch.setattr(sys, "argv", ["snaplii", *shlex.split(command)])
    try:
        cli._cli()
        code = 0
    except SystemExit as exc:
        code = exc.code
    return code, capsys.readouterr()


def test_blocked_list_covers_init_and_business_commands():
    assert "init" in BLOCKED and "balance" in BLOCKED and "transfer create" in BLOCKED


@pytest.mark.parametrize("command", BLOCKED)
def test_cli_refuses_init_and_business_commands(instinct_cli, monkeypatch, capsys, httpx_mock, command):
    code, output = _run(monkeypatch, capsys, command)
    assert code == 1
    assert output.out == ""
    result = json.loads(output.err)
    assert result["auth_state"] == "mcp_required"
    assert result["reason_code"] == "instinct_requires_mcp"
    assert result["next_action"] == auth.build_auth_action("mcp_required", host="instinct")
    assert "INSTINCT_AGENT_ID" in result["message"]
    assert "synthetic-value" not in output.err
    assert httpx_mock.get_requests() == []


@pytest.mark.parametrize("command", ["help", "--version", "update", "config show", "config doctor", "config clear"])
def test_cli_keeps_local_commands(instinct_cli, monkeypatch, capsys, httpx_mock, command):
    code, output = _run(monkeypatch, capsys, command)
    assert code == 0
    assert output.err == ""
    assert output.out
    assert httpx_mock.get_requests() == []


def test_show_and_doctor_name_variables_without_values(instinct_cli, monkeypatch, capsys):
    _, output = _run(monkeypatch, capsys, "config show")
    shown = json.loads(output.out)
    assert shown["host"] == "instinct"
    assert shown["instinct_env"] == ["INSTINCT_AGENT_ID"]
    _, output = _run(monkeypatch, capsys, "config doctor")
    doctor = json.loads(output.out)
    assert doctor["instinct"] == {"detected": True, "reason_code": "instinct_env_present",
                                  "env_names": ["INSTINCT_AGENT_ID"]}
    assert doctor["authentication"]["host"] == "instinct"
    assert "synthetic-value" not in output.out


def test_corrupt_config_still_points_to_mcp_and_doctor_reports_instinct(
    instinct_cli, monkeypatch, capsys,
):
    instinct_cli.write_text("{not json")
    code, output = _run(monkeypatch, capsys, "balance")
    assert code == 1
    assert json.loads(output.err)["auth_state"] == "mcp_required"
    code, output = _run(monkeypatch, capsys, "config doctor")
    assert code == 0
    authentication = json.loads(output.out)["authentication"]
    assert authentication["auth_state"] == "session_cache_failed"
    assert authentication["host"] == "instinct"
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests/test_instinct_cli.py -q`
Expected: FAIL。被拦截的命令目前会返回 `auth_required`，doctor 输出里没有 `instinct` 字段。

- [ ] **Step 3: 实现 CLI 拦截**

在 `snaplii-cli/src/snaplii/cli.py` 里，把：

```python
from snaplii.client import GatewayClient
```

改成：

```python
from snaplii import auth
from snaplii.client import GatewayClient
```

把：

```python
from snaplii.exceptions import ConfigError, SnapliiCliError
```

改成：

```python
from snaplii.exceptions import AuthError, ConfigError, SnapliiCliError
```

把：

```python
_DEFAULT_BASE_URL = "https://aipayment.snaplii.com"
```

改成：

```python
_DEFAULT_BASE_URL = "https://aipayment.snaplii.com"
# Local setup and repair commands: they run without a gateway client, and they
# stay available in Instinct, where everything else goes through MCP.
_LOCAL_COMMANDS = ("config", "help", "update")
```

然后在 `main` 里找到：

```python
    if ctx.invoked_subcommand not in ("config", "help", "update"):
        # Repair commands must run even when the stored configuration is
```

改成：

```python
    if ctx.invoked_subcommand not in _LOCAL_COMMANDS:
        instinct = auth.instinct_environment_status()
        if instinct["detected"]:
            # Checked before reading configuration, so a broken config file
            # still yields this pointer instead of a configuration error.
            raise AuthError(
                "Instinct detected from " + ", ".join(instinct["env_names"])
                + ": Snaplii runs through its MCP tools here. Use snaplii_connect.",
                auth_state="mcp_required", reason_code="instinct_requires_mcp",
                next_action=auth.build_auth_action("mcp_required", host="instinct"))
        # Repair commands must run even when the stored configuration is
```

这样 Instinct 检查就在创建网关客户端之前，并且和它共用同一个条件。

- [ ] **Step 4: 实现 doctor 的 Instinct 字段**

在 `snaplii-cli/src/snaplii/commands/config.py` 的 `config_doctor` 里，找到：

```python
    muse = auth.muse_environment_status()
```

改成：

```python
    muse = auth.muse_environment_status()
    instinct = auth.instinct_environment_status()
```

找到：

```python
                  "host": "muse" if muse["detected"] else "unknown",
```

改成：

```python
                  "host": "muse" if muse["detected"] else "instinct" if instinct["detected"] else "unknown",
```

找到：

```python
    print_json({"version": version("snaplii-cli"), "muse": muse,
                "authentication": status})
```

改成：

```python
    print_json({"version": version("snaplii-cli"), "muse": muse, "instinct": instinct,
                "authentication": status})
```

- [ ] **Step 5: 运行测试，确认通过**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests/test_instinct_cli.py -q`
Expected: PASS

- [ ] **Step 6: 全量测试**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests -q`
Expected: 全部通过。

- [ ] **Step 7: Commit**

```bash
git add snaplii-cli/src/snaplii/cli.py snaplii-cli/src/snaplii/commands/config.py tests/test_instinct_cli.py
git commit -m "feat(cli): route Instinct to MCP and report its signal in config doctor"
```

---

### Task 4: MCP 的 instructions、工具列表和直接传 key 的拒绝

**Files:**
- Modify: `mcp-server/server.py`
- Create: `tests/test_instinct_mcp.py`

**Interfaces:**
- Consumes: Task 1 的 `detect_instinct`、`INSTINCT_AUTH_INSTRUCTION`。Task 2 的 `build_auth_action("mcp_required", host="instinct")`。
- Produces:
  - `_server_instructions() -> str`：Instinct 下返回 `_SERVER_INSTRUCTIONS + "\n\n" + INSTINCT_AUTH_INSTRUCTION`。
  - `_instinct_tools(tools: list[types.Tool]) -> list[types.Tool]`：去掉 `snaplii_submit_api_key`。把 `snaplii_connect` 的 `meta` 设为 None，替换描述，参数改为可选的 `eid`。
  - Instinct 下 `_authenticate()` 返回 `{"error": "mcp_connect_required", "auth_state": "mcp_required", "reason_code": "instinct_requires_vault_connect", "message": str, "next_action": dict}`，不调用登录。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_instinct_mcp.py`：

```python
import asyncio
import json

import pytest

import server
from snaplii import auth


@pytest.fixture
def instinct_env(monkeypatch):
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    monkeypatch.setattr(server, "_update_notice", lambda: None)


def _tools():
    return {tool.name: tool for tool in asyncio.run(server.list_tools())}


def test_instructions_gain_instinct_section_only_in_instinct(monkeypatch):
    assert auth.INSTINCT_AUTH_INSTRUCTION not in server._server_instructions()
    monkeypatch.setenv("INSTINCT_AGENT_ID", "synthetic-value")
    text = server._server_instructions()
    assert text.startswith(server._SERVER_INSTRUCTIONS)
    assert text.endswith(auth.INSTINCT_AUTH_INSTRUCTION)


def test_tool_list_is_unchanged_outside_instinct():
    tools = _tools()
    assert "snaplii_submit_api_key" in tools
    assert tools["snaplii_connect"].meta["ui"]["resourceUri"]
    assert tools["snaplii_connect"].inputSchema["properties"] == {}


def test_instinct_tool_list_drops_the_card_and_takes_an_eid(instinct_env):
    tools = _tools()
    assert "snaplii_submit_api_key" not in tools
    connect = tools["snaplii_connect"]
    assert connect.meta is None
    assert set(connect.inputSchema["properties"]) == {"eid"}
    assert connect.inputSchema["required"] == []
    assert "vault" in connect.description
    assert "card" not in connect.description.lower()


class _NoLoginClient:
    def login(self, *args, **kwargs):
        raise AssertionError("login must not be called in Instinct")


@pytest.mark.parametrize("tool", ["snaplii_init", "snaplii_submit_api_key"])
def test_instinct_refuses_raw_api_keys(instinct_env, monkeypatch, tool):
    monkeypatch.setattr(server, "_get_client", lambda: _NoLoginClient())
    text = asyncio.run(server.call_tool(tool, {"api_key": "snp_sk_live_SECRET123"}))[0].text
    result = json.loads(text)
    assert result["error"] == "mcp_connect_required"
    assert result["auth_state"] == "mcp_required"
    assert result["reason_code"] == "instinct_requires_vault_connect"
    assert result["next_action"] == auth.build_auth_action("mcp_required", host="instinct")
    assert "SECRET123" not in text
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests/test_instinct_mcp.py -q`
Expected: FAIL，报错 `AttributeError: module 'server' has no attribute '_server_instructions'`

- [ ] **Step 3: 实现 instructions**

在 `mcp-server/server.py` 里，把：

```python
app = Server("snaplii", instructions=_SERVER_INSTRUCTIONS)
```

改成：

```python
def _server_instructions() -> str:
    """Instinct hears its vault connect flow in the system prompt, where it is
    read before any tool call."""
    if auth.detect_instinct():
        return _SERVER_INSTRUCTIONS + "\n\n" + auth.INSTINCT_AUTH_INSTRUCTION
    return _SERVER_INSTRUCTIONS


app = Server("snaplii", instructions=_server_instructions())
```

- [ ] **Step 4: 实现工具列表调整**

在 `@app.list_tools()` 这一行的正上方插入：

```python
_INSTINCT_CONNECT_DESCRIPTION = (
    "Connect the user's Snaplii account in Instinct through the Instinct vault. Call with no "
    "arguments to get connect_url, eid and vault_entry. Open connect_url in your cloud browser, "
    "fill the API key field from the vault entry, click Connect, then call again with the eid "
    "within 2 minutes to finish. Do not call when snaplii_config_show reports "
    "has_valid_token=true. The API key never passes through the chat."
)


def _instinct_tools(tools: list[types.Tool]) -> list[types.Tool]:
    """Instinct connects only through the vault-filled browser page: no card, no
    card submit tool, and snaplii_connect takes the eid back."""
    adapted = []
    for tool in tools:
        if tool.name == "snaplii_submit_api_key":
            continue
        if tool.name == "snaplii_connect":
            tool = tool.model_copy(update={
                "meta": None,
                "description": _INSTINCT_CONNECT_DESCRIPTION,
                "inputSchema": {
                    "type": "object",
                    "properties": {"eid": {
                        "type": "string",
                        "description": "The eid returned by the first snaplii_connect call",
                    }},
                    "required": [],
                },
            })
        adapted.append(tool)
    return adapted
```

然后在 `list_tools` 函数里，把开头的：

```python
async def list_tools() -> list[types.Tool]:
    return [
```

改成：

```python
async def list_tools() -> list[types.Tool]:
    tools = [
```

再把这个函数末尾的：

```python
                    "page_size": {"type": "integer", "description": "Rows per page, 1-100 (default 20)"},
                },
            },
        ),
    ]
```

改成：

```python
                    "page_size": {"type": "integer", "description": "Rows per page, 1-100 (default 20)"},
                },
            },
        ),
    ]
    return _instinct_tools(tools) if auth.detect_instinct() else tools
```

改之前先确认，这段 `page_size` 文字在 `list_tools` 里只出现一次，位于 `snaplii_transfer_list` 工具末尾。

- [ ] **Step 5: 实现拒绝直接传 key**

在 `_authenticate` 函数里，找到：

```python
    import hashlib
    api_key = (api_key or "").strip()
```

改成：

```python
    import hashlib
    if auth.detect_instinct():
        # Instinct keeps the key in its vault; it reaches Snaplii only through the
        # vault-filled connect page, never as a tool argument.
        return {"error": "mcp_connect_required",
                "message": ("In Instinct, connect with snaplii_connect and the Instinct vault. "
                            "API keys are not accepted as tool arguments."),
                "auth_state": "mcp_required", "reason_code": "instinct_requires_vault_connect",
                "next_action": auth.build_auth_action("mcp_required", host="instinct")}
    api_key = (api_key or "").strip()
```

- [ ] **Step 6: 运行测试，确认通过**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests/test_instinct_mcp.py -q`
Expected: PASS

- [ ] **Step 7: 全量测试**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests -q`
Expected: 全部通过。非 Instinct 环境下，`test_business_auth_matrix_covers_all_registered_entrypoints` 和卡片相关测试应当不受影响。

- [ ] **Step 8: Commit**

```bash
git add mcp-server/server.py tests/test_instinct_mcp.py
git commit -m "feat(mcp): give Instinct its connect instructions and drop the key card there"
```

---

### Task 5: `snaplii_connect` 的 Instinct 流程

**Files:**
- Modify: `mcp-server/server.py`
- Test: `tests/test_instinct_mcp.py`

**Interfaces:**
- Consumes: Task 1 的 `instinct_vault_entry`。现有的 `_elicit_url()`、`_base_url()`、`_get_client()`，`GatewayClient.poll_connect_token(eid) -> dict | None`，`GatewayClient.accept_connect_token(response) -> dict`，以及常量 `_ELICIT_POLL_MAX_ATTEMPTS`、`_ELICIT_POLL_INTERVAL_S`。
- Produces:
  - `_poll_connect_token(client, eid: str) -> dict | None`，异步函数，供 Instinct 流程和现有 elicitation 流程共用。
  - `_instinct_eid(value) -> str | None`：接受单独的一次性 ID，也接受带 `eid=` 参数的完整链接。
  - `_instinct_connect(arguments: dict) -> dict`，异步函数。返回的 `status` 取 `open_in_browser`、`invalid_eid`、`authenticated` 或 `pending` 之一。

- [ ] **Step 1: 写失败的测试**

在 `tests/test_instinct_mcp.py` 顶部的 import 区补上：

```python
import re

import keyring
from keyring.backends.fail import Keyring

from snaplii.config_store import ConfigStore
from snaplii.exceptions import GatewayConnectionError
```

然后在文件末尾追加：

```python
EID = "ABCDEF0123456789abcdef0123456789"


@pytest.fixture
def instinct_mcp(tmp_path, monkeypatch, instinct_env):
    monkeypatch.setattr(keyring, "get_keyring", lambda: Keyring())
    monkeypatch.delenv("SNAPLII_ALLOW_INSECURE", raising=False)
    store = ConfigStore(tmp_path / "config.json", runtime="mcp")
    monkeypatch.setattr(server, "ConfigStore", lambda: store)
    monkeypatch.setattr(server, "_base_url", lambda: auth.DEFAULT_ORIGIN)
    monkeypatch.setattr(server, "_elicit_url", lambda: auth.DEFAULT_ORIGIN + "/connect")
    monkeypatch.setattr(server, "_ELICIT_POLL_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(server, "_ELICIT_POLL_INTERVAL_S", 0)
    return store


class _PollClient:
    def __init__(self, token=None, error=None):
        self.token, self.error = token, error
        self.polled, self.accepted = [], None

    def poll_connect_token(self, eid):
        self.polled.append(eid)
        if self.error:
            raise self.error
        return self.token

    def accept_connect_token(self, response):
        self.accepted = response
        return response

    def auth_status(self):
        return {"has_valid_token": self.accepted is not None, "host": "instinct", "auth_method": "url"}


def _call(name, arguments):
    return json.loads(asyncio.run(server.call_tool(name, arguments))[0].text)


def _use(monkeypatch, client):
    monkeypatch.setattr(server, "_get_client", lambda: client)
    return client


def test_config_show_reports_instinct(instinct_mcp):
    state = _call("snaplii_config_show", {})
    assert state["host"] == "instinct"
    assert state["instinct_env"] == ["INSTINCT_AGENT_ID"]


def test_first_call_returns_link_entry_and_eid_without_polling(instinct_mcp, monkeypatch):
    client = _use(monkeypatch, _PollClient())
    out = _call("snaplii_connect", {})
    assert out["status"] == "open_in_browser"
    assert re.fullmatch(r"[0-9a-f]{32}", out["eid"])
    assert out["connect_url"] == f"{auth.DEFAULT_ORIGIN}/connect?eid={out['eid']}"
    assert out["vault_entry"] == "Snaplii API Key"
    assert "apikey" in out["field"]
    assert client.polled == []


def test_link_keeps_page_query_and_names_the_staging_entry(instinct_mcp, monkeypatch):
    _use(monkeypatch, _PollClient())
    monkeypatch.setattr(server, "_base_url", lambda: "https://aipay.stage.snaplii.com/gw")
    monkeypatch.setattr(server, "_elicit_url", lambda: "https://aipay.stage.snaplii.com/gw/connect?lang=en")
    out = _call("snaplii_connect", {})
    assert out["connect_url"] == f"https://aipay.stage.snaplii.com/gw/connect?lang=en&eid={out['eid']}"
    assert out["vault_entry"] == "Snaplii API Key aipay.stage.snaplii.com"


@pytest.mark.parametrize("passed", [EID, f"{auth.DEFAULT_ORIGIN}/connect?eid={EID}"], ids=["eid", "whole-url"])
def test_second_call_takes_the_parked_token(instinct_mcp, monkeypatch, passed):
    client = _use(monkeypatch, _PollClient(token={"access_token": "jwt-x", "expires_in": 1800, "country": "CA"}))
    out = _call("snaplii_connect", {"eid": passed})
    assert out["status"] == "authenticated"
    assert client.polled == [EID]
    assert client.accepted["access_token"] == "jwt-x"
    assert "jwt-x" not in json.dumps(out)


@pytest.mark.parametrize("client", [
    _PollClient(token=None),
    _PollClient(error=GatewayConnectionError("https://aipayment.snaplii.com", OSError("down"))),
], ids=["not-ready", "gateway-down"])
def test_second_call_reports_pending_without_raw_key_fallback(instinct_mcp, monkeypatch, client):
    _use(monkeypatch, client)
    out = _call("snaplii_connect", {"eid": "a" * 32})
    assert out["status"] == "pending"
    assert len(client.polled) == 2
    text = json.dumps(out).lower()
    assert "without arguments" in text
    assert "snaplii init" not in text and "paste" not in text


@pytest.mark.parametrize("eid", ["short", "z" * 32, "https://evil.example/connect?x=1", 42])
def test_invalid_eid_is_rejected_without_polling(instinct_mcp, monkeypatch, eid):
    client = _use(monkeypatch, _PollClient())
    out = _call("snaplii_connect", {"eid": eid})
    assert out["status"] == "invalid_eid"
    assert client.polled == []


def test_already_connected_short_circuits_even_with_an_eid(instinct_mcp, monkeypatch):
    instinct_mcp.commit_session("synthetic-token", 3600, agent_id="agent-1",
                                auth_method="url", token_origin=auth.DEFAULT_ORIGIN)
    client = _use(monkeypatch, _PollClient())
    out = _call("snaplii_connect", {"eid": EID})
    assert out["status"] == "already_connected"
    assert client.polled == []
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests/test_instinct_mcp.py -q`
Expected: 新加的连接测试失败。现在 Instinct 下会走卡片或 elicitation 路由，返回 `card_requested` 或 `use_terminal_or_chat_key`，而不是 `open_in_browser`。`test_config_show_reports_instinct` 应当已经通过。

- [ ] **Step 3: 补充 import**

在 `mcp-server/server.py` 顶部，把：

```python
import asyncio
import json
import sys
import threading
from pathlib import Path
```

改成：

```python
import asyncio
import json
import re
import sys
import threading
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
```

- [ ] **Step 4: 抽出共用的轮询函数，并实现 Instinct 流程**

在 `def _elicit_url() -> str:` 这一行的正上方插入：

```python
async def _poll_connect_token(client, eid: str) -> dict | None:
    """Take the token the hosted /connect page parked under eid, or None."""
    for _ in range(_ELICIT_POLL_MAX_ATTEMPTS):
        try:
            token_data = client.poll_connect_token(eid)
        except GatewayConnectionError:
            token_data = None
        if isinstance(token_data, dict) and token_data.get("access_token"):
            return token_data
        await asyncio.sleep(_ELICIT_POLL_INTERVAL_S)
    return None


_EID_PATTERN = re.compile(r"[0-9a-fA-F]{16,64}")
_INSTINCT_FIELD = "the password input labelled 'Snaplii API key' (id apikey)"


def _instinct_eid(value) -> str | None:
    """Accept the bare one-time ID, or the whole connect URL an agent echoes back."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if "eid=" in value:
        value = (parse_qs(urlsplit(value).query).get("eid") or [""])[0]
    return value if _EID_PATTERN.fullmatch(value) else None


async def _instinct_connect(arguments: dict) -> dict:
    """Instinct: the agent opens the connect page in its cloud browser and has the
    Instinct vault fill the key. This server only hands out the link and later
    takes the parked token, so the key never reaches the model or this process.
    Stateless: the agent passes the eid back, so a restart in between is fine."""
    raw = (arguments or {}).get("eid")
    if not raw:
        eid = uuid.uuid4().hex
        page = _elicit_url()
        sep = "&" if "?" in page else "?"
        return {
            "status": "open_in_browser",
            "connect_url": f"{page}{sep}eid={eid}",
            "eid": eid,
            "vault_entry": auth.instinct_vault_entry(_base_url()),
            "field": _INSTINCT_FIELD,
            "next": ("Open connect_url in your cloud browser, use the Instinct vault fill action on "
                     "that field with vault_entry, click Connect, then call snaplii_connect with "
                     "this eid within 2 minutes of the page showing Connected."),
        }
    eid = _instinct_eid(raw)
    if eid is None:
        return {"status": "invalid_eid",
                "message": ("That eid is not valid. Pass the eid returned by snaplii_connect, "
                            "or call snaplii_connect without arguments to start over.")}
    client = _get_client()
    token_data = await _poll_connect_token(client, eid)
    if token_data:
        client.accept_connect_token(token_data)
        return {"status": "authenticated", **client.auth_status(),
                "message": ("✅ Connected through the Instinct vault. Purchases come only from your "
                            "prepaid Snaplii Cash, capped by your daily limit.")}
    return {"status": "pending",
            "message": ("No connection for this eid yet. Check the connect page. If it shows "
                        "Connected and more than 2 minutes have passed, call snaplii_connect "
                        "without arguments to start over once.")}
```

- [ ] **Step 5: 在 `snaplii_connect` 里接入 Instinct 分支，并让 elicitation 复用轮询函数**

在 `call_tool` 的 `snaplii_connect` 分支里，找到：

```python
            if auth_status["host"] == "muse":
```

在它前面插入：

```python
            if auth_status["host"] == "instinct":
                return _text(await _instinct_connect(arguments))

```

然后在同一个分支的 elicitation 路由里，找到：

```python
                client = _get_client()
                token_data = None
                for _ in range(_ELICIT_POLL_MAX_ATTEMPTS):
                    try:
                        token_data = client.poll_connect_token(eid)
                    except GatewayConnectionError:
                        token_data = None
                    if isinstance(token_data, dict) and token_data.get("access_token"):
                        break
                    await asyncio.sleep(_ELICIT_POLL_INTERVAL_S)
                if isinstance(token_data, dict) and token_data.get("access_token"):
```

改成：

```python
                client = _get_client()
                token_data = await _poll_connect_token(client, eid)
                if token_data:
```

最后删掉 elicitation 路由里原来的局部 `import uuid`，因为模块顶部已经导入了。也就是删除：

```python
                import uuid
                eid = uuid.uuid4().hex
```

中的第一行，保留 `eid = uuid.uuid4().hex`。

- [ ] **Step 6: 运行测试，确认通过**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests/test_instinct_mcp.py tests/test_apikey_card.py -q`
Expected: PASS。`test_apikey_card.py` 里的 elicitation 测试证明抽出的轮询函数行为不变。

- [ ] **Step 7: 全量测试**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests -q`
Expected: 全部通过。

- [ ] **Step 8: Commit**

```bash
git add mcp-server/server.py tests/test_instinct_mcp.py
git commit -m "feat(mcp): connect Instinct through a vault-filled page and a returned eid"
```

---

### Task 6: README 和 Skill 文档

**Files:**
- Modify: `snaplii-cli/src/snaplii/auth.py`，函数 `render_auth_skill_block`
- Modify: `skills/snaplii-cli.md`、`clawhub-publish/SKILL.md`、`skills/snaplii-autopilot.md`、`clawhub-autopilot/SKILL.md`，由同步脚本生成
- Modify: `README.md`
- Create: `tests/test_instinct_docs.py`

**Interfaces:**
- Consumes: Task 1 的 `INSTINCT_AUTH_INSTRUCTION`、`INSTINCT_VAULT_ENTRY`。
- Produces: Skill 的 Auth 章节多一个 `### Instinct` 小节。README 的 MCP 一节多一个 Instinct 折叠块。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_instinct_docs.py`：

```python
from pathlib import Path

from snaplii import auth

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text()


def test_skill_block_routes_instinct_to_mcp():
    block = auth.render_auth_skill_block()
    section = block.split("### Instinct", 1)[1].split("### Other agents", 1)[0]
    section = " ".join(section.split())
    for phrase in ("host=instinct", "snaplii_connect", "README", "Never ask for the API key in the chat"):
        assert phrase in section


def test_readme_instinct_section_skips_cli_login_and_states_the_risk():
    section = README.split("<summary><strong>Instinct</strong></summary>", 1)[1].split("</details>", 1)[0]
    for phrase in ("mcp-server/server.py", "Skip `snaplii init`", "snaplii_connect",
                   auth.INSTINCT_VAULT_ENTRY, "INSTINCT_", "one-time `eid`", "2 minutes"):
        assert phrase in section


def test_readme_cli_login_step_points_instinct_elsewhere():
    step = README.split("#### Step 2: Authenticate", 1)[1].split("#### Step 3", 1)[0]
    assert "In Instinct, skip this step" in step


def test_instinct_instruction_uses_the_readme_app_route():
    route = "More → Payment Methods → AI Payment Management → + New API Key"
    assert route in " ".join(auth.INSTINCT_AUTH_INSTRUCTION.split())
    quick_start = README.split("### 1. Get Your API Key via Snaplii App", 1)[1].split("### 2.", 1)[0]
    positions = [quick_start.index(label) for label in route.split(" → ")]
    assert positions == sorted(positions)
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests/test_instinct_docs.py -q`
Expected: 前三个测试失败，原因是还没有 Instinct 小节。最后一个测试应当已经通过。

- [ ] **Step 3: 在 Skill 的 Auth 章节加 Instinct 小节**

在 `snaplii-cli/src/snaplii/auth.py` 的 `render_auth_skill_block` 返回的 f-string 里，找到：

```
{invocation}

### Other agents
```

改成：

```
{invocation}

### Instinct

When `snaplii config show` or `snaplii_config_show` reports `host=instinct`,
Snaplii runs only through the Snaplii MCP tools; the CLI refuses authentication
and business commands there. Install the MCP server from GitHub as the README's
Instinct section describes, then follow the Instinct instructions from the MCP
server or from `next_action`, starting with `snaplii_connect`. Never ask for the
API key in the chat.

### Other agents
```

- [ ] **Step 4: 同步 4 个 Skill 文件**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" python scripts/sync_muse_auth_docs.py`
Expected: 输出 `Updated 4 Auth block(s).`

Run: `uv run -q --with-editable "./snaplii-cli[dev]" python scripts/sync_muse_auth_docs.py --check`
Expected: 输出 `Auth blocks are in sync.`

`dist/` 下的候选包不要改。

- [ ] **Step 5: 更新 README**

在 `README.md` 的 "#### Step 2: Authenticate" 里，找到：

```
Enter your API key when prompted.
```

改成：

```
Enter your API key when prompted.

In Instinct, skip this step and follow the **Instinct** instructions under Step 3.
```

然后在下面这一段之前：

```
<details>
<summary><strong>Cursor / VS Code / Other MCP clients</strong></summary>
```

插入：

````
<details>
<summary><strong>Instinct</strong></summary>

Instinct installs the MCP server from this repository and connects through the Instinct vault, so the API key never enters the chat.

1. Clone the repository and install the dependencies from Step 1.
2. Register `python3 /path/to/agent-to-merchant-payments/mcp-server/server.py` as a stdio MCP server in Instinct.
3. Skip `snaplii init`. In Instinct the CLI only serves `help`, `update`, `--version` and `config`; everything else runs through the MCP tools.
4. Connect right away. Call `snaplii_connect` and open the returned `connect_url` in the cloud browser. Use the Instinct vault fill action on the API key field with the returned `vault_entry`, click **Connect**, then call `snaplii_connect` again with the returned `eid` within 2 minutes. If the MCP tools only load in a new session, connect at the start of that session.
5. If the vault has no entry yet, the agent explains how to create a key in the Snaplii App and sends the vault's encrypted submission link so you can save it there.

The vault entry is `Snaplii API Key` for the production gateway. Other gateways append their host, for example `Snaplii API Key aipay.stage.snaplii.com`.

Instinct is detected from any environment variable whose name starts with `INSTINCT_`; Muse takes precedence. `snaplii_config_show` and `snaplii config doctor` list the matching variable names, never their values.

The one-time `eid` in the connect link is visible to the agent. Whoever holds it can take the session token once, within 2 minutes after **Connect** is pressed. If someone else takes it first, `snaplii_connect` reports `pending` instead of connecting.

</details>

````

- [ ] **Step 6: 运行测试，确认通过**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests/test_instinct_docs.py tests/test_muse_auth_docs.py -q`
Expected: PASS

- [ ] **Step 7: 全量测试**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests -q`
Expected: 全部通过。

- [ ] **Step 8: Commit**

```bash
git add snaplii-cli/src/snaplii/auth.py skills/snaplii-cli.md clawhub-publish/SKILL.md \
  skills/snaplii-autopilot.md clawhub-autopilot/SKILL.md README.md tests/test_instinct_docs.py
git commit -m "docs: document the Instinct MCP install and vault connect flow"
```

---

### Task 7: 版本号和 CHANGELOG

**Files:**
- Modify: `snaplii-cli/pyproject.toml`、`snaplii-cli/src/snaplii/__init__.py`、`mcp-server/pyproject.toml`、`CHANGELOG.md`

**Interfaces:**
- Consumes: 前面所有任务。
- Produces: 两个包都是 `0.19.0`。

- [ ] **Step 1: 改版本号**

- `snaplii-cli/pyproject.toml`：`version = "0.18.0"` 改为 `version = "0.19.0"`。
- `snaplii-cli/src/snaplii/__init__.py`：`__version__ = "0.18.0"` 改为 `__version__ = "0.19.0"`。
- `mcp-server/pyproject.toml`：`version = "0.18.0"` 改为 `version = "0.19.0"`，`"snaplii-cli>=0.18.0",` 改为 `"snaplii-cli>=0.19.0",`。

- [ ] **Step 2: 写 CHANGELOG**

在 `CHANGELOG.md` 里，找到：

```
---

## [0.18.0] — 2026-10-01
```

改成：

```
---

## [0.19.0] — 2026-10-08

### Added
- **Instinct support.** When an environment variable whose name starts with `INSTINCT_` is present and Muse is not detected, Snaplii treats the host as Instinct and runs only through the MCP tools. `snaplii_connect` returns a connect link; the agent opens it in its cloud browser, has the Instinct vault fill the stored API key, clicks Connect, and calls `snaplii_connect` again with the one-time `eid` so the MCP server takes the session token. The key never passes through the chat, the model, or the MCP process. The production gateway uses the vault entry `Snaplii API Key`; other gateways append their host.
- **Connect right after installation in Instinct.** The README's Instinct section and the MCP server instructions tell the agent to connect as soon as the MCP server is registered, and to reconnect on the next Snaplii request once the session is gone.

### Changed
- **CLI and raw-key tools are disabled in Instinct.** The CLI only serves `help`, `update`, `--version`, and `config`; other commands point to `snaplii_connect`. `snaplii_init` and the card submit tool refuse API keys, and `snaplii_connect` shows no card there.
- **Diagnostics name the Instinct signal.** `snaplii config show`, `snaplii_config_show`, and `snaplii config doctor` list the matching `INSTINCT_` variable names, never their values.

---

## [0.18.0] — 2026-10-01
```

再在文件末尾的版本表里，找到：

```
| 0.18.0 | 2026-10-01 | Muse app update notice in `snaplii config show` |
```

在它前面插入一行：

```
| 0.19.0 | 2026-10-08 | Instinct support: MCP-only, vault-filled connect page |
```

- [ ] **Step 3: 全量测试**

Run: `uv run -q --with-editable "./snaplii-cli[dev]" --with-editable ./mcp-server pytest tests -q`
Expected: 全部通过，包括 `tests/test_candidate_version.py`。如果 uv 报告 `snaplii-mcp` 依赖的 `snaplii-cli>=0.19.0` 无法满足，就去掉 `--with-editable ./mcp-server`，改用 `--with "mcp>=1.0,<2"` 提供 mcp 依赖。测试通过 `tests/conftest.py` 直接从源码导入 `mcp-server/server.py`，不需要安装 MCP 包本身。

- [ ] **Step 4: Commit**

```bash
git add snaplii-cli/pyproject.toml snaplii-cli/src/snaplii/__init__.py mcp-server/pyproject.toml CHANGELOG.md
git commit -m "chore: release 0.19.0 with Instinct support"
```

---

### Task 8: 真实 Instinct 验收，由人工完成

这个任务不能由 Agent 在本仓库里完成。它需要真实的 Instinct 环境、staging 网关和 staging 测试 key。结果决定能否合并到 main。

- [ ] **Step 1: 推送功能分支**，让 Instinct 能从 `feat/instinct-adapt` 克隆。推送前先征得仓库负责人同意。
- [ ] **Step 2: 在 Instinct 里按 README 的 Instinct 分支安装**，网关指向 `https://aipay.stage.snaplii.com`。
- [ ] **Step 3: 逐项记录结果**，每条记录日期、版本、操作序列和结果。不要记录 key、令牌或变量值。
  1. `snaplii_config_show` 返回 `host=instinct`，并列出变量名。这确认了环境变量能传到 MCP 进程。
  2. 安装完成后，Agent 不等用户开口就开始连接。
  3. 条目 `Snaplii API Key aipay.stage.snaplii.com` 不存在时，Agent 发出加密链接。用户保存后，填充成功。
  4. 点击 Connect 后，第二次调用返回 `authenticated`。
  5. 开一个新会话，第一次 Snaplii 业务请求会自动重连。
  6. 记下 Vault 填充和加密链接的确切工具名与参数。
- [ ] **Step 4: 处理结果。** 第 1 项失败时，回到设计文档重新选择检测信号。第 6 项拿到工具名后，另开一个小改动，把确切调用写进 `INSTINCT_AUTH_INSTRUCTION`。全部通过后，再提 PR 合并到 main。

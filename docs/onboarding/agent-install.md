# 供 Agent 使用的 Pico 安装契约

自动化 Agent 为用户安装 Pico 时遵循本契约。Agent 不得推测发布地址、暴露密钥、
发布制品、重置已有配置，也不得初始化用户未选择的仓库。

## 必需输入

- 目标操作系统：macOS/Linux 或 Windows。
- 目标 Git 仓库的绝对路径。
- 私有 Gitee 仓库的访问权限，或者一个可信的 `PICO_WHEEL_URL`。
- 由用户直接提供的 Provider 选择和凭证。
- 是否允许执行一次真实计费的首条 Turn。没有明确授权时默认不允许。
- 本次范围是否包含消息渠道。默认不包含。

当前发布不附带外部 Memory 实现。使用 `--skip-memory`；不要根据源码树里的 adapter
名称推测未发布的仓库、包或下载地址。

## 安装

Private 发布场景下，使用用户已经配置的 Gitee 凭证，并在 Checkout 中运行安装器：

```bash
git clone https://gitee.com/htxoffical/pico-harness.git
cd pico-harness
./install.sh
```

Windows PowerShell：

```powershell
git clone https://gitee.com/htxoffical/pico-harness.git
Set-Location pico-harness
.\install.ps1
```

安装器需要读取 Private Release 时，从用户环境中获取 `PICO_GITEE_TOKEN`。不要打印它，
不要放进 URL，也不要写入文件。`PICO_WHEEL_URL` 可能包含带签名的查询参数，报告和
捕获到的输出中都要脱敏。

## 属于用户的配置边界

开始 onboarding 前，先切换到确切的目标仓库：

```bash
cd <absolute-target-repository>
pico onboard --skip-memory --skip-test
```

交互式向导是首选的密钥输入路径。用户输入 Provider 凭证期间保持暂停等待。

只有用户明确授权非交互密钥处理时，才使用 `--non-interactive --api-key ...`。命令行
参数可能被本机进程列表和历史记录工具读取。

不要自动加上 `--reset`。已有的 Provider、渠道、Sandbox 和 workspace 选择都属于用户。

## 验收

在目标仓库中执行只读检查：

```bash
uv tool list
pico --version
pico plugins
pico channels list
pico doctor --json
```

验收结果应满足：

- `uv tool list` 包含 `pico-harness`，并暴露 `pico` 可执行文件。
- `pico --version` 能返回已安装版本。
- `pico doctor --json` 输出合法 JSON。
- Memory 明确处于关闭状态，而不是指向一个不可用的 Memory Backend。
- 捕获到的输出中没有出现任何凭证取值。

用户授权一次真实计费的连通检查时，运行下面其中一条命令：

```bash
pico doctor --probe
pico run -m "Reply with: Pico is ready"
```

真实命令没有返回模型回复时，不能称 Provider 已验证。安装成功、静态 doctor 报告或者
跳过 probe，都不算真实 Provider 结果。

## 飞书交接

App ID 与 App Secret 由用户持有，权限审批、应用发布和入站测试消息也由用户负责。按
[feishu.zh-CN.md](feishu.zh-CN.md) 操作，之后只核对脱敏后的本地状态：

```bash
pico channels get feishu
pico gateway --workspace <absolute-target-repository> --verbose
```

在有真人于同一会话中发送入站消息并收到 Pico 回复之前，不能称飞书已经接通。不要把
飞书密钥粘贴到 issue、pull request、聊天记录、截图或提交进仓库的文件里。

## 交接记录

交接时报告已安装的 Pico 版本、目标仓库路径、Memory 状态、是否执行过计费 probe，
以及是否完成过一次真实的渠道往返。凭证和带签名的 URL 查询串都要脱敏。某一层被跳过
时，把它标记为未验证，不要用其他层的结论推断它成功。

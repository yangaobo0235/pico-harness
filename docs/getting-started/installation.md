# 安装与首次运行

本指南从源码安装 Pico、配置模型后端并启动 CLI。Pico 的运行时只使用标准库，安装动作因此只有两件事：准备一个 Python 3.12 环境，以及把模型凭证放进被操作仓库的 `.env`。

源码开发用 `uv run pico` 跑当前代码；装成可编辑包之后可以直接运行 `pico` 或 `python -m pico`。

## 环境要求

| 依赖 | 要求 | 用途 |
| --- | --- | --- |
| Python | 3.12（`>=3.12,<3.13`） | Agent、CLI 与全部运行时 |
| uv | 可用的当前版本 | Python 依赖与开发工具安装 |
| Git | 可用的当前版本 | 获取源码，并提供工作区分支与差异事实 |
| ripgrep | 可选 | `search` 工具的首选实现 |
| 模型服务 | 有效端点、模型和凭证 | 真实请求 |

运行时没有第三方包：Provider 走 `urllib`，渲染走文本排版，持久化走 `json`。保持零依赖是有意的，一次 `uv sync` 不应该成为在别的仓库里试用 Pico 的前置成本。

Windows 支持完整 CLI 与全部内置工具。`search` 在没有 `rg` 时退回纯 Python 遍历；路径锚定在解析符号链接之后判断，跨盘符与 UNC 路径按越界处理。

## 源码安装

### 1. 获取代码

```powershell
git clone <仓库地址> pico
Set-Location pico
```

`<仓库地址>` 替换为你的远程地址。

### 2. 安装依赖

```powershell
uv sync
```

这条命令安装 dev 组：`pytest`、`pytest-timeout`、`pytest-xdist`、`pre-commit`、`ruff`。产品运行本身不需要它们。

### 3. 安装 Git hooks

```powershell
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

hook 覆盖格式化、架构边界与提交信息格式，见[测试指南](../development/testing.md)。

### 4. 配置模型

仓库只保留 `.env.example`，真实 key 写在本地 `.env` 里并被 Git 忽略：

```powershell
Copy-Item .env.example .env
```

bash 下等价命令是 `cp .env.example .env`。只填写你要用的 provider：

```text
PICO_PROVIDER=deepseek
PICO_DEEPSEEK_API_KEY=your-api-key
```

默认 provider 是 `deepseek`，只填 key 就能启动。共享网关的 key 推荐只写 `PICO_RIGHT_CODES_API_KEY`。`.env` 的解析规则、变量回退顺序与全部取值见[配置参考](../reference/configuration.md)。

`.env` 在创建 provider client 之前加载，并覆盖进程里的同名环境变量。API key 只从环境变量读取，命令行不接受 key，避免凭证进入进程列表和 shell 历史。

### 5. 启动助手

```powershell
uv run pico
uv run pico "阅读 README 和入口文件，说明项目用途"
```

第一条进入交互循环，第二条执行一次 one-shot 请求后退出。默认操作当前目录，需要指定别的仓库时使用 `--cwd D:\path\to\repo`。

## 安装为本地包

在源码根目录执行：

```powershell
pip install -e .
```

安装后 `pico` 与 `python -m pico` 都指向同一个入口。在其他仓库里使用时，把那个仓库当作 `--cwd`，会话与运行工件会写在被操作仓库的 `.pico/` 下，而不是 Pico 自己的目录里。

```powershell
pico --cwd D:\path\to\repo "列出这个仓库的测试入口"
```

## IDE 运行配置

使用仓库 `.venv` 中的解释器，将 `src` 标记为 Sources Root，否则 `import pico` 会解析失败。

| 配置 | 模块 | 参数 | 工作目录 |
| --- | --- | --- | --- |
| Pico REPL | `pico` | 留空 | 希望助手处理的仓库 |
| Pico one-shot | `pico` | `"分析测试失败原因" --approval auto` | 同上 |
| Pico 恢复会话 | `pico` | `--resume latest` | 会话文件所在的仓库 |

环境变量里设置以下三项，可以让日志与错误正文按 UTF-8 输出：

```text
PYTHONUNBUFFERED=1;PYTHONUTF8=1;PYTHONIOENCODING=utf-8
```

## 验证安装

```powershell
uv run pico --help
uv run pico
```

`--help` 使用 `ArgumentDefaultsHelpFormatter`，每个开关的默认值直接出现在帮助里。交互模式的首屏会打印 WORKSPACE、MODEL、BRANCH、APPROVAL 和 SESSION 五项装配结果。

首屏不访问网络，也不校验凭证是否可用：它只报告“这次配置用的是什么”。连接结论由第一次真实请求给出。

没有 key 但想确认链路可用时，跑一次脚本化模型的评测，它用确定性输出走完整控制循环，不需要凭证也不产生费用：

```powershell
uv run python -m scripts.dev.run_benchmark
```

说明见[Benchmark 说明](../../benchmarks/README.md)。

后续操作见[使用指南](../guides/usage.md)，启动失败见[故障排查](../guides/troubleshooting.md)。

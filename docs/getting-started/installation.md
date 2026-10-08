# 安装与首次运行

本指南从源码安装 Pico，配置模型并启动 CLI、TUI 或消息 Gateway。源码开发通过 `uv run` 使用当前代码；独立安装后可以在其他项目直接运行 `pico`。

## 环境要求

| 依赖 | 要求 | 用途 |
| --- | --- | --- |
| Python | 3.12 | Agent 和 CLI 运行时 |
| Node.js | 22 | TUI 与 Trace 查看器 |
| uv | 可用的当前版本 | Python 依赖和工具安装 |
| npm | 随 Node.js 提供 | 前端依赖和构建 |
| Git | 可用的当前版本 | 获取源码 |
| 模型服务 | 有效端点、模型和凭证 | 真实请求 |

Windows 支持核心 CLI 和 TUI 开发。符号链接取决于用户权限；Sandbox 和依赖 POSIX PTY、Unix Socket 的功能需要支持对应接口的环境。

## 源码安装

### 1. 获取代码

```powershell
git clone https://github.com/yangaobo0235/pico-harness.git
Set-Location pico-harness
```

### 2. 安装依赖

```powershell
uv sync --frozen --extra dev --extra channels
npm ci
npm ci --prefix apps/tui
```

`channels` 安装飞书、企业微信和 QQ 适配器依赖。只使用 CLI/TUI 可以省略；Sandbox 和大型检索依赖按需要单独安装。

### 3. 构建终端界面

```powershell
npm run build:tui
uv run pico --version
```

TUI 构建产物位于 `apps/tui/dist/entry.js`，发行包会携带该文件。

### 4. 配置模型

```powershell
uv run pico onboard --skip-memory
```

向导选择 Provider、模型、凭证、运行环境和可选渠道，默认执行首次真实请求。使用 `--skip-test` 跳过后，可单独运行 `uv run pico doctor --probe` 验证连接。

公开版本不附带外部长期记忆实现。`--skip-memory` 写入 `memory.backend = null`，保留会话、上下文和本地技能。真实请求可能产生费用。

### 5. 启动助手

```powershell
uv run pico
uv run pico run -m "阅读 README 和入口文件，说明项目用途"
```

第一条打开 TUI，第二条执行单次任务。默认操作当前目录。

## 安装独立命令

在已构建 TUI 的源码根目录执行：

```powershell
uv tool install .
```

需要消息渠道时使用：

```powershell
uv tool install --reinstall ".[channels]"
```

进入希望助手工作的目录，运行 `pico`、`pico run -m "..."` 或 `pico onboard --skip-memory`。

未安装独立命令时，可以在其他项目使用开发版本：

```powershell
uv run --project /absolute/path/to/pico-harness pico run -m "分析项目入口"
```

`/absolute/path/to/pico-harness` 替换为源码仓库的实际路径。

## IDE 运行配置

使用仓库 `.venv` 中的 Python 解释器，模块填写 `pico`，将 `src` 标记为 Sources Root。

| 配置 | 模块 | 参数 | 工作目录 |
| --- | --- | --- | --- |
| Pico TUI | `pico` | 留空 | 希望助手处理的目录 |
| Pico Gateway | `pico` | `gateway --workspace /path/to/workspace --verbose` | 项目根目录或专用运行目录 |

TUI 控制台开启模拟终端。Windows 可设置以下环境变量，使日志使用 UTF-8：

```text
PYTHONUNBUFFERED=1;PYTHONUTF8=1;PYTHONIOENCODING=utf-8
```

## 安装脚本

Linux/macOS：

```bash
sh scripts/install/install.sh
```

Windows：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install/install.ps1
```

脚本支持 `PICO_REPO_URL`、`PICO_WHEEL_URL`、`PICO_PYPI_INDEX` 和 `PICO_NPM_REGISTRY` 等配置，用于选择源码、制品或依赖源。

后续操作见[使用指南](../guides/usage.md)，启动失败见[故障排查](../guides/troubleshooting.md)。

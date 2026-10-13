# 贡献指南

Pico 接受可复现的 Bug、文档改进和功能提案。贡献代码前建立开发环境，按模块职责组织改动，并提供实际运行的检查结果。

## 开发环境

- Python 3.12
- uv 与 Git

在仓库根目录安装依赖与 Git hooks：

```powershell
uv sync
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

使用 `uv run pico` 运行开发版本，`python -m pico` 在源码树里等价。IDE 选择仓库 `.venv` 中的解释器，并将 `src` 标记为 Sources Root。运行配置见[安装指南](docs/getting-started/installation.md)。

运行时只使用标准库。新增第三方依赖需要说明它替换了哪一段手写实现，以及为什么不能留在可选入口里。

## 代码组织

| 内容 | 放置位置 |
| --- | --- |
| Python 产品实现 | `src/pico`，按入口、运行时、能力和外部适配分类 |
| Python 测试 | `tests`，按测试范围和源码职责分类 |
| 工程脚本 | `scripts/ci`、`scripts/dev` |
| 可复现评测 | `benchmarks` |
| 使用与开发说明 | `docs` |

Python 模块和函数使用 `snake_case`，类使用 `PascalCase`。文件与函数名称表达具体责任，私有辅助函数先留在所属模块。详细边界与函数归属见[架构文档](docs/architecture/overview.md)。

## 本地验证

支持 Make 的环境执行 `make check`。Windows 或无 Make 的环境使用[测试指南](docs/development/testing.md)中的等价命令。

- 行为变更覆盖实际触发条件和预期结果。
- 跨模块行为选择相应集成或契约测试。
- 修改持久化字段（会话 JSON、checkpoint、运行工件）时同时更新读取路径的兼容处理。
- 真实模型请求需要凭证与预算；PR 中标明未执行的范围。

## 分支与提交

分支名围绕目标命名，例如 `feat/tool-search`、`fix/session-resume`。提交信息和 PR 标题使用英文 ASCII，遵循 Conventional Commits：

```text
feat(tools): add a bounded file search option
fix(sessions): preserve message order on resume
docs: explain approval policies
```

同一 PR 围绕一个目标组织。较大的功能或架构调整先在 Issue 中说明目标、行为和验证方式。

## Pull Request

PR 描述应包括：

- 具体问题和改动后的行为。
- 关联 Issue。
- 实际执行的验证命令与结果。
- 公共接口或持久化格式受到的影响，以及恢复方式。

凭证、个人会话、运行日志、虚拟环境和构建产物留在本地，不随仓库提交。

## 构建

```powershell
uv build
```

wheel 只包含 Python 代码。构建结果在仓库外的干净环境里安装验证一次，可以提前发现对源码树路径的意外依赖。

## 问题报告

Bug 报告提供系统、版本、复现步骤、预期结果和必要的脱敏日志。日志里包含工具参数或 Prompt 片段时先做替换，`PICO_SECRET_ENV_NAMES` 可以帮助确认哪些值需要处理。

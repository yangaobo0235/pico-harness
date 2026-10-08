# 贡献指南

Pico 接受可复现的 Bug、文档改进和功能提案。贡献代码前建立开发环境，按模块职责组织改动，并提供实际运行的检查结果。

## 开发环境

- Python 3.12
- Node.js 22 与 npm
- uv 与 Git

在仓库根目录安装依赖与 Git hooks：

```powershell
uv sync --frozen --extra dev --extra channels
npm ci
npm ci --prefix apps/tui
npm run build:tui
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
```

使用 `uv run pico` 运行开发版本。IDE 选择仓库 `.venv` 中的解释器，并将 `src` 标记为 Sources Root。运行配置见[安装指南](docs/getting-started/installation.md)。

## 代码组织

| 内容 | 放置位置 |
| --- | --- |
| Python 产品实现 | `src/pico`，按入口、运行时、能力和外部适配分类 |
| TUI 界面与状态 | `apps/tui/src` |
| Python 测试 | `tests`，按测试范围和源码职责分类 |
| TUI 应用测试 | `apps/tui/tests/unit` |
| 工程脚本 | `scripts/ci`、`scripts/dev`、`scripts/release`、`scripts/install` |
| 可复现评测 | `benchmarks` |
| 使用与开发说明 | `docs` |

Python 模块和函数使用 `snake_case`，类使用 `PascalCase`。文件与函数名称表达具体责任，私有辅助函数先留在所属模块。详细边界与函数归属见[架构文档](docs/architecture/overview.md)。

## 本地验证

支持 Make 的环境执行 `make check`。Windows 或无 Make 的环境使用[测试指南](docs/development/testing.md)中的等价命令。

- 行为变更覆盖实际触发条件和预期结果。
- 跨模块行为选择相应集成或契约测试。
- 修改 RPC Schema 后运行 `npm --prefix apps/tui run gen:rpc`，再检查生成文件与调用接口。
- 真实模型、消息渠道和 VM 需要对应环境；PR 中标明未执行的范围。

## 分支与提交

分支名围绕目标命名，例如 `feat/channel-filter`、`fix/session-save`。提交信息和 PR 标题使用英文 ASCII，遵循 Conventional Commits：

```text
feat(tools): add a file search option
fix(sessions): preserve message order on resume
docs: explain workspace configuration
```

同一 PR 围绕一个目标组织。较大的功能或架构调整先在 Issue 中说明目标、行为和验证方式。

## Pull Request

PR 描述应包括：

- 具体问题和改动后的行为。
- 关联 Issue。
- 实际执行的验证命令与结果。
- 公共接口或持久化格式受到的影响，以及恢复方式。

新增依赖说明用途和许可证。凭证、个人会话、运行日志、虚拟环境、构建产物和原始评测输出留在本地。

## 构建与发行校验

```powershell
npm run build:tui
uv build
```

wheel 包含 Python 代码、模板、技能、TUI bundle 和 Trace 查看器。构建前生成 TUI，确保资源齐全。

`scripts/release/verify_distribution.py` 在仓库外的空目录校验发行包。支持 Make 的环境设置 `PICO_RELEASE_OUTPUT` 后执行 `make release-dist`；完整参数使用模块帮助查看：

```powershell
uv run python -m scripts.release.verify_distribution --help
```

维护者发布前核对版本、许可证、文件清单和独立安装结果。GitHub 的手动 release workflow 生成构建产物。

## 问题报告

Bug 报告提供系统、版本、复现步骤、预期结果和必要的脱敏日志。安全问题按[安全报告流程](SECURITY.md)私下提交。

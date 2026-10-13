# Pico Review Pack

这份材料面向代码评审：说明项目定位、模块归属、评测证据和一次运行留下的工件，评审者据此可以只看文件就复现结论。

## 项目定位

Pico 是面向本地仓库的轻量 coding agent。它把一个模型包进一层可控运行时：工作区事实、显式工具白名单、预算化的上下文、任务状态、记忆沉淀和可复盘的运行工件，并用固定 benchmark 约束能力主张。

## 架构地图

- `interfaces/cli` 解析参数、渲染首屏并分派单次执行或交互循环。
- `bootstrap` 采集工作区快照、加载项目配置、选择 Provider 并装配运行时。
- `runtime/agent` 持有运行现场并推进模型与工具的迭代。
- `runtime/context` 按预算组装指令、工作记忆、相关笔记、历史与本轮请求。
- `capabilities/tools` 提供工具目录与执行护栏，`capabilities/memory` 提供记忆与晋升判断。
- `security` 决定路径锚定、审批与环境变量脱敏。
- `observability/runs` 写出一次运行的状态、Trace 与报告。
- `extensions/evaluation` 提供固定 benchmark、消融实验与指标聚合。

## 评测证据

评测结果需要保留可复现元数据、任务行、汇总计数和失败类别，使评审者能区分运行时回归、任务本身问题和 Provider 故障。确定性路径使用脚本模型，不产生费用；真实 Provider 对比是显式选择的实验，需要凭证与预算。

## 一次运行的工件清单

- `.pico/runs/<run_id>/task_state.json`
- `.pico/runs/<run_id>/trace.jsonl`
- `.pico/runs/<run_id>/report.json`
- `.pico/sessions/<session-id>.json`

状态文件回答"进行到哪了"，Trace 回答"这一轮做了什么"，报告回答"结果和关键指标是什么"，会话文件负责"能不能接着干"。

## 建议阅读顺序

先读[架构与代码归属](../architecture/overview.md)确认分层与请求链路，再按[测试指南](../development/testing.md)跑一遍默认回归，最后沿 [Benchmark 使用说明](../../benchmarks/README.md)复核评测口径。

# PicoBench Ship-1

PicoBench 是 Pico 只在仓库 checkout 中运行的评测 campaign。它让真实的 Pico
Runtime 参与冻结的单轴对比，并从终态制品重建每一份结果。它不属于 `pico` wheel，
也不会新增对外的 `pico bench` 命令。

## 入口

先运行不需要凭证的闸门：

```bash
make picobench-smoke
```

它执行 2,000 请求的 Scheduler 轨道、100 Turn 的完整 Runtime 轨道、本地 stdio MCP
传输 smoke test，以及一次只依赖制品的报告重建。它不会解析 Provider，也不会发起
付费模型调用。

用下面的命令运行冻结的 calibration 与正式 campaign：

```bash
make picobench
```

付费命令使用常规 Pico 配置，但只有在精确解析出 `deepseek / deepseek-v4-flash`、
用一次真实 preflight 证明 Tool Calling 与完整用量字段可用、并冻结 tokenizer 身份
之后才会继续。禁止使用回退模型。

## 当前 Scorecard campaign

当前 Scorecard campaign 运行 Context 与 Tool/MCP Pack。CallEfficiency 与 Runtime
仍是独立的证据轨道，只有在各自的 Claim Gate 评估完成后才被合成进来。本次发布不
包含外部 Memory backend 实验。

用下面的命令运行或续跑完整的多维度流程：

```bash
PICO_BENCH_EXECUTE_PAID=1 make picobench-reproduce
```

该命令在任何付费调用之前先执行一次完整 preflight，然后运行 Runtime、TokenWise，
以及 Context 加 Tool/MCP 的 Scorecard 轨道。它合成多维度得分，在终端渲染表格，并
把 `report.json`、`REPORT.md`、`score.json` 和各阶段日志写入
`.pico/evidence/picobench-reproduction/<pico-commit>/`。重复执行该命令会校验并续跑
已保留的阶段制品，而不是重跑已经完成的工作。

当前 commit 已有的证据可以在不付费执行的情况下复用：

```bash
PICO_SCORECARD_FORMAL_SUMMARY=/absolute/path/to/summary.json \
PICO_SCORECARD_RUNTIME_EVIDENCE=/absolute/path/to/runtime-evidence.json \
PICO_SCORECARD_TOKENWISE_REPORT=/absolute/path/to/tokenwise-report.json \
  make picobench-reproduce
```

runner 会把这些精简输入复制到自己的输出目录，并在合成得分之前校验它们的 commit
身份与摘要。正式 summary 必须与同一实验的 `manifest.json` 放在一起，否则无法重建
它的 Scorecard 身份。诊断分与认证分始终分别标注，终端报告与 Markdown 报告会用
直白的语言列出每一条未通过的认证检查。

用下面的命令打印冻结的最坏情况预算：

```bash
make picobench-scorecard-estimate
```

用下面的命令运行付费 campaign：

```bash
make picobench-scorecard-ship
```

测量相互独立的 Context 与 Tool/MCP Pack 并不需要 Runtime 证据。但当提供了
`PICO_SCORECARD_RUNTIME_EVIDENCE` 时，campaign 会在付费调用之前验证它的 Pico 产品
代码、依赖身份与 Runtime Pack 逐字节等价。它绝不会静默重跑 Runtime 实验。

v1 多维度得分的权重为 Capability 50、Reliability 20、Efficiency 20、Process 10。
Capability 取 Context、Tool/MCP 与 Memory 当前 treatment（实验组）达成率的平均值。
Context 能力分是四项冻结检查的平均值：早期约束仍然存在、制品落实了该约束、最新
决策被采纳、制品完全正确。严格的外部 verifier 通过率仍然单独报告，其判定标准没有
放宽。Context 预留 500 个输出 Token，并保护它的第一个约束 Turn，为最新决策留出
2,400 Token 窗口中足够的空间。空 Provider 响应最多可重试四次，并在 treatment 与
control 两组中对称执行。Context 能力分的有效性与 Token 用量完整性互相独立。缺失用量只会使
Context 的效率主张失效；它既不会被强行记为零，也不会阻碍由 verifier 支撑的能力
诊断。Efficiency 为每一个具备资格的 TokenWise、Context、Tool/MCP 与 Turn 效率主张
各赋 5 分。缺失、不具备资格或与 commit 不兼容的证据记 0 分。Process 检查 MCP
披露、传输、invalid-target 与 exact-repeat 四类闸门。安全性与证据全覆盖属于认证
闸门，不是加分项。

用下面的命令从不可变的正式与 Runtime 制品计算得分：

```bash
PICO_SCORECARD_FORMAL_SUMMARY=/absolute/path/to/summary.json \
PICO_SCORECARD_RUNTIME_EVIDENCE=/absolute/path/to/runtime-evidence.json \
PICO_SCORECARD_TOKENWISE_REPORT=/absolute/path/to/tokenwise-report.json \
PICO_SCORECARD_MEMORY_SUMMARY=/absolute/path/to/memory-summary.json \
PICO_SCORECARD_MEMORY_HANDOFF=/absolute/path/to/memory-handoff.json \
PICO_SCORECARD_PREREGISTERED=1 \
  make picobench-scorecard-score
```

Runtime、Memory 与预注册输入都是可选的。Memory summary 只有配合一份绑定摘要、
且写明当前 Pico commit 的 handoff 时才会被接受。评分器始终输出诊断分，并把缺失的
维度记为零；只有当评分规范已预注册、且每一项证据与安全闸门都完整时，才输出认证
分。

## 冻结的规模与预算

`benchmarks/picobench/suites/agent_application_ship_1.yaml` 这套 suite 冻结了：

- calibration：64 个 E2E Trial 和 34 个 Retrieval Case；
- 正式：216 个 E2E Trial 和 260 个 Retrieval Case；
- 最多两次 Provider 尝试和两次整块重跑；
- 80 CNY 的告警阈值与 100 CNY 的硬性上限。

冻结的 Provider 预算按 pack 划分：

- Context Trial 最多允许八次逻辑调用，每次 42,000 输入 Token 和 1,200 输出
  Token。只用于 Benchmark 的 Curator 上限为四步，主 Agent Loop 上限为四次调用。
- Memory / Skill Trial 最多允许四次逻辑调用，每次 15,000 输入 Token 和 1,500
  输出 Token。
- Tool / MCP Trial 最多允许四次逻辑调用，每次 40,000 输入 Token 和 1,500 输出
  Token。

把全部 DeepSeek 输入按 cache-miss 单价计价，使用冻结的 USD 兑 CNY 乘数，并为外部
服务预留 5 CNY，得到当前 suite 全新 campaign 的 62.86592 CNY 最坏情况。

在任何付费调用之前，PicoBench 会把账本上的既有支出和两次真实 preflight 尝试计入
预测。它把当前请求数与新增授权尝试数冻结写入一份绑定摘要的审批记录。续跑复用该
生命周期上限，而不是另开一份新预算。每个请求在派发前按所属 pack 的上限预扣，并在
拿到完整 Provider 用量后结算；账目不完整属于基础设施故障，不是继续花费的许可。

## 正式结果

最终留档的 Ship-1 campaign 从干净的源码 commit
`e6c790e37d707f74c44896dbcba9de9ee4ad8327` 出发，使用
`deepseek / deepseek-v4-flash`。该 Provider 没有暴露 seed，因此矩阵记录的是三次
重复，而不是三个 seed。

正式实验 id 为
`abffb7d2fe6a76f1102741cacd3cff1ed02697be0fb37fe2fa7a910dbeb11b4d`：

- `ship_complete=true`，但 `measurement_valid=false`；
- 全部 216 个计划内 E2E Trial 和全部 260 个 Retrieval Case 都有终态记录；
- 被选中的 E2E 结果为 82 通过、72 次 task 失败、61 次 task 超时、1 次基础设施
  故障；
- 120 个 Pair 中 119 个有效。一次 Context 对比在 treatment 用量证据不完整的情况
  下用尽了它的对称重试；
- 反复从原始制品重建报告得到 report 摘要
  `25ca985d2f80560fba789d14fc76acc07d0a45ea3b6a0b4aa7a3d4cfadf19eb1`；
- 主 campaign 累计账本记录的 Provider 高水位为 25.26335175 CNY，计入固定的 5 CNY
  外部服务预留后为 30.26335175 CNY 的已承诺金额。这是预算控制口径的估计，不是
  Provider 账单。

把最终留档的主 campaign、semantic v1 重放和 semantic v2 campaign 合在一起，三条
Provider 高水位分别为 25.26335175、0.13745664 和 0.21468672 CNY，合计
25.61549511 CNY，未结算预扣为零。这一跨账本合计同样是预算控制口径的估计，不是
Provider 账单。

全局 `positive_claim_eligible` 为 false，`cv-metrics.json` 不导出任何指标。
Context 只有 23 个有效 Pair，因此按其声明的 pack 规则，整体测量无效。Tool/MCP
也独立地不具备资格，尽管渐进披露在六个可测量 task 上把等 task 宏平均的可见 Tool
Schema Token 估计值降低了 93.4513%：treatment 组 24 个 Trial 通过 20 个，而
control 组 24 个通过 23 个，其中一个 task 在它的三次通过中至少丢掉了两次。Semantic
Memory 端到端在 treatment 与 control 两组中都是零通过，也没有 verifier 层面的增益。
这些被保留下来的失败是产品发现，不是正向的复跑主张。

## 证据边界

calibration 与正式 campaign 的 task id、query id 互不重叠。Claim Rules 在真实
preflight 之前完成哈希。每个计划内的 Trial 与 Retrieval Case 都必须有一条终态
记录，报告只由这些记录重建。Provider、基础设施、超时、取消与 task 失败都保留在
制品中。

`ship_complete` 表示 campaign 与证据链已经完成。
`measurement_valid` 表示保留下来的测量可以被解释。
`positive_claim_eligible` 按全局和按能力分别报告；只有通过其所在能力组全部规则的
指标才会进入 `cv-metrics.json`。一个有效的负向结果可以完成 Ship-1，但不会因此
成为正向的复跑主张。

确定性的 R0 与 R1 Runtime 指标单独从干净的源码 commit 导出，成为一份不可变、
自带摘要的 Runtime 证据制品。当前制品绑定源码 commit
`e6c790e37d707f74c44896dbcba9de9ee4ad8327`，证据摘要为
`1c9fc1c4882ff09e3cf44140d84206bfb5ce923344cf7e482615a36e4f0f6006`。
引用这些指标时必须带上它们显式的 Scheduler 或全路径确定性范围；它们不是实时吞吐、
task 效果或生产 SLO 主张。

原始 Trial、trace、Memory 内容、回执和生成的报告都留在
`.pico/evidence/picobench/` 下，不进入版本控制。

# Runtime scheduler 实验

Runtime scheduler benchmark 分离出三条结论，仅靠原先的 dispatch overhead
探测无法支撑它们。它使用确定性的本地 workload，使 Provider 与网络的抖动
无法主导排队行为。这些结果是 scheduler 层面的证据，不是生产环境的服务级别
目标。

在干净的 checkout 中运行冻结的默认配置：

```bash
make picobench-runtime-scheduler
```

该命令会把不可变证据写入
`.pico/evidence/picobench-runtime-scheduler/`。生成的证据始终保留在 Git
之外。只有每个 correctness Gate 都通过，并且 commit、依赖 lock、环境标识与
clean worktree 在整轮运行期间保持稳定，一条结果才具备 claim 资格。

## 实验 1：Session 队头阻塞隔离

对照 arm 是一个严格的全局 FIFO，带有固定的 worker 上限和按 Session
串行化。如果队列头部属于一个已在运行的 Session，后面的 Session 就得等待。
处理 arm 是 Pico 的 session Lane scheduler，使用相同的 USER 并发上限。两个
arm 收到同一份有序 trace：一段很长的 hot-session 突发，穿插来自其他 Session
的短 foreground Turn。

主要指标是 foreground P95 queue wait。每次成对重复都会交换 arm 顺序。报告
的改善取成对 P95 降幅的中位数，而不是把重复样本合并之后再算分位数。

## 实验 2：foreground 与 background 的 bulkhead 隔离

对照 arm 把 USER、CRON 与 SUBAGENT 的工作映射到同一个共享信号量。处理 arm
使用相互独立的 USER 池与 Runtime origin 池。两种策略的总标称容量相同，并
运行同一份 idle trace 与 background 饱和下的 foreground trace。

主要指标是带负载的 foreground P95 queue wait 与 idle foreground P95 queue
wait 之比。报告比值可以抵消重复之间的宿主机级计时差异。策略与负载顺序在
成对重复之间交替。

## 实验 3：已接受请求的 fate 归账

request-fate 实验复用既有的 R0 Runtime conformance track。它覆盖正常执行、
排队中与运行中的取消、injection、interrupt、shutdown、origin 限额，以及
drain 之后的拒绝。它汇总所有已被接受的请求，要求丢失请求数、意外的重复
执行、未 resolved 的 Handle、生命周期矛盾以及池上限违规全部为零。

这是一条进程内的保证，覆盖从 scheduler 接受到终态 Handle resolved 的区间。
它不声称跨进程崩溃或外部副作用的 exactly-once 执行。

## Live Agent 响应实验

live 扩展保留队头阻塞对比，但把脚本化的延迟替换为
`AgentTurnRunner -> AgentLoop -> configured Provider` 调用。每条 foreground
prompt 拥有一个唯一的 marker。只有当回复包含该 marker、Provider usage 完整、
没有调用 Tool、且 Runtime 到达终态结果时，一个 Turn 才是可计量的。

对照 arm 与处理 arm 收到相同的 prompts、相同的顺序，使用相同的 Provider 与
模型，并在 80 次成对重复中采用均衡交替的 arm 顺序。每个 arm 包含来自同一个
热会话的两个连续 Turn，随后是 24 个 foreground conversation，合计 4,160 个
真实 Agent Turn。主要指标是 foreground accept-to-terminal P95 latency。报告
的效果取成对 P95 降幅的中位数，并给出确定性的 10,000 次重采样 bootstrap 95%
置信区间。

每个 Turn 都以原始记录保留，包含其提交序号、conversation、accept/start/
terminal 偏移、queue wait、执行时间、端到端 latency、usage、调用次数以及
Verifier 失败项。只有所有 Turn 都通过各自的 task Verifier、置信区间下界为正，
并且每个 Provider、usage、budget、checkout 与 performance Gate 都通过，结果
才具备资格。这是一次对抗性的队头阻塞突发 benchmark，不是生产流量模型，也不
是服务级别目标。

live 执行是需单独审批的付费动作。先冻结 clean commit、精确的 manifest、最大
请求尝试次数与人民币硬性上限：

```bash
make picobench-runtime-live-plan
```

然后传入精确的、已获批的 manifest digest 与金额：

```bash
PICO_LIVE_PERF_APPROVAL_DIGEST=<digest> \
PICO_LIVE_PERF_APPROVED_CNY=<amount> \
make picobench-runtime-live-run
```

在不调用 Provider 的前提下，从保留的原始 Turn 记录重建摘要与置信区间：

```bash
PICO_LIVE_PERF_EVIDENCE=<run-artifact.json> \
make picobench-runtime-live-verify
```

## 正式 live campaign 结果

正式 campaign 绑定到 source commit
`00fd757f1b55cb05f67bde099de2b1196d690db6`、plan digest
`d45e5ba88b8f07a82276612170bdbf2b9205f15d3c3b73ac1534378e7c1b4e8c`
以及 evidence digest
`07f8c955347f50797e8f4e4aafb02ee85cd9e3ab06547ecaa75cc0fd9fd8bf59`。
该 source SHA 作为实验身份保留。它的开发分支不在本发布仓库中公开。
本轮运行完成 80 次成对重复，并保留 4,160 条原始 Turn 记录。

foreground P95 的中位数从严格全局 FIFO 下的 13,567.997 ms 降到 session Lane
下的 11,663.193 ms，降幅 13.53%。确定性的 10,000 次重采样成对 bootstrap
95% 置信区间为 11.36% 到 15.26%。全部 4,160 个请求都得到执行，缺失执行、
重复执行、runner 异常与 Provider 失败均为零。

task Verifier 在 4,160 个 Turn 中通过 4,158 个，即 99.95%。两次失败都是
`marker_missing`：两条请求都到达正常终态结果，usage 完整、回复明确，但模型
回复漏掉了自己的唯一 marker。其中一条回复触到 512 completion token 上限。
这些属于模型回复质量问题，不是 scheduler 丢失请求或 Provider 错误。

预先注册的 `all_tasks_verified` Gate 要求 4,160 个 marker 全部通过，因此
聚合制品记录 `claim_eligible: false`。摘要与对外措辞必须报告 99.95% 的
Verifier 通过率，且不得声称每个任务都通过。基于原始记录的 verifier 独立
复现了 P95 降幅、置信区间、usage 合计与请求完整性计数。

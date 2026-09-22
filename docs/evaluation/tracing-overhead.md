# Tracing Runtime 开销

> **状态：正式运行已于 2026-08-13 完成。** 生成的证据保留在 Git 之外；
> 本页记录它的 candidate 绑定与各项 digest。

这条 PicoBench track 度量 Pico 树内 Tracing 带来的本地 Runtime tax。它不
测试外部 Provider，也不对外声称生产环境的 latency。

## 处理与 workload

campaign 运行 20 个均衡 block，每个 block 含 50 对 Turn，合计 1,000 对、
2,000 个 Turn。每个 Turn 都经过共享的 Runtime Assembly 与 Agent Loop，发起
两次确定性的本地 Provider 调用，执行一次 `trace_lookup`，并返回 `TRACE_OK`。
唯一的处理轴是 `PICO_TRACING=0` 与 `PICO_TRACING=1`。

每个开启 Tracing 的 Turn 必须恰好保留一条终态 `session.turn` trace，并挂接
两个 `llm.call` span 与一个 `tool.call` span。关闭 arm 不得输出任何 trace
字节。两个 arm 必须完成同一 workload，且回复与调用次数完全一致。

## 指标与证据

聚合结果报告两个 arm 的 P50 与 P95 latency、相对 overhead、按 block 聚类的
P95 比值 bootstrap 95% 区间，以及每个被 trace 的 Turn 的字节数。度量有效性
要求所有 correctness、correlation、Pair-count、arm-balance 与
disabled-no-output Gate 全部通过。这里没有预先注册的“良好 overhead”阈值；
结果是一项估算出来的运维 cost，不是优化主张。

不可变 manifest 绑定 Pico commit、Python 与平台标识、workload、Pair 数量与
bootstrap 设置。逐 block 的回执保留原始 Turn latency 与终态结果，并为每个
trace 文件保存 SHA-256 回执。离线 verifier 重建 `raw-outcomes.jsonl`、
`aggregate.json`、`claim-eligibility.json`、`verifier-report.json` 与
`inventory.json`。

## 结果

1,000 对与 2,000 个 Turn 全部有效。开启 arm 恰好保留 1,000 条 trace 与
6,000 个 span，correlation 为 100%；关闭 arm 输出的 trace 字节为零。Tracing
在每个开启的 Turn 上写入 25,717.2 字节。

| 指标 | Tracing 关闭 | Tracing 开启 |
| --- | ---: | ---: |
| P50 Turn latency | 2.061208 ms | 4.284334 ms |
| P95 Turn latency | 2.912292 ms | 5.157333 ms |

观测到的 P95 tax 为 2.245041 ms，相对于这个很小的本地基线是 77.0885%。
按 block 聚类的相对 P95 区间为 -9.9969% 到 101.9378%，因此该结果不支持任何
稳定的相对 overhead 结论。它支持的是精确的 correlation，以及一个绝对量的
本地 tax 估算。

聚合结果的 SHA-256 是
`29b855459d6039f7630f410a623875a37a7e454f4a978aae265330fb023cec65`。
原始 manifest 与清单有意不在本仓库发布。

## 运维命令

```bash
make picobench-tracing-plan
make picobench-tracing-run
make picobench-tracing-verify
```

设置 `PICO_TRACING_OUTPUT` 可改用新的 evidence 根目录。当仓库已经前进到被测
candidate 之后，在运行离线 verifier 之前，需把 `PICO_TRACING_COMMIT` 设为
保留 manifest 所绑定的完整 commit。

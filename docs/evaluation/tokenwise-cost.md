# DeepSeek TokenWise cost 实验

> **状态：2026-08-13 通过当前的 CallEfficiency 重跑。** 冻结的 DeepSeek V4
> Flash campaign 完成了 36 个有效 Comparison Block、72 次 Trial 和 504 次真实
> Provider 调用。所有 Claim Gate 均通过。

本页保留历史的 TokenWise 实验名以维持连贯。当前生效的 Runtime 子系统是
CallEfficiency，本轮 campaign 走的是共享的 Runtime Assembly，并为每次物理
尝试保留一条 Call Record。

## 问题

在请求前缀保持稳定时，DeepSeek 的自动磁盘 Context cache 能把一个已验证成功的
Pico Agent 任务的估算 API cost 降低多少？

DeepSeek 会忽略 Anthropic 的 `cache_control` marker。因此 TokenWise 不为该
Provider 设置显式的 breakpoint。它把 DeepSeek 的 `prompt_cache_hit_tokens` 与
`prompt_cache_miss_tokens` 归一化，用 Provider 的 cache-hit、cache-miss 与输出
单价重建 cost，并度量前缀稳定性的价值。

## 处理轴

每个 Comparison Block 都在两种策略下执行同一任务。两个 arm 中 DeepSeek 的
自动 cache 始终保持开启。

| 策略 | 请求行为 | 角色 |
| --- | --- | --- |
| `prefix_disrupted` | 在每次 Provider 调用之前改动开头的 system 与 Tool Schema 字节 | 负向对照 |
| `prefix_stable` | 保持 Pico 常规的请求前缀 | 处理组 |

被扰动的 arm 是一种实验性的反事实构造，不是更早的产品版本，也不是可部署的
配置。每次 Trial 使用独立的 DeepSeek `user_id`，因此一个 arm 无法为另一个
arm 预热 KV cache。

Provider、精确模型、non-thinking 生成模式、Tool 集合、Context 预算、
workspace fixture、prompts 与重试上限都保持固定。禁止 fallback。

## 冻结 workload 矩阵

本轮 campaign 包含四类 workload，每类三个 case，各重复三次：

| workload 类别 | 可观测的压力 | 每次 Trial 的形态 |
| --- | --- | --- |
| `stable_dialogue` | 重复且稳定的 system 指令 | 六个短 Turn，不使用 Tool |
| `long_history` | 不断增长的 conversation 前缀 | 在 16 个预置 history Turn 之后执行六个 Turn |
| `tool_accumulation` | Tool schema 与结果跨 Turn 累积 | 六个 Turn，每个 Turn 一次经过验证的 Tool 调用 |
| `intra_turn_tool_chain` | 单个 Turn 内由 Tool 结果扩展前缀 | 一个 Turn，包含一次经过验证的三步 Tool chain |

由此得到 36 个 Comparison Block 与 72 次 Trial。一次 Trial 指一个策略把某个
case 执行一次。本轮 campaign 共发出 504 次真实 Provider 调用。

## 指标与 Gate

主要指标是每次已验证成功的估算 cost：

```text
cost_per_verified_success = sum(all valid Trial cost) / verified successes
```

失败的任务仍留在分子中。保守口径的 cache 命中率是：

```text
cache_read / (cache_miss + cache_read)
```

只有在以下条件全部满足时，报告才导出 CV 指标：所有规划的 block 均有效；每条
usage 记录都满足 `prompt = cache_hit + cache_miss`；每一次调用都由所请求的
精确模型服务；四类 workload 全部在场；处理组的任务成功度没有回退；稳定前缀
同时改善 cache 命中率与 cost per verified success。

## 结果

本轮 campaign 固定使用 `deepseek/deepseek-v4-flash`。冻结的价格快照为：
cache-miss 输入 0.14 美元每百万 Token、cache-hit 输入 0.0028 美元每百万
Token、输出 0.28 美元每百万 Token。

| 指标 | 前缀被扰动 | 前缀稳定 |
| --- | ---: | ---: |
| 有效 Trial 数 | 36 | 36 |
| 已验证任务通过率 | 100% | 100% |
| 保守口径 cache 命中率 | 0% | 74.0478% |
| 每次已验证成功的估算 cost | $0.008356 | $0.002311 |

在总体上，稳定前缀把 cost per verified success 降低了 **72.3413%**。按任务
聚类的成对估计为 **72.0750%**，95% 区间为 **68.8471% 至 75.0961%**。36 个
Comparison Block 全部有效，没有出现 fallback 或 model drift，整轮 campaign
的估算花费为 0.384031 美元。

处理组在各 workload 上的命中率分别是：stable dialogue 65.12%、long history
75.72%、Tool accumulation 79.31%、intra-Turn Tool chain 65.47%。

## 证据边界

该结果证明：在冻结 workload 之下，Pico 的稳定请求前缀能从 DeepSeek 的自动
cache 中获益，并且 TokenWise 能重建 DeepSeek 的 cache 用量与估算 cost。它
不能证明 Pico 创建了 DeepSeek 的 cache，不能证明每个生产 workload 都会达到
75.19% 的命中率，也不能证明该估算已与 Provider 账单做过对账。

当前报告保留在 Git 之外的
`.pico/evidence/call-efficiency-cost/1df7029-formal/`。其 SHA-256 是
`b905ec833231236a53959cf78b05c89ca9b72b4066055aa5b6e3c327df3e4337`。
原始 manifest、不可变输入与独立报告制品有意不在本仓库发布。

## 复现

CallEfficiency 的 replay 路径不发出任何 Provider 调用。它校验历史报告的
digest，用内嵌的冻结价格快照重新计算每一次 Trial，并再次运行原有的 reducer：

```bash
uv run python -m benchmarks.picobench.packs.tokenwise_cost.replay \
  --source-report .pico/evidence/tokenwise-cost-deepseek-rebased/report.json \
  --expected-source-digest fcde99b98c8bc46d0852015d7a92c01a0de6a4e4216f773045375f2f06e75aec \
  --output .pico/evidence/call-efficiency-replay/report.json
```

`--expected-source-digest` 是外部的 lineage 绑定。它必须来自单独可信的
manifest 或冻结的证据记录；从被校验的那份报告本身复制 digest 并不能确立来源。
缺少该绑定时，replay 拒绝声称等价，并拒绝覆盖自己的来源制品。

`equivalent: true` 的结果只建立制品层面与 reducer 层面的等价。它不是新的
live Runtime 结果。

当前的付费 runner 走共享的 Runtime Assembly，并通过 CallEfficiency 观察每一
次物理 Provider 尝试。它保留原始的 Provider 与 CallEfficiency 回执，应用按
任务聚类的成对 bootstrap 区间，并离线重建结果。付费模式仍然需要显式 flag
才生效：

```bash
uv run python -m benchmarks.picobench.tokenwise_cost_campaign \
  --mode preflight \
  --output-root .pico/evidence/call-efficiency-cost-current \
  --execute-paid-campaign

uv run python -m benchmarks.picobench.tokenwise_cost_campaign \
  --mode formal \
  --output-root .pico/evidence/call-efficiency-cost-current \
  --execute-paid-campaign

uv run python -m benchmarks.picobench.tokenwise_cost_campaign \
  --mode verify \
  --output-root .pico/evidence/call-efficiency-cost-current
```

runner 先读取 `DEEPSEEK_API_KEY`，随后回退到 Pico 配置中的
`providers.deepseek.apiKey`。它绝不会把凭证写入制品。当观测到的估算花费达到
2 美元、或 Provider 调用达到 1,200 次时，它会在发起新调用之前停止。

正式 campaign 仍是 12 个冻结任务乘以三次重复再乘以两个 arm：36 对、72 次
Trial。正向 claim 还额外要求：每个任务都通过；Usage 与 cost 数据完整；由
精确模型执行且无 fallback；每次物理尝试持久化一条 CallEfficiency 记录；
ledger 健康；并且成对的 cost 降幅置信区间下界大于零。verifier 在不发起
Provider 调用的前提下，写出原始结果、重建后的聚合值、claim 资格、verifier
状态以及 SHA-256 清单。

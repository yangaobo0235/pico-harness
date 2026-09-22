# ClawBench 流式 Runner

本目录包含一个只面向 Pico 的 ClawBench runner。它在同一个持久的 Pico session 中
顺序执行 task：

1. 准备 task 1 的 workspace；
2. 通过 `AgentLoop.run_turn()` 提交一个 `TurnRequest`；
3. 用 ClawBench 的 verifier 对 workspace 打分；
4. 不清空该 Pico session，对 task 2 重复同样的步骤。

ClawBench 数据集没有随本仓库内置。请单独克隆该仓库，并把 runner 指向那个
checkout。

## 准备

```bash
git clone https://github.com/claw-bench/claw-bench ../claw-bench
export CLAW_BENCH_ROOT="$PWD/../claw-bench"
```

正常安装 Pico，然后配置模型。对任意 OpenAI 兼容网关，benchmark runner 都使用
OpenRouter 风格的环境变量名：

```bash
export OPENROUTER_API_KEY="..."
export OPENROUTER_API_BASE="https://openrouter.ai/api/v1"
export PICO_BENCH_PROVIDER="custom"
export PICO_BENCH_MODEL="deepseek-v4-flash"
```

可选的 web 工具：

```bash
export SERPER_API_KEY="..."
export JINA_API_KEY="..."
```

也可以把同样的值写进 `~/.pico/config.json`：

```json
{
  "agents": {
    "defaults": {
      "provider": "custom",
      "model": "deepseek-v4-flash",
      "maxToolIterations": 40,
      "contextWindowTokens": 65536
    }
  },
  "providers": {
    "custom": {
      "apiKey": "YOUR_API_KEY",
      "apiBase": "YOUR_OPENAI_COMPATIBLE_API_BASE"
    }
  },
  "tools": {
    "web": {
      "jinaApiKey": "YOUR_JINA_KEY",
      "search": {
        "apiKey": "YOUR_SERPER_KEY"
      }
    }
  }
}
```

不要提交真实密钥。

## 运行

对单个 task 做 smoke test：

```bash
./benchmarks/clawbench/run.sh \
  --clawbench-root "$CLAW_BENCH_ROOT" \
  --task cal-001 \
  --session-id clawbench-smoke
```

把前 80 个 task 作为一个流式 session 运行：

```bash
./benchmarks/clawbench/run.sh \
  --clawbench-root "$CLAW_BENCH_ROOT" \
  --limit 80 \
  --session-id clawbench-stream-pico-80 \
  --max-iterations 40
```

启用 Curator 运行：

```bash
./benchmarks/clawbench/run.sh \
  --clawbench-root "$CLAW_BENCH_ROOT" \
  --limit 80 \
  --session-id clawbench-stream-pico-curator-80 \
  --context-engine curator \
  --curator-model deepseek-v4-flash \
  --max-iterations 40
```

常用的过滤方式：

```bash
./benchmarks/clawbench/run.sh --domain data-analysis --limit 5
./benchmarks/clawbench/run.sh --level L4 --limit 3
./benchmarks/clawbench/run.sh --task cal-001,code-001,xdom-014
```

## 输出

默认情况下，输出写入 `benchmarks/clawbench/results/`：

- `run_<timestamp>/workspaces/` — 每个 task 独立的 workspace；
- `run_<timestamp>/transcripts/` — prompt、最终回复、错误；
- `run_<timestamp>/partial_results.json` — 每个 task 结束后更新；
- `pico_clawbench_stream_<timestamp>.json` - 最终汇总；
- `pico_clawbench_stream_<timestamp>.tokens.csv` - 逐 task 的 Token 记录；
- `results.md` — 实时更新的 markdown 表格。

Token 各列使用 Provider 上报的 `response.usage`。`context_used` 是该 task 最后一次
模型调用的 prompt 与 completion Token 之和；它不是该 task 全部 Token 的累加值。

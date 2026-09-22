# Pico Benchmark 总览

本目录存放与 Runtime 包刻意解耦的**评测 harness**。`pico/` 不会导入它们，
它们也不参与 wheel 构建——请保持这一状态。

`pinchbench/tasks/` 下的 Markdown task 卡片是可执行的评测 fixture，不是 Pico
产品文档。其中一些 task 故意探测 Pico 已经移除的能力，包括图片生成和远程 Skill
发现。一张 task 卡片的存在，不能证明当前 Runtime 支持该 Tool。

请把本区域用于可复现的评测工作：能力套件、Agent 对比，以及不应随终端用户 CLI
包一起发布的 Context 压力测试。

## PicoBench

`benchmarks/picobench/` 下的 PicoBench Ship-1 是只在仓库 checkout 中可用的 Agent
应用评测 harness。它的契约记录在[公开评测说明](../docs/evaluation/README.md)中，
通过冻结的单轴配对 task 与由父进程持有的确定性 verifier 来评测现有 Runtime。

实现本身不会产出结果主张。生成的 PicoBench 证据始终留在 Git 之外。发布完整性
（Ship Completeness）与测量有效性（Measurement Validity）约束整个 campaign，而
每项能力各自适用自己的正向结论资格（Positive Claim Eligibility）规则。
PinchBench、EvalEngine、Evolver 证据、PicoBench 与 V-R0 仍是互相独立的范围。

最终留档的 Ship-1 campaign 完成了全部 216 个计划内 E2E Trial 和 260 个
Retrieval Case，但有一个 Context Pair 缺少完整的用量证据，使整体测量无效。
Tool 披露方式同时让 task 通过数出现回退，因此保留的主 campaign 材料不导出任何
正向 CV 指标。已公开的实验边界见 [PicoBench](picobench/README.md)。

## 目录结构

```
benchmarks/
├── appworld/           AppWorld agent benchmark + evolver plugin
│   ├── agent_cli.py       单 task subject agent（驱动 AgentLoop）
│   ├── batch.py           批量打分器：N tasks x K trials，可续跑
│   └── evolve/            pico.evolver BenchBundle plugin (entry.py)
│                          外加 designer/diagnosis/sandbox/precheck 胶水代码
│
├── evolver/            确定性 Evolution Run 的 subject
│   ├── small_real.yaml     单轮 run spec（+ --smoke overlay）
│   └── subject_template/   一次性的 subject：一份有缺陷的 agent_cli.py 加上
│                           它自己的 bench plugin；由
│                           scripts/setup_small_real_subject.py 实例化到
│                           subject/（gitignored）
│
├── pinchbench/         Context / AgentLoop 能力 benchmark
│   ├── tasks/             23 张 task_*.md 卡片（YAML frontmatter + 分节）
│   ├── direct/            逐 task 驱动 AgentLoop.run_turn()
│   ├── bot_runner/        逐 task 驱动完整 gateway + channel 链路
│   ├── assets/            task 专属的 workspace 文件
│   └── results/           运行输出（gitignored）
│
├── picobench/          Agent 应用评测 harness
│   ├── packs/             Runtime、Context、Memory/Skill 与 Tool/MCP 轨道
│   ├── suites/            冻结的实验计划与 claim 规则
│   └── README.md          smoke、campaign、重建与证据边界
│
├── clawbench/          ClawBench 流式 benchmark 适配器
│   ├── stream.py          在同一个 session 内驱动 AgentLoop.run_turn()
│   ├── run.sh             Shell 包装脚本
│   └── README.md          配置与运行说明
│
├── skill_evals/        保留的 SkillForge 评测所用查询语料
│   └── queries.jsonl      由 scripts/skill_forge_retrieval_eval.py 使用
│
└── README.md           本文件
```

运行 `uv run python scripts/skill_forge_retrieval_eval.py` 可执行自包含、离线的
SkillForge 检索评测。随着远程 skill 检索架构退役，已废弃的 SQLite 大规模库
runner 一并移除。

## 运行

### 模型与工具配置

Benchmark runner 可以使用常规的 `~/.pico/config.json`，也可以使用下面的环境变量
覆盖。绝不要把真实密钥提交进仓库。

使用 OpenRouter 风格的环境变量名接入 OpenAI 兼容网关：

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

等价的 `~/.pico/config.json`：

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

PinchBench（Direct 模式）：
```bash
./benchmarks/pinchbench/direct/run.sh \
    --model deepseek-v4-flash \
    --provider custom \
    --api-base "$OPENROUTER_API_BASE" \
    --api-key "$OPENROUTER_API_KEY" \
    --suite task_00_sanity
```

PinchBench（Bot 模式）：
```bash
./benchmarks/pinchbench/bot_runner/run.sh --suite automated-only
```

ClawBench（前 80 个 task，单个流式 session）：
```bash
git clone https://github.com/claw-bench/claw-bench ../claw-bench
export CLAW_BENCH_ROOT="$PWD/../claw-bench"

./benchmarks/clawbench/run.sh \
    --clawbench-root "$CLAW_BENCH_ROOT" \
    --limit 80 \
    --session-id clawbench-stream-pico-80 \
    --max-iterations 40
```

ClawBench 搭配 Curator Context 引擎：
```bash
./benchmarks/clawbench/run.sh \
    --clawbench-root "$CLAW_BENCH_ROOT" \
    --limit 80 \
    --session-id clawbench-stream-pico-curator-80 \
    --context-engine curator \
    --curator-model deepseek-v4-flash \
    --max-iterations 40
```

## 与 Runtime 的关系

Runtime（`pico/`）**从不静态导入 `benchmarks/` 中的任何内容**——这就是“独立评测
轨道”原则。反向依赖是允许且符合预期的：benchmark 可以直接导入 `pico.agent`、
`pico.providers` 等。

一个受限的例外：`pico.evolver` 在启动时按注册名从这里加载它的 bench *plugin*
（`benchmarks.appworld.evolve.entry:build`），并先把 subject 仓库根目录插入
`sys.path`。它是惰性、需显式启用、且只在仓库 checkout 下可用的——演进本来就需要
git 仓库作为 subject，因此安装后的 wheel 没有任何部分依赖本目录。

AppWorld 是仓库 checkout 场景的示例。纳入版本控制的 small-real 模板会实例化一个
一次性的 subject 仓库，它自带已注册的 benchmark plugin 和不可变的 grader。
方法学/设计说明中提到的 EvoAgentBench 或其他 benchmark 线路，在没有对应代码的
情况下，只能视为计划中或历史内容。

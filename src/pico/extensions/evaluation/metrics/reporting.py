"""把指标与实验结果排版成人和简历能读的东西。

`collect_resume_metrics` 是这一层的装配点：它先读两份工件（benchmark 与 ``.pico/runs``）拿到已经发生
的事实，再按 ``experiment_mode`` 决定跑合成实验还是真实模型实验，最后连同 ``resume_highlights`` 一起
返回一份大字典。`render_resume_metrics_markdown` 与 `render_large_scale_experiment_report` 只吃这份
字典，按固定小节标题排出 markdown；`_write_json_artifact` 是三个 ``*_v2`` 入口共用的落盘动作，
`write_benchmark_core_report` 则只读四份 v2 工件写出核心报告。

边界：这一层不重新计算任何口径——所有数字都来自 `aggregates` 的聚合与 `experiments` 的实验返回值，
它只负责挑选、格式化与排版，因此改这里不会影响任何测量结果，也修不好一个错掉的测量。格式化精度是
公开约定的一部分：比率一律 ``:.2%``，平均字符数与平均步数用 ``:.2f``，平均缓存 token 用 ``:.1f``，
压力场景的 Prompt 字符数先 `int(round(...))` 再打印；小节标题与逐行文本被 tests 断言，新增内容请追加
在末尾。`write_benchmark_core_report` 刻意只覆盖 Harness / Context / Memory / Recovery 四层，不把
provider 与 run aggregation 的结论混进来，避免一份报告里出现两种可比性。
"""

import json
from pathlib import Path
from typing import Any

from pico.extensions.evaluation.metrics.ablations import run_memory_dependency_experiment
from pico.extensions.evaluation.metrics.aggregates import (
    DEFAULT_CONTEXT_ABLATION_V2_PATH,
    DEFAULT_CORE_REPORT_PATH,
    DEFAULT_HARNESS_REGRESSION_V2_PATH,
    DEFAULT_MEMORY_ABLATION_V2_PATH,
    DEFAULT_RECOVERY_ABLATION_V2_PATH,
    aggregate_benchmark_artifact,
    aggregate_run_artifacts,
)
from pico.extensions.evaluation.metrics.experiments import (
    build_stress_agent_metrics,
    run_context_stress_matrix,
    run_large_scale_memory_experiment,
    run_real_context_experiment,
    run_real_memory_experiment,
    run_real_security_experiment_suite,
    run_security_experiment_suite,
)


def collect_resume_metrics(
    benchmark_artifact_path: str | Path,
    runs_root: str | Path,
    provider_experiments: str | Path | None = None,
    memory_repetitions: int = 3,
    large_memory_repetitions: int = 5,
    context_repetitions: int = 5,
    security_repetitions: int = 3,
    experiment_mode: str = "synthetic",
    real_provider: str = "gpt",
) -> dict[str, Any]:
    """把工件聚合与实验结果收进一份字典，供两个 ``render_*`` 函数排版。

    ``benchmark_artifact_path`` 与 ``runs_root`` 是必需的两份已有工件；``provider_experiments`` 默认
    ``None``，此时 ``provider_experiments`` 字段就是 ``{"providers": []}``，给了路径才按 JSON 读进来。
    四个 repetitions 参数分别是小记忆（默认 3）、大记忆（5）、上下文矩阵（5）、安全场景（3）。
    ``experiment_mode`` 默认 ``synthetic``，取 ``real`` 时整套实验换成真实模型版本，并用
    ``real_provider``（默认 ``gpt``）装配。

    返回字典含 ``experiment_mode``、``real_provider``、``facts``、``benchmark``、``runs``、
    ``stress_ablation``、``memory_experiment``、``memory_large_experiment``、``context_experiment``、
    ``security_experiment``、``provider_experiments`` 与 ``resume_highlights``。三处容易被误改的口径：
    ``real_provider`` 只在 ``real`` 模式下给值，否则是空串；``facts`` 是平台事实的常量声明（3 个模型
    后端、7 类工具、每次运行 3 份工件），不从工件推导；``stress_ablation`` 在 ``real`` 模式下由上下文
    实验的 ``avg_full_prompt_chars`` / ``avg_raw_prompt_chars`` 四舍五入成整数拼出来，形状与合成模式
    保持同构，好让下游排版不用分叉。

    这里不校验 repetitions 的合理性，也不缓存结果：每次调用都会重跑实验（``real`` 模式即产生付费请求），
    因此调用方需要自己控制频次。工件缺失或 JSON 损坏直接抛异常，因为「半个指标」会被读成「指标变差了」。
    """
    benchmark = aggregate_benchmark_artifact(benchmark_artifact_path)
    runs = aggregate_run_artifacts(runs_root)
    experiment_mode = str(experiment_mode)
    real_provider = str(real_provider)
    if experiment_mode == "real":
        memory_large = run_real_memory_experiment(provider=real_provider, repetitions=large_memory_repetitions)
        memory = {name: dict(values) for name, values in memory_large["variants"].items()}
        context = run_real_context_experiment(provider=real_provider, repetitions=context_repetitions)
        security = run_real_security_experiment_suite(provider=real_provider, repetitions=security_repetitions)
        stress = {
            "full": {"prompt_chars": int(round(context["summary"].get("avg_full_prompt_chars", 0.0)))},
            "no_context_reduction": {"prompt_chars": int(round(context["summary"].get("avg_raw_prompt_chars", 0.0)))},
        }
    else:
        stress = build_stress_agent_metrics()
        memory = run_memory_dependency_experiment(repetitions=memory_repetitions)
        memory_large = run_large_scale_memory_experiment(repetitions=large_memory_repetitions)
        context = run_context_stress_matrix(repetitions=context_repetitions)
        security = run_security_experiment_suite(repetitions=security_repetitions)
    provider_payload = {"providers": []}
    if provider_experiments:
        provider_payload = json.loads(Path(provider_experiments).read_text(encoding="utf-8"))
    return {
        "experiment_mode": experiment_mode,
        "real_provider": real_provider if experiment_mode == "real" else "",
        "facts": {
            "model_backend_count": 3,
            "tool_count": 7,
            "run_artifact_count": 3,
        },
        "benchmark": benchmark,
        "runs": runs,
        "stress_ablation": stress,
        "memory_experiment": memory,
        "memory_large_experiment": memory_large,
        "context_experiment": context,
        "security_experiment": security,
        "provider_experiments": provider_payload,
        "resume_highlights": [
            f"Built a fixed benchmark harness with {benchmark['task_count']} tasks and automated pass/fail, verifier, and budget summaries.",
            f"Recorded 3 run artifacts per execution and structured runtime metadata across {runs['run_count']} aggregated runs.",
            f"Observed prompt-cache telemetry with average cached tokens of {runs['avg_cached_tokens']:.1f} and cache-hit rate of {runs['cache_hit_rate']:.2%} when available.",
            (
                f"In a real-model long-context experiment ({real_provider}), context reduction shrank average prompt size from "
                f"{stress['no_context_reduction']['prompt_chars']} to {stress['full']['prompt_chars']} chars."
                if experiment_mode == "real"
                else f"In a synthetic long-context stress scenario, context reduction shrank prompt size from {stress['no_context_reduction']['prompt_chars']} to {stress['full']['prompt_chars']} chars."
            ),
            f"In the memory dependency experiment, repeated follow-up reads dropped from {memory['memory_off']['repeated_reads']} to {memory['memory_on']['repeated_reads']}.",
            f"In the large-scale memory experiment, repeated reads dropped from {memory_large['variants']['memory_off']['repeated_reads']} to {memory_large['variants']['memory_on']['repeated_reads']} across {memory_large['task_count']} tasks.",
        ],
    }


def render_resume_metrics_markdown(metrics: dict[str, Any]) -> str:
    """把 `collect_resume_metrics` 的结果排成 ``# Pico Resume Metrics`` 那份简历向 markdown。

    ``metrics`` 是那份大字典，函数只读不改。输出依次是 ``## Key Numbers``（逐行列出模式、后端数、
    工具数、benchmark 任务数与通过率、聚合运行数、平均步数与尝试数、缓存命中率、Prompt 字符对照、
    记忆重读对照、大记忆任务数、上下文配置数、安全场景数）、``## Resume Highlights``（原样列出
    ``resume_highlights``），以及只在有 provider 数据时才出现的 ``## Provider Experiments``。

    口径与精度：``pass_rate`` 与 ``cache_hit_rate`` 用 ``:.2%``，``avg_tool_steps`` 与 ``avg_attempts``
    用 ``:.2f``；``experiment_mode`` 缺失时按 ``synthetic`` 打印。``stress_ablation`` 的两个字符数直接
    插值（已经是整数），不再套格式说明符。provider 行只在 ``status`` 为 ``completed`` 时打印四项指标，
    否则打印状态与 ``reason``，缺 reason 写成 ``unknown``。

    这里不补算缺失字段，也不合并两个 render 函数的内容：一次运行要么给出完整对照，要么让 KeyError
    暴露「上游少喂了一份实验」。
    """
    benchmark = metrics["benchmark"]
    runs = metrics["runs"]
    stress = metrics["stress_ablation"]
    memory = metrics["memory_experiment"]
    memory_large = metrics["memory_large_experiment"]
    context = metrics["context_experiment"]
    security = metrics["security_experiment"]
    provider_payload = metrics.get("provider_experiments", {})
    lines = [
        "# Pico Resume Metrics",
        "",
        "## Key Numbers",
        f"- Experiment mode: {metrics.get('experiment_mode', 'synthetic')}",
        f"- Model backends: {metrics['facts']['model_backend_count']}",
        f"- Tool types: {metrics['facts']['tool_count']}",
        f"- Fixed benchmark tasks: {benchmark['task_count']}",
        f"- Fixed benchmark pass rate: {benchmark['pass_rate']:.2%}",
        f"- Aggregated runs: {runs['run_count']}",
        f"- Average tool steps per run: {runs['avg_tool_steps']:.2f}",
        f"- Average attempts per run: {runs['avg_attempts']:.2f}",
        f"- Cache hit rate: {runs['cache_hit_rate']:.2%}",
        (
            f"- Real-model prompt chars (full vs no context reduction): {stress['full']['prompt_chars']} / {stress['no_context_reduction']['prompt_chars']}"
            if metrics.get("experiment_mode") == "real"
            else f"- Synthetic prompt chars (full vs no context reduction): {stress['full']['prompt_chars']} / {stress['no_context_reduction']['prompt_chars']}"
        ),
        f"- Memory repeated reads (on vs off): {memory['memory_on']['repeated_reads']} / {memory['memory_off']['repeated_reads']}",
        f"- Large-scale memory tasks: {memory_large['task_count']}",
        f"- Context matrix configs: {context['config_count']}",
        f"- Security scenarios: {security['scenario_count']}",
        "",
        "## Resume Highlights",
    ]
    lines.extend(f"- {line}" for line in metrics["resume_highlights"])
    providers = provider_payload.get("providers", [])
    if providers:
        lines.extend(["", "## Provider Experiments"])
        for provider in providers:
            if provider.get("status") == "completed":
                lines.append(
                    f"- {provider['provider']}: pass_rate={provider['pass_rate']:.2%}, avg_attempts={provider['avg_attempts']:.2f}, avg_tool_steps={provider['avg_tool_steps']:.2f}, cache_hit_rate={provider['cache_hit_rate']:.2%}"
                )
            else:
                lines.append(f"- {provider['provider']}: {provider['status']} ({provider.get('reason', 'unknown')})")
    lines.append("")
    return "\n".join(lines)


def render_large_scale_experiment_report(metrics: dict[str, Any]) -> str:
    """把同一份指标排成 ``# Pico Large-Scale Experiment Report``，按四个实验主题分节。

    ``metrics`` 同 `collect_resume_metrics` 的返回。小节固定为 ``## Executive Summary``、
    ``## Context Governance``、``## Memory Experiments``、``## Security Experiments``、
    ``## Provider Experiments``、``## Resume-Safe Claims``。provider 名字按 ``real_provider`` →
    上下文实验 → 大记忆实验 → 安全实验 → ``unknown`` 的顺序取第一个非空值，所以三份实验来自同一个
    后端时只会打印一次名字。

    口径与精度：压缩率用 ``:.2%``，平均步数用 ``:.2f``，重读次数是整数总和直接插值；
    ``security_event_counts`` 与 ``tool_error_code_counts`` 用 ``json.dumps(..., sort_keys=True)``
    打印，保证同一份数据两次渲染文本一致。一个 provider 都没有时 ``## Provider Experiments`` 段落写
    ``- none`` 而不是留空。

    这里不重复渲染 resume 版本的内容，也不做跨模式的字段补齐：``experiment_mode`` 决定措辞，
    排版层不去猜另一套模式的数字。
    """
    benchmark = metrics["benchmark"]
    memory_small = metrics["memory_experiment"]
    memory_large = metrics["memory_large_experiment"]
    context = metrics["context_experiment"]
    security = metrics["security_experiment"]
    providers = metrics.get("provider_experiments", {}).get("providers", [])
    report_provider = (
        metrics.get("real_provider")
        or context.get("provider")
        or memory_large.get("provider")
        or security.get("provider")
        or "unknown"
    )
    lines = [
        "# Pico Large-Scale Experiment Report",
        "",
        "## Executive Summary",
        (
            f"- Experiment mode: real-model (provider: {report_provider})"
            if metrics.get("experiment_mode") == "real"
            else f"- Experiment mode: {metrics.get('experiment_mode', 'synthetic')}"
        ),
        f"- Fixed benchmark tasks: {benchmark['task_count']}",
        f"- Large-scale memory tasks: {memory_large['task_count']}",
        f"- Context stress configurations: {context['config_count']}",
        f"- Security scenarios: {security['scenario_count']}",
        "",
        "## Context Governance",
        (
            f"- Real-model prompt chars ({report_provider}): {metrics['stress_ablation']['full']['prompt_chars']} vs {metrics['stress_ablation']['no_context_reduction']['prompt_chars']}"
            if metrics.get("experiment_mode") == "real"
            else f"- Synthetic stress prompt chars: {metrics['stress_ablation']['full']['prompt_chars']} vs {metrics['stress_ablation']['no_context_reduction']['prompt_chars']}"
        ),
        f"- Average prompt compression ratio across context matrix: {context['summary']['avg_prompt_compression_ratio']:.2%}",
        f"- Max prompt compression ratio across context matrix: {context['summary']['max_prompt_compression_ratio']:.2%}",
        "",
        "## Memory Experiments",
        f"- Small memory experiment repeated reads: {memory_small['memory_on']['repeated_reads']} vs {memory_small['memory_off']['repeated_reads']}",
        f"- Large memory experiment repeated reads: {memory_large['variants']['memory_on']['repeated_reads']} vs {memory_large['variants']['memory_off']['repeated_reads']}",
        f"- Large memory experiment avg tool steps: {memory_large['variants']['memory_on']['avg_tool_steps']:.2f} vs {memory_large['variants']['memory_off']['avg_tool_steps']:.2f}",
        "",
        "## Security Experiments",
        f"- Security event counts: {json.dumps(security['security_event_counts'], sort_keys=True)}",
        f"- Tool error code counts: {json.dumps(security['tool_error_code_counts'], sort_keys=True)}",
        "",
        "## Provider Experiments",
    ]
    if providers:
        for provider in providers:
            if provider.get("status") == "completed":
                lines.append(
                    f"- {provider['provider']}: pass_rate={provider['pass_rate']:.2%}, avg_attempts={provider['avg_attempts']:.2f}, avg_tool_steps={provider['avg_tool_steps']:.2f}, cache_hit_rate={provider['cache_hit_rate']:.2%}"
                )
            else:
                lines.append(f"- {provider['provider']}: {provider['status']} ({provider.get('reason', 'unknown')})")
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Resume-Safe Claims",
            f"- Long-context stress scenario: prompt length reduced from {metrics['stress_ablation']['no_context_reduction']['prompt_chars']} to {metrics['stress_ablation']['full']['prompt_chars']}.",
            f"- Large-scale memory experiment: repeated reads reduced from {memory_large['variants']['memory_off']['repeated_reads']} to {memory_large['variants']['memory_on']['repeated_reads']}.",
            f"- Platform facts: {benchmark['task_count']} benchmark tasks, {metrics['facts']['tool_count']} tool types, {metrics['facts']['run_artifact_count']} run artifacts.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_json_artifact(path: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    """建好父目录、以缩进加排序键写出 JSON（结尾带换行），并原样返回 payload。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return payload


def write_benchmark_core_report(
    report_path: str | Path = DEFAULT_CORE_REPORT_PATH,
    harness_artifact_path: str | Path = DEFAULT_HARNESS_REGRESSION_V2_PATH,
    context_artifact_path: str | Path = DEFAULT_CONTEXT_ABLATION_V2_PATH,
    memory_artifact_path: str | Path = DEFAULT_MEMORY_ABLATION_V2_PATH,
    recovery_artifact_path: str | Path = DEFAULT_RECOVERY_ABLATION_V2_PATH,
) -> str:
    """读四份 v2 工件，写出并返回核心 benchmark 报告的 markdown。

    五个参数都是路径，默认值指向仓库里的 ``artifacts/`` 与 ``docs/metrics/``；报告父目录不存在时创建，
    同一 ``report_path`` 重复调用直接覆盖，返回的就是刚落盘的那份文本。四份工件必须已经存在，缺任何
    一份都让异常抛出——报告里每一条数字都要能追溯到一次真实运行。

    口径与精度：``pass_rate`` / ``within_budget_rate`` / ``verifier_pass_rate`` / 各类压缩率与
    ``correct_rate``、``memory_hit_rate`` 和恢复四个比率都用 ``:.2%``，``avg_full_prompt_chars``、
    ``avg_raw_prompt_chars`` 与 ``avg_tool_steps`` 用 ``:.2f``，``repeated_reads`` 与任务数是整数原样
    打印。恢复段落只取 ``variants.resume_enabled.summary``，因为「关掉恢复后必然失败」不是要展示的结论。

    小节标题（``## Harness Regression`` 等）与末尾三段中文说明都被 tests 断言，属于公开口径；这份报告
    刻意只覆盖四层实验，不引入 provider 或 run aggregation 的结论，避免跨口径混写。
    """
    harness = json.loads(Path(harness_artifact_path).read_text(encoding="utf-8"))
    context = json.loads(Path(context_artifact_path).read_text(encoding="utf-8"))
    memory = json.loads(Path(memory_artifact_path).read_text(encoding="utf-8"))
    recovery = json.loads(Path(recovery_artifact_path).read_text(encoding="utf-8"))

    enabled_recovery = recovery["variants"]["resume_enabled"]["summary"]
    lines = [
        "# Pico Benchmark Core Report",
        "",
        "这轮 benchmark 只收缩到 Harness regression、context ablation、working memory ablation 和 recovery ablation 四层，不把 provider、run aggregation 或 durable memory 的别的结论揉进来。",
        "",
        "## Harness Regression",
        f"- 固定 regression 任务数：{harness['summary']['total_tasks']}",
        f"- pass_rate：{harness['summary']['pass_rate']:.2%}",
        f"- within_budget_rate：{harness['summary']['within_budget_rate']:.2%}",
        f"- verifier_pass_rate：{harness['summary']['verifier_pass_rate']:.2%}",
        "",
        "## Context Ablation",
        f"- 配置数：{context['config_count']}",
        f"- avg_full_prompt_chars：{context['summary']['avg_full_prompt_chars']:.2f}",
        f"- avg_raw_prompt_chars：{context['summary']['avg_raw_prompt_chars']:.2f}",
        f"- avg_prompt_compression_ratio：{context['summary']['avg_prompt_compression_ratio']:.2%}",
        f"- max_prompt_compression_ratio：{context['summary']['max_prompt_compression_ratio']:.2%}",
        f"- current_request_preserved_rate：{context['summary']['current_request_preserved_rate']:.2%}",
        "",
        "## Working Memory Ablation",
        f"- memory_on repeated_reads：{memory['variants']['memory_on']['repeated_reads']}",
        f"- memory_off repeated_reads：{memory['variants']['memory_off']['repeated_reads']}",
        f"- memory_on avg_tool_steps：{memory['variants']['memory_on']['avg_tool_steps']:.2f}",
        f"- memory_on correct_rate：{memory['variants']['memory_on']['correct_rate']:.2%}",
        f"- memory_hit_rate：{memory['variants']['memory_on']['memory_hit_rate']:.2%}",
        "",
        "## Recovery / Resume Ablation",
        f"- resume_success_rate：{enabled_recovery['resume_success_rate']:.2%}",
        f"- stale_reanchor_rate：{enabled_recovery['stale_reanchor_rate']:.2%}",
        f"- workspace_drift_detection_rate：{enabled_recovery['workspace_drift_detection_rate']:.2%}",
        f"- resume_false_accept_rate：{enabled_recovery['resume_false_accept_rate']:.2%}",
        "",
        "## 可以安全写进简历的指标",
        "- avg_full_prompt_chars",
        "- avg_raw_prompt_chars",
        "- avg_prompt_compression_ratio",
        "- max_prompt_compression_ratio",
        "- repeated_reads",
        "- avg_tool_steps",
        "- correct_rate",
        "- resume_success_rate",
        "- workspace_drift_detection_rate",
        "- resume_false_accept_rate",
        "",
        "## 只适合放文档/面试展开的指标",
        "- current_request_preserved_rate",
        "- memory_hit_rate",
        "- stale_reanchor_rate",
        "- failure_category_counts",
        "",
        "## 口径边界",
        "- Harness regression 只证明 runtime 合同稳定，不证明 provider 上限。",
        "- Context、memory、recovery 这三层只证明模块收益，不和 provider benchmark 混写。",
    ]
    report_text = "\n".join(lines) + "\n"
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")
    return report_text

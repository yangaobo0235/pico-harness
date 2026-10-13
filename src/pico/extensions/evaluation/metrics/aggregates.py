"""从运行工件重建指标：这一层只读磁盘上已经存在的事实，不驱动 agent。

`aggregate_benchmark_artifact` 把一次 fixed benchmark 的 JSON 工件摊平成任务数、通过率、失败分类与
平均步数；`aggregate_run_artifacts` 遍历 ``.pico/runs/<run_id>/`` 下的 ``report.json`` 与
``trace.jsonl``，聚合工具状态分布、Prompt 缓存命中与各类耗时。`METRICS_SCHEMA_VERSION` 与几个
``DEFAULT_*`` 路径常量规定这些工件的写入口径，`_safe_mean`、`_safe_ratio`、`_parse_iso8601` 是这一层
共用的算法原语：空列表的均值是 ``0.0``，分母为 0 的比例是 ``0.0``，解析不了的时间戳是 ``None``。

边界：这里不发起任何一次请求，也不判断指标好不好——把数字讲成人话属于 `reporting`，产生记录属于
runtime 与 evaluation engine。字段缺失一律按「那次运行没发生这件事」处理，不补一个看起来合理的默认
值，否则聚合结果会把「没有记录」和「记录就是 0」压成同一个数字，事后无法区分。
"""

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from pico.config.paths import REPORT_FILE_NAME, TRACE_FILE_NAME

#: 指标工件的字段口径版本；写入方与读取方共用同一个数字，字段语义变化时递增。
METRICS_SCHEMA_VERSION = 2

#: 默认工件落点，相对当前工作目录，与 `scripts/` 里的实验入口保持一致。
DEFAULT_HARNESS_REGRESSION_V2_PATH = Path("artifacts/harness-regression-v2.json")
DEFAULT_CONTEXT_ABLATION_V2_PATH = Path("artifacts/context-ablation-v2.json")
DEFAULT_MEMORY_ABLATION_V2_PATH = Path("artifacts/memory-ablation-v2.json")
DEFAULT_RECOVERY_ABLATION_V2_PATH = Path("artifacts/recovery-ablation-v2.json")
DEFAULT_CORE_REPORT_PATH = Path("docs/metrics/pico-benchmark-core-report.md")


def _safe_mean(values: Iterable[float]) -> float:
    """求平均，空输入返回 ``0.0`` 而不是抛 ``ZeroDivisionError``。"""
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _safe_ratio(numerator: float, denominator: float) -> float:
    """求比例，分母为 0（含 ``0.0``）时返回 ``0.0``，表示「没有样本，因此没有比率」。"""
    if not denominator:
        return 0.0
    return numerator / denominator


def _parse_iso8601(value: object) -> datetime | None:
    """把工件里的时间戳解析成 `datetime`，空值或格式不符时返回 ``None``。"""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        # 工件可能来自旧版本或手工编辑，时间戳坏掉时让调用方按「缺失」继续，而不是整轮聚合失败。
        return None


def aggregate_benchmark_artifact(path: str | Path) -> dict[str, Any]:
    """读取一份 benchmark 工件，返回可直接对比的计数字段与按类别分布。

    ``path`` 是 `run_fixed_benchmark` 写出的 JSON 路径，可以是字符串或 `Path`。返回字典含
    ``task_count``、``passed``、``failed``、``pass_rate``、``within_budget``、``verifier_passes``、
    ``failure_category_counts``、``avg_tool_steps``、``avg_attempts``、``category_counts`` 与原始
    ``rows``；``rows`` 原样带出，供报告层再按需要展开。

    口径细节：``task_count`` 优先取 ``summary.total_tasks``，缺失时才回退到「行数，行也为空就是 0」；
    ``avg_tool_steps`` 与 ``avg_attempts`` 是对 ``rows`` 求均值（空 ``rows`` 得 ``0.0``），与
    ``summary`` 里的通过数各算各的，不做交叉校验。``category_counts`` 只统计非空的 ``category``。

    这里不重新判定任务是否通过，也不打开工件里引用的 fixture：判定属于 evaluation engine，重跑属于
    实验层，本函数只对已经落盘的结论做一次摊平，因此工件缺失或 JSON 损坏时让异常原样抛出。
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = list(payload.get("rows", []))
    summary = dict(payload.get("summary", {}))
    task_count = int(summary.get("total_tasks", len(rows) or 0))
    tool_steps = [int(row.get("tool_steps", 0)) for row in rows]
    attempts = [int(row.get("attempts", 0)) for row in rows]
    categories: dict[str, int] = {}
    for row in rows:
        category = str(row.get("category", "")).strip()
        if not category:
            continue
        categories[category] = categories.get(category, 0) + 1
    return {
        "task_count": task_count,
        "passed": int(summary.get("passed", 0)),
        "failed": int(summary.get("failed", 0)),
        "pass_rate": float(summary.get("pass_rate", 0.0)),
        "within_budget": int(summary.get("within_budget", 0)),
        "verifier_passes": int(summary.get("verifier_passes", 0)),
        "failure_category_counts": dict(summary.get("failure_category_counts", {})),
        "avg_tool_steps": _safe_mean(tool_steps),
        "avg_attempts": _safe_mean(attempts),
        "category_counts": categories,
        "rows": rows,
    }


def _infer_run_duration_ms(events: list[dict[str, Any]]) -> float:
    """从一次运行的事件里推出总耗时，优先用 ``run_finished`` 自带的 ``run_duration_ms``。"""
    finished = next((event for event in reversed(events) if event.get("event") == "run_finished"), None)
    if finished and finished.get("run_duration_ms") is not None:
        return float(finished["run_duration_ms"])
    started = next((event for event in events if event.get("event") == "run_started"), None)
    if not started or not finished:
        return 0.0
    start_dt = _parse_iso8601(started.get("created_at"))
    end_dt = _parse_iso8601(finished.get("created_at"))
    if start_dt is None or end_dt is None:
        return 0.0
    return max(0.0, (end_dt - start_dt).total_seconds() * 1000.0)


def aggregate_run_artifacts(runs_root: str | Path) -> dict[str, Any]:
    """遍历 ``.pico/runs`` 下的运行目录，把 report 与 trace 聚合成一份跨运行汇总。

    ``runs_root`` 是运行工件根目录；子目录按名称排序后处理，因此同一份磁盘两次聚合得到同序结果。
    返回字段分三组：计数与均值（``run_count``、``avg_tool_steps``、``avg_attempts``、
    ``avg_prompt_chars``）、缓存（``cache_hit_rate``、``cached_token_ratio``、``avg_cached_tokens``、
    ``prefix_reuse_rate``）、分布与耗时（``tool_status_counts``、``tool_name_counts``、
    ``security_event_counts``、``stop_reason_counts``、``avg_run_duration_ms``、``avg_tool_duration_ms``、
    ``avg_prompt_build_duration_ms``）。

    口径细节：``run_count`` 在有 ``report.json`` 时按报告条数计，一份报告都没有才退回目录数，避免
    「只有空目录」被算成成功运行；``prefix_reuse_rate`` 只统计显式带 ``prefix_changed`` 的记录，老工件
    里缺这个字段的运行既不算复用也不算未复用；``cached_token_ratio`` 是缓存 token 总和比输入 token
    总和，不是逐条比例的平均。目录为空、缺 ``trace.jsonl`` 或某条事件缺 ``duration_ms`` 都按「没有样本」
    处理，均值得到 ``0.0``。

    这里不去重同一 ``run_id``、不解析 trace 的语义，也不跨 ``runs_root`` 递归：一次运行一个目录是
    runtime 的既定布局，重跑覆盖与筛选属于调用方的实验设计。
    """
    root = Path(runs_root)
    run_dirs = sorted(path for path in root.glob("*") if path.is_dir())
    reports: list[dict[str, Any]] = []
    tool_status_counts: dict[str, int] = {}
    tool_name_counts: dict[str, int] = {}
    security_event_counts: dict[str, int] = {}
    run_durations: list[float] = []
    tool_durations: list[float] = []
    prompt_durations: list[float] = []
    stop_reasons: dict[str, int] = {}

    for run_dir in run_dirs:
        report_path = run_dir / REPORT_FILE_NAME
        trace_path = run_dir / TRACE_FILE_NAME
        if report_path.exists():
            reports.append(json.loads(report_path.read_text(encoding="utf-8")))
        events: list[dict[str, Any]] = []
        if trace_path.exists():
            lines = trace_path.read_text(encoding="utf-8").splitlines()
            events = [json.loads(line) for line in lines if line.strip()]
        run_durations.append(_infer_run_duration_ms(events))
        for event in events:
            if event.get("event") == "prompt_built" and event.get("duration_ms") is not None:
                prompt_durations.append(float(event["duration_ms"]))
            if event.get("event") != "tool_executed":
                continue
            tool_name = str(event.get("name", "")).strip()
            if tool_name:
                tool_name_counts[tool_name] = tool_name_counts.get(tool_name, 0) + 1
            tool_status = str(event.get("tool_status", "")).strip()
            if tool_status:
                tool_status_counts[tool_status] = tool_status_counts.get(tool_status, 0) + 1
            security_event = str(event.get("security_event_type", "")).strip()
            if security_event:
                security_event_counts[security_event] = security_event_counts.get(security_event, 0) + 1
            if event.get("duration_ms") is not None:
                tool_durations.append(float(event["duration_ms"]))

    tool_steps = [int(report.get("tool_steps", 0)) for report in reports]
    attempts = [int(report.get("attempts", 0)) for report in reports]
    prompt_chars = [int((report.get("prompt_metadata") or {}).get("prompt_chars", 0)) for report in reports]
    cached_tokens = [int((report.get("prompt_metadata") or {}).get("cached_tokens", 0) or 0) for report in reports]
    cache_hits = [bool((report.get("prompt_metadata") or {}).get("cache_hit")) for report in reports]
    input_tokens = [int((report.get("prompt_metadata") or {}).get("input_tokens", 0) or 0) for report in reports]
    prefix_reused = [
        not bool((report.get("prompt_metadata") or {}).get("prefix_changed"))
        for report in reports
        if "prefix_changed" in (report.get("prompt_metadata") or {})
    ]
    for report in reports:
        stop_reason = str(report.get("stop_reason", "")).strip()
        if stop_reason:
            stop_reasons[stop_reason] = stop_reasons.get(stop_reason, 0) + 1

    return {
        "run_count": len(reports) if reports else len(run_dirs),
        "avg_tool_steps": _safe_mean(tool_steps),
        "avg_attempts": _safe_mean(attempts),
        "avg_prompt_chars": _safe_mean(prompt_chars),
        "cache_hit_rate": _safe_ratio(sum(1 for hit in cache_hits if hit), len(cache_hits)),
        "cached_token_ratio": _safe_ratio(sum(cached_tokens), sum(input_tokens)),
        "avg_cached_tokens": _safe_mean(cached_tokens),
        "prefix_reuse_rate": _safe_ratio(sum(1 for reused in prefix_reused if reused), len(prefix_reused)),
        "tool_status_counts": tool_status_counts,
        "tool_name_counts": tool_name_counts,
        "security_event_counts": security_event_counts,
        "stop_reason_counts": stop_reasons,
        "avg_run_duration_ms": _safe_mean(run_durations),
        "avg_tool_duration_ms": _safe_mean(tool_durations),
        "avg_prompt_build_duration_ms": _safe_mean(prompt_durations),
    }

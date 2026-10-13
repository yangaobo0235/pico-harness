"""基准定义的读入、字段校验与结果汇总。

`load_benchmark` 从磁盘读一份基准 JSON，`validate_benchmark` 决定它是否可执行并把字段规范化成
运行时需要的形状（字符串裁剪、`step_budget` 转 `int`、`allowed_tools` 逐个查工具名录），
`summarize_rows` 把逐任务结果行压成一份可写入工件的统计。判定的口径全部落在这里，
`engine.py` 只负责产生行、不再解释行。

这里不装配 Agent、不复制 fixture、也不写工件：需要动文件与跑循环的是 `pico.extensions.evaluation.engine`。
有意只做"能否执行"级别的最小校验，不做"是否合理"级别的建议——例如不检查 prompt 是否与脚本
输出匹配、不比较任务数量下限：基准的作者就是仓库的维护者，多余的启发式只会让一次刻意的实验
在加载阶段被拒之门外。
"""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pico.capabilities.tools.registry import legal_tool_names
from pico.extensions.evaluation.config import (
    BENCHMARK_SCHEMA_VERSION,
    DEFAULT_BENCHMARK_PATH,
    REQUIRED_BENCHMARK_KEYS,
    REQUIRED_TASK_KEYS,
)


def validate_benchmark(data: Any, repo_root: str | Path | None = None) -> dict[str, Any]:
    """校验并规范化一份基准定义，返回可直接交给评测器的新字典。

    ``data`` 应当是从 JSON 解出的映射，``repo_root`` 是解析 `fixture_repo` 相对路径的基准目录，
    省略时取当前工作目录。返回的字典带 `schema_version`（恒为 `BENCHMARK_SCHEMA_VERSION`）与
    `tasks`（规范化后的任务列表），任务里其余字段（例如 `setup`、`description`）原样保留。

    按固定顺序失败，报的第一条就是让这份基准不可执行的原因，全部抛 ``ValueError``：顶层不是映射
    → ``benchmark must be a mapping``；缺 `REQUIRED_BENCHMARK_KEYS` 中的键 → 列出缺失键名；
    `schema_version` 转 `int` 后不等于当前版本 → ``unsupported benchmark schema_version``；
    `tasks` 不是列表或为空列表 → ``benchmark tasks must be a non-empty list``。逐任务依次检查：
    不是映射、缺 `REQUIRED_TASK_KEYS` 的键（消息里的任务标识在 `id` 缺失时退化成索引）、`id`
    裁剪后为空、`id` 与前面重复、`fixture_repo` 指向的目录不存在（空目录也算不存在）、
    `allowed_tools` 不是非空列表、其中某项裁剪后为空或不在 `legal_tool_names()` 里、
    `step_budget` 转 `int` 后小于 1。空任务列表与缺字段是两种不同错误，不会互相掩盖。

    数字与布尔字段用 `int()`/`str()` 强制转换，无法转换时抛的是原生 ``ValueError``/``TypeError``
    而不是这里的消息——把语言层的转换失败伪装成 schema 错误会让调试变难。不校验 fixture 内容、
    也不预跑 `verifier`，因为那会把一次"读配置"变成一次"执行外部命令"。
    """
    if not isinstance(data, dict):
        raise ValueError("benchmark must be a mapping")

    missing = [key for key in REQUIRED_BENCHMARK_KEYS if key not in data]
    if missing:
        raise ValueError(f"benchmark is missing required keys: {', '.join(missing)}")

    if int(data.get("schema_version", 0)) != BENCHMARK_SCHEMA_VERSION:
        raise ValueError("unsupported benchmark schema_version")

    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("benchmark tasks must be a non-empty list")

    repo_root = Path(repo_root or Path.cwd()).resolve()
    seen_ids = set()
    normalized_tasks = []
    for index, task in enumerate(tasks):
        if not isinstance(task, dict):
            raise ValueError(f"benchmark task at index {index} must be a mapping")

        missing_task_keys = [key for key in REQUIRED_TASK_KEYS if key not in task]
        if missing_task_keys:
            raise ValueError(
                f"benchmark task {task.get('id', index)!r} is missing required keys: {', '.join(missing_task_keys)}"
            )

        task_id = str(task["id"]).strip()
        if not task_id:
            raise ValueError(f"benchmark task at index {index} has an empty id")
        if task_id in seen_ids:
            raise ValueError(f"duplicate benchmark task id: {task_id}")
        seen_ids.add(task_id)

        fixture_repo = repo_root / str(task["fixture_repo"])
        if not fixture_repo.is_dir():
            raise ValueError(f"benchmark task {task_id} fixture repo does not exist: {task['fixture_repo']}")

        allowed_tools = task["allowed_tools"]
        if not isinstance(allowed_tools, list) or not allowed_tools:
            raise ValueError(f"benchmark task {task_id} allowed_tools must be a non-empty list")
        valid_tools = legal_tool_names()
        normalized_allowed_tools = []
        for tool in allowed_tools:
            tool_name = str(tool).strip()
            if not tool_name:
                raise ValueError(f"benchmark task {task_id} has an empty allowed_tools entry")
            if tool_name not in valid_tools:
                raise ValueError(f"benchmark task {task_id} has an unknown allowed_tools entry: {tool_name}")
            normalized_allowed_tools.append(tool_name)

        step_budget = int(task["step_budget"])
        if step_budget < 1:
            raise ValueError(f"benchmark task {task_id} step_budget must be positive")

        normalized_task = dict(task)
        normalized_task["id"] = task_id
        normalized_task["prompt"] = str(task["prompt"]).strip()
        normalized_task["fixture_repo"] = str(task["fixture_repo"]).strip()
        normalized_task["allowed_tools"] = normalized_allowed_tools
        normalized_task["step_budget"] = step_budget
        normalized_task["expected_artifact"] = str(task["expected_artifact"]).strip()
        normalized_task["verifier"] = str(task["verifier"]).strip()
        normalized_task["category"] = str(task["category"]).strip()
        normalized_tasks.append(normalized_task)

    normalized = dict(data)
    normalized["schema_version"] = BENCHMARK_SCHEMA_VERSION
    normalized["tasks"] = normalized_tasks
    return normalized


def load_benchmark(path: str | Path = DEFAULT_BENCHMARK_PATH, repo_root: str | Path | None = None) -> dict[str, Any]:
    """读取 ``path`` 指向的基准 JSON 并交给 `validate_benchmark`。

    文件一律按 UTF-8 解码，因此非 UTF-8 写入的基准会抛 ``UnicodeDecodeError`` 而不是被当成
    乱码解析；JSON 语法错误抛 ``json.JSONDecodeError``，文件不存在抛 ``FileNotFoundError``。
    ``repo_root`` 省略时取基准文件的祖父目录（约定基准放在 ``<repo>/benchmarks/`` 下），这也
    意味着把基准挪到别的深度就会让 `fixture_repo` 解析到错误的位置——需要精确控制时用显式
    ``repo_root`` 覆盖。这里不缓存、不合并多份基准，也不按 glob 挑选"最新的"工件。
    """
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if repo_root is None:
        repo_root = path.resolve().parent.parent
    return validate_benchmark(data, repo_root=repo_root)


def summarize_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """把逐任务结果行压成一份统计，字段名与工件里的 `summary` 段一致。

    输入可以是生成器（先一次性 `list()`，因此不会消耗两次或在中途抛错留下半份统计）。判定
    通过的条件是 `passed` 为真**或** `status` 等于 ``"pass"``，两者都不满足即计入 `failed`；
    `failure_category_counts` 只统计未通过的行，缺失或为假的 `failure_category` 归到 ``"unknown"``。
    返回字典依次为：`total_tasks`、`passed`、`failed`、`pass_rate`、`within_budget`、
    `verifier_passes`、`within_budget_rate`、`verifier_pass_rate`、`failure_category_counts`。

    空输入是合法调用：`total_tasks` 为 0，三个比率取 ``0.0`` 而不是除零。比率用未取整的浮点，
    这里不做显著性检验、不算分位数也不合并多次运行——评测器一次只产一份工件，跨运行比较属于
    调用方的实验脚本。
    """
    rows = list(rows)
    passed = sum(1 for row in rows if row.get("passed") or row.get("status") == "pass")
    failed = len(rows) - passed
    failure_category_counts = {}
    for row in rows:
        if row.get("passed") or row.get("status") == "pass":
            continue
        category = str(row.get("failure_category") or "unknown")
        failure_category_counts[category] = failure_category_counts.get(category, 0) + 1

    total_tasks = len(rows)
    within_budget = sum(1 for row in rows if row.get("within_budget"))
    verifier_passes = sum(1 for row in rows if row.get("verifier_passed"))
    return {
        "total_tasks": total_tasks,
        "passed": passed,
        "failed": failed,
        "pass_rate": (passed / total_tasks) if total_tasks else 0.0,
        "within_budget": within_budget,
        "verifier_passes": verifier_passes,
        "within_budget_rate": (within_budget / total_tasks) if total_tasks else 0.0,
        "verifier_pass_rate": (verifier_passes / total_tasks) if total_tasks else 0.0,
        "failure_category_counts": failure_category_counts,
    }

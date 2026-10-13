"""一次运行的最终摘要。

report 关注结果与关键指标，trace 关注过程；复盘时先看 report，再回到 trace 找具体一步。这份
摘要由运行结束时的一次性快照构造，因此它反映“结束时已知的事实”，不会在之后被改写。

这里不判断任务是否成功（停止原因就是结论），也不重新计算指标——评测与实验脚本从工件里读取
这些字段自行聚合。字段集合一旦发布就保持兼容，新增信息以追加字段的方式进入。
"""

from typing import Any

from pico.contracts.turns import TaskState


def build_report(
    task_state: TaskState,
    *,
    prompt_metadata: dict[str, Any] | None = None,
    durable_promotions: list[Any] | None = None,
    durable_rejections: list[Any] | None = None,
    durable_superseded: list[Any] | None = None,
    redacted_env: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把结束状态与解释性上下文合成一份报告字典。

    ``prompt_metadata`` 来自最后一次 Prompt 组装，包含各段长度、收缩记录与缓存键，是解释
    “模型当时看到什么”的唯一来源。三个 durable 列表记录本轮沉淀进长期记忆的内容与被拒绝的
    原因，``redacted_env`` 说明有多少环境变量被识别为敏感，用于解释工件里出现的占位符。

    所有可选参数都以拷贝写入，调用方之后再修改列表不会影响已经生成的报告。
    """
    return {
        "run_id": task_state.run_id,
        "task_id": task_state.task_id,
        "status": task_state.status,
        "stop_reason": task_state.stop_reason,
        "final_answer": task_state.final_answer,
        "tool_steps": task_state.tool_steps,
        "attempts": task_state.attempts,
        "checkpoint_id": task_state.checkpoint_id,
        "resume_status": task_state.resume_status,
        "task_state": task_state.to_dict(),
        "prompt_metadata": dict(prompt_metadata or {}),
        "durable_promotions": list(durable_promotions or []),
        "durable_rejections": list(durable_rejections or []),
        "durable_superseded": list(durable_superseded or []),
        "redacted_env": dict(redacted_env or {}),
    }

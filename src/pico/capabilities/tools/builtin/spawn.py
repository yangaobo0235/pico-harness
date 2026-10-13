"""把一次调查动作委派给受限的子 Agent。

委派的意义在于“拆开一次上下文”，而不是“多要一份权限”：子 Agent 以只读模式运行、步数更少，
只把结论文本返回给父 Agent。深度耗尽后这个工具连定义都不再暴露给模型，避免递归展开。

真正的子 Agent 构造与运行属于 `pico.runtime.subagents`，本模块只做参数校验和一次转发，
因此工具层不需要知道模型客户端、会话存储等 runtime 细节。
"""

from typing import Any

from pico.capabilities.tools.contracts import ToolContext

DELEGATE_TOOL_NAME = "delegate"

DELEGATE_SPEC = {
    "schema": {"task": "str", "max_steps": "int=3"},
    "risky": False,
    "description": "Ask a bounded read-only child agent to investigate.",
}

DELEGATE_EXAMPLE = '<tool>{"name":"delegate","args":{"task":"inspect README.md","max_steps":3}}</tool>'


def validate_delegate(context: ToolContext, args: dict[str, Any]) -> None:
    """确认任务描述非空，且当前深度仍允许再向下委派一层。

    深度检查在参数校验阶段就做一次，执行阶段还会再检查一次：委派可以由模型连续发起，
    只检查一处会让“校验通过但注册表已不含 delegate”的路径出现。
    """
    task = str(args.get("task", "")).strip()
    if not task:
        raise ValueError("task must not be empty")
    if context.depth >= context.max_depth:
        raise ValueError("delegate depth exceeded")


def delegate(context: ToolContext, args: dict[str, Any]) -> str:
    """调用 runtime 注入的委派实现并返回子 Agent 的结论。

    ``args`` 原样转发，``max_steps`` 等预算的解释属于 runtime，本模块不复制那份默认值，
    以免两处各改一半。``spawn_delegate`` 未注入时抛 `ValueError`，因为那只意味着装配错误，
    不该伪装成“子 Agent 得出了空结论”。
    """
    if context.depth >= context.max_depth:
        raise ValueError("delegate depth exceeded")
    task = str(args.get("task", "")).strip()
    if not task:
        raise ValueError("task must not be empty")
    if context.spawn_delegate is None:
        raise ValueError("delegate is not wired in this runtime")
    return context.spawn_delegate(args)

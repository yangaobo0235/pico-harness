"""Tool 能力层：定义、注册、执行一次模型可以申请的动作。

子模块按职责分开：`contracts` 给出跨层词汇，`registry` 装配本次运行可见的工具目录，
`builtin` 放内置实现，`executor` 执行护栏链，`interaction` 处理需要用户参与的确认与提问。

工具层不决定“任务是否完成”，也不直接把结果交给用户：结果文本回到 Agent 控制循环，
持久化与交付分别属于 `pico.observability` 和 `pico.interfaces`。
"""

from pico.capabilities.tools.contracts import ToolContext, ToolResult
from pico.capabilities.tools.executor import ToolExecutor
from pico.capabilities.tools.registry import build_tool_registry, legal_tool_names

__all__ = [
    "ToolContext",
    "ToolExecutor",
    "ToolResult",
    "build_tool_registry",
    "legal_tool_names",
]

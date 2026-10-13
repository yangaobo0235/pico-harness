"""子 Agent 职责组。

只有一件事：按父 Agent 的授权范围创建一个更受限的运行实例，并把结论交回。工具目录、记忆与
工件都属于子实例自己的一次运行。

跨层递归的深度上限是配置事实（`pico.config.models.runtime`），能力收窄在这里实现；是否值得
委派由模型决定，这里不做任务价值判断。
"""

from pico.runtime.subagents.manager import spawn

__all__ = ["spawn"]

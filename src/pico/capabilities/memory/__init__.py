"""记忆能力层：当前任务的工作集、跨轮笔记与跨会话主题。

子模块按依赖方向分开：`contracts` 给出状态骨架、条目上限与主题名称这些跨层词汇，`state` 只做
字典层面的规范化、写入与召回，`workspace_paths` 负责路径命名与内容指纹，`durable` 把值得长留的
事实落成 markdown 主题文件，`service` 用 `LayeredMemory` 把状态字典绑到一个 Workspace 上。

本包只导出两个稳定入口：`LayeredMemory` 供 runtime 持有，`default_memory_state` 供构造空状态。
其余符号是包内细节，需要更窄能力时按子模块路径导入，不要依赖本入口的再导出——记忆层不读取
会话历史，不决定哪些事实值得晋升，也不组装 prompt：事件流属于 `pico.runtime.session`，晋升时机
属于控制循环，文本排版属于上下文组装；它也不会导入 `pico.runtime`，否则状态层与执行层互相成环。
"""

from pico.capabilities.memory.contracts import default_memory_state
from pico.capabilities.memory.service import LayeredMemory

__all__ = [
    "LayeredMemory",
    "default_memory_state",
]

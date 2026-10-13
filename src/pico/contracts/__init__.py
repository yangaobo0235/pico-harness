"""跨层共享的约定类型：一次请求的状态、历史记录形状与运行事件。

这里只放各层都必须按同一含义解释的词汇，不放只有某个模块内部才需要的辅助结构，也不引入
入口、装配层或 Provider SDK。协议变化会同时影响持久化工件，因此字段默认值一旦发布就保持
兼容，旧工件在字段增加后仍应可读。
"""

from pico.contracts.messages import ROLE_ASSISTANT, ROLE_TOOL, ROLE_USER
from pico.contracts.turns import STATUS_COMPLETED, STATUS_RUNNING, TaskState

__all__ = [
    "ROLE_ASSISTANT",
    "ROLE_TOOL",
    "ROLE_USER",
    "STATUS_COMPLETED",
    "STATUS_RUNNING",
    "TaskState",
    "TraceEvent",
]

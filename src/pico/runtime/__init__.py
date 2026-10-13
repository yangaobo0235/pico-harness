"""运行时职责组：把一次请求推进到结果。

`agent` 迭代模型与工具，`context` 决定模型每轮看到什么，`sessions` 保存可恢复的对话，
`subagents` 创建更受限的子实例，`workspace` 提供仓库事实与差异。五者只依赖能力层与约定层，
不导入任何入口或装配代码——CLI、REPL 和评测脚本复用同一套执行机制。

生命周期由调用方掌握：运行时不在构造时启动后台任务，也不在请求结束后自动清理会话文件。
"""

from pico.runtime.agent import AgentLoop, Pico
from pico.runtime.context import ContextAssembler
from pico.runtime.sessions import SessionStore

__all__ = [
    "AgentLoop",
    "ContextAssembler",
    "Pico",
    "SessionStore",
]

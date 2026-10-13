"""mini-pico 是 pico 的教学尺寸实现：把一轮请求从头跑到尾的最小 agent harness。

单层包、十来个模块、零第三方依赖。`Pico` 组织一次 `ask()`，`AgentLoop` 推进“组装 Prompt → 请求
模型 → 解析输出 → 执行工具 → 回写历史”这条循环，`FakeModelClient` 让整条控制流不需要 API key
也不需要联网就能被观察，`RunStore` 把状态、Trace 与报告写到 ``.mini-pico/runs/<run_id>/``，读者
可以对着落盘文件复盘每一轮模型到底看到了什么。这里导出的五个名字就是用这个包时需要的全部对象。

边界：这里不追求生产可用。会话恢复、上下文预算、记忆、审批交互、工件脱敏与多 Provider 适配都被
有意省略，它们属于主项目的 ``src/pico/`` 分层结构（interfaces、bootstrap、runtime、capabilities、
integrations、security、observability、contracts、shared）。本包刻意保持单层，因为教学实现的目标
是“一屏之内读完”；模块与生产各层的对应关系写在同目录的 README 里。
"""

from mini_pico.providers import FakeModelClient
from mini_pico.runtime import Pico
from mini_pico.state import RunStore, TaskState
from mini_pico.workspace import Workspace

__all__ = [
    "FakeModelClient",
    "Pico",
    "RunStore",
    "TaskState",
    "Workspace",
]

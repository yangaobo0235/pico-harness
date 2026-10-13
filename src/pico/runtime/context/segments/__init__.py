"""Prompt 分段渲染器。

每个段落把自己的文本变成 `SectionRender`，并附带该段特有的观察项；组装器
（`pico.runtime.context.assembler`）只按 `pico.runtime.context.budget` 给的预算调用它们，
不再关心段内细节。新增段落应该新建子模块并在这里登记，而不是往组装器里加分支。

段落顺序、标题文本和裁剪方式是稳定契约的一部分：它们共同决定 prompt 缓存键能否命中。
"""

from pico.runtime.context.segments.history import render_history
from pico.runtime.context.segments.instructions import render_instructions
from pico.runtime.context.segments.memory import render_memory, render_relevant_memory
from pico.runtime.context.segments.render import SectionRender

__all__ = [
    "SectionRender",
    "render_history",
    "render_instructions",
    "render_memory",
    "render_relevant_memory",
]

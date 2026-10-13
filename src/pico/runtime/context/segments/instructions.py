"""稳定指令段的渲染。

指令段包含角色规则、工具清单、示例调用与 Workspace 快照，是一轮 Prompt 里最稳定的部分：
只要工作区事实和工具签名没变，它就逐字相同，因此也是 Provider 侧 prompt 缓存的命中依据。

这里只做尾部裁剪，不做重排或摘要——任何改动都会让缓存的 prefix 哈希失效。缓存键的计算属于
`pico.runtime.context.instructions`，预算属于 `pico.runtime.context.budget`。
"""

from pico.runtime.context.segments.render import SectionRender
from pico.shared.text import tail_clip


def render_instructions(raw: str, budget: int) -> SectionRender:
    """按预算尾部裁剪稳定指令段。

    裁剪发生在尾部意味着“角色规则与工具说明优先保住”，被牺牲的是 Workspace 快照的末尾条目
    和示例调用。这符合排序意图：文本本身在构造时就把不变的东西放在前面。
    """
    return SectionRender(raw=raw, budget=int(budget), rendered=tail_clip(raw, budget))

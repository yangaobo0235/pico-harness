"""上下文职责组：决定每一轮模型实际看到什么。

`instructions` 构造稳定前缀，`segments` 渲染各个段落，`budget` 给出预算与收缩顺序，
`history_trimmer` 把过长的历史降级成摘要，`assembler` 把这些合成一份 Prompt 并解释构成。

上下文层不发送请求、不执行工具，也不写入工件；它唯一的输出是「一段文本 + 一份构成说明」。
Provider 侧的 prompt 缓存是否命中由文本决定，本层不假装能观察对端缓存。
"""

from pico.runtime.context.assembler import ContextAssembler
from pico.runtime.context.budget import DEFAULT_TOTAL_BUDGET, SECTION_ORDER
from pico.runtime.context.instructions import PromptPrefix, build_prompt_prefix

__all__ = [
    "DEFAULT_TOTAL_BUDGET",
    "ContextAssembler",
    "PromptPrefix",
    "SECTION_ORDER",
    "build_prompt_prefix",
]

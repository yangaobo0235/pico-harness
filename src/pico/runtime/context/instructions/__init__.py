"""上下文指令段的构造入口。

`instructions` 负责“稳定前缀长什么样”，包括角色规则、工具清单与示例调用。它与 Workspace 快照
一起构成一轮 Prompt 的第一段，也是 prompt 缓存键的来源。

会话历史、工作记忆与本轮请求不在这里出现：它们每轮都变，交给
`pico.runtime.context.assembler` 按预算拼装。
"""

from pico.runtime.context.instructions.builder import PromptPrefix, build_prompt_prefix, tool_signature

__all__ = ["PromptPrefix", "build_prompt_prefix", "tool_signature"]

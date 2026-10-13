"""把一轮请求组装成真正发给模型的 Prompt 文本。

`ContextManager` 是教学版的上下文组装器：每轮都从头重建一段文本，把工具签名、工作区快照、
最近 12 条历史和当前请求按固定顺序拼起来，并附带三个事实（历史条数、工具数量、Prompt 字符数）
进入 Trace。历史靠文本回灌而不是靠模型自带记忆，所以“模型下一轮看到什么”完全由这里决定，
读 Prompt 就能读满整个循环的行为。返回的元数据随后成为 `prompt_built` 事件的载荷。

这里没有预算，也没有分段收缩：稳定指令写死在模板里，快照与 `clip` 自带长度上限，历史只按条数截断。
主项目把这件事拆成 `runtime.context` 的 assembler、budget 与 segments 三层，按段分配预算并按固定
顺序裁剪；教学版保留“段落顺序”和“元数据”这两个概念，砍掉预算机制，因为一次讲清“上下文是拼出来的”
不需要再讲“怎么裁”。协议标记的解析也不在这里，属于 `Pico.parse`。
"""

from typing import TYPE_CHECKING, Any

from mini_pico import tools

if TYPE_CHECKING:
    from mini_pico.runtime import Pico


class ContextManager:
    """按当前运行时的事实渲染一轮 Prompt。

    它持有运行时引用而不是把历史、工作区当参数传进来：这些是“此刻”的事实，每轮都要重新读，
    复制成构造参数就会让教学示例多出一层同步问题。
    """

    def __init__(self, agent: "Pico") -> None:
        self.agent = agent

    def build(self, user_message: str) -> tuple[str, dict[str, Any]]:
        """返回 ``(prompt, metadata)``。

        Prompt 以当前请求结尾，往前依次是历史、工作区快照、工具签名和固定的指令段；顺序不变，
        两次同样的请求才能得到同一段前缀。元数据只描述规模不描述内容，因为它进 Trace 是为了让人
        判断“这一轮是不是被历史撑爆了”。
        """
        history = _render_history(self.agent.history)
        prompt = f"""You are mini-pico, a teaching-sized local coding agent.

Return exactly one of these forms:
<tool>{{"name":"read_file","args":{{"path":"README.md","start":1,"end":40}}}}</tool>
<final>Your final answer</final>

Tools:
{tools.tool_signature()}

{self.agent.workspace.snapshot_text()}

Transcript:
{history}

Current request:
{user_message}
"""
        metadata = {
            "history_items": len(self.agent.history),
            "tool_count": len(tools.TOOL_SPECS),
            "prompt_chars": len(prompt),
        }
        return prompt, metadata


def _render_history(history: list[dict[str, Any]]) -> str:
    """把最近 12 条历史压成文本，工具结果统一渲染成 `Tool result:` 一行。"""
    if not history:
        return "(empty)"
    lines = []
    for item in history[-12:]:
        role = item.get("role", "")
        if role == "tool":
            lines.append(f"Tool result: {item.get('name')} -> {item.get('content')}")
        else:
            lines.append(f"{role}: {item.get('content')}")
    return "\n".join(lines)

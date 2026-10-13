"""构造一轮 Prompt 的稳定前缀，并给出可比较的签名。

`build_prompt_prefix` 把角色规则、工具清单、示例调用和 Workspace 快照拼成一份文本，
`PromptPrefix` 同时携带文本哈希、Workspace 指纹与工具签名。这三项是 runtime 判断“这一段能不能
复用缓存”的全部依据：只要三者不变，本轮就沿用已经构造好的文本。

这里不注入会话历史、记忆或 checkpoint 文本，也不做预算裁剪——那些发生在
`pico.runtime.context.assembler`，属于每轮都要重算的部分。规则文本一旦改动就会让既有缓存键
失效，因此新增规则要谨慎，措辞调整与结构调整等价于一次缓存重建。
"""

import hashlib
import json
import textwrap
from dataclasses import dataclass
from typing import Any

from pico.shared.clock import now

#: 工具协议要求模型二选一返回的标记。
TOOL_TAG = "tool"
FINAL_TAG = "final"

#: 示例调用覆盖两种工具写法与一个终态答案，模型只需要这几种模式就能开工。
RESPONSE_EXAMPLES = (
    '<tool>{"name":"list_files","args":{"path":"."}}</tool>',
    '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":80}}</tool>',
    '<tool name="write_file" path="binary_search.py"><content>def binary_search(nums, target):\n    return -1\n</content></tool>',
    '<tool name="patch_file" path="binary_search.py"><old_text>return -1</old_text><new_text>return mid</new_text></tool>',
    '<tool>{"name":"run_shell","args":{"command":"uv run --with pytest python -m pytest -q","timeout":20}}</tool>',
    "<final>Done.</final>",
)


@dataclass
class PromptPrefix:
    """稳定前缀的文本与其可复用性依据。

    ``hash`` 覆盖整段文本，是 prompt 缓存键；``workspace_fingerprint`` 用来判断仓库事实是否变化，
    ``tool_signature`` 用来判断动作集合是否变化。把三项和文本放在一起返回，runtime 就不需要在
    别处再算一次，也不会出现“文本变了但键没变”的分裂状态。``built_at`` 只用于观察，不参与比较。
    """

    text: str
    hash: str
    workspace_fingerprint: str
    tool_signature: str
    built_at: str


def tool_signature(tools: dict[str, dict[str, Any]]) -> str:
    """返回工具集合的声明指纹。

    只对名称、schema、风险标记和描述取哈希，因此替换实现而不动声明不会改变签名——这正是
    期望语义：模型看到的动作契约没变。排序后序列化，保证注册顺序变化不影响签名。
    """
    payload = []
    for name in sorted(tools):
        tool = tools[name]
        payload.append(
            {
                "name": name,
                "schema": tool["schema"],
                "risky": tool["risky"],
                "description": tool["description"],
            }
        )
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def render_tool_lines(tools: dict[str, dict[str, Any]]) -> str:
    """把工具声明渲染成一行一条的清单。

    每行给出参数签名、是否需要审批以及一句描述。描述来自工具定义本身，这里不加解释，
    以免同一件事在两个地方各写一遍。
    """
    lines = []
    for name, tool in tools.items():
        fields = ", ".join(f"{key}: {value}" for key, value in tool["schema"].items())
        risk = "approval required" if tool["risky"] else "safe"
        lines.append(f"- {name}({fields}) [{risk}] {tool['description']}")
    return "\n".join(lines)


def build_prompt_prefix(workspace: Any, tools: dict[str, dict[str, Any]], built_at: str | None = None) -> PromptPrefix:
    """按仓库快照与工具目录构造稳定前缀。

    文本顺序是刻意的：角色与规则在最前，工具清单与示例居中，Workspace 快照放在尾部。
    前缀段被裁剪时先牺牲的就是快照末尾，这样规则文本可以尽量保持逐字一致。

    ``workspace`` 只需要提供 `text()` 与 `fingerprint()`；类型留在调用方满足，本模块不依赖
    Workspace 的具体实现，避免上下文层反向依赖运行时对象。
    """
    tool_text = render_tool_lines(tools)
    examples = "\n".join(RESPONSE_EXAMPLES)
    # 这段模板的缩进与措辞参与缓存键计算，改动它就等于一次全量缓存失效。
    text = textwrap.dedent(
        f"""\
        You are pico, a small local coding agent working inside a local repository.

        Rules:
        - Use tools instead of guessing about the workspace.
        - Return exactly one <tool>...</tool> or one <final>...</final>.
        - Tool calls must look like:
          <tool>{{"name":"tool_name","args":{{...}}}}</tool>
        - For write_file and patch_file with multi-line text, prefer XML style:
          <tool name="write_file" path="file.py"><content>...</content></tool>
        - Final answers must look like:
          <final>your answer</final>
        - Never invent tool results.
        - Keep answers concise and concrete.
        - If the user asks you to create or update a specific file and the path is clear, use write_file or patch_file instead of repeatedly listing files.
        - Before writing tests for existing code, read the implementation first.
        - When writing tests, match the current implementation unless the user explicitly asked you to change the code.
        - New files should be complete and runnable, including obvious imports.
        - Do not repeat the same tool call with the same arguments if it did not help. Choose a different tool or return a final answer.
        - Required tool arguments must not be empty. Do not call read_file, write_file, patch_file, run_shell, or delegate with args={{}}.

        Tools:
        {tool_text}

        Valid response examples:
        {examples}

        {workspace.text()}
        """
    ).strip()
    return PromptPrefix(
        text=text,
        hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        workspace_fingerprint=workspace.fingerprint(),
        tool_signature=tool_signature(tools),
        built_at=built_at or now(),
    )

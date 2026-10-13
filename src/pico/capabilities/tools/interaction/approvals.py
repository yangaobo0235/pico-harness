"""在终端里向用户确认一次高风险动作。

策略判断（该不该问）属于 `pico.security.authorization.approval`，这里只负责“问”这个动作：
把工具名与参数打印给用户，读一行回答，并把任何异常输入都当成拒绝。

不缓存答案、没有“本会话总是允许”的开关：Pico 的审批是一次动作一次的，一次放行不会外溢到
后续同类调用。需要完全无人值守时应把策略设为 ``auto`` 或 ``never``，而不是在这里加自动同意。
"""

import json
from typing import Any, Callable

#: 接受的自然语言回答，全部按去掉两端空白并转小写后比较。
AFFIRMATIVE_ANSWERS = frozenset({"y", "yes"})

_APPROVAL_PROMPT = "approve {name} {args}? [y/N] "


def confirm_approval(name: str, args: dict[str, Any], *, input_fn: Callable[[str], str] = input) -> bool:
    """向用户询问是否放行一次工具调用。

    ``input_fn`` 可注入，测试因此不需要模拟 stdin；读到 ``EOFError``（管道输入结束、用户按
    Ctrl-D）返回 ``False``，把“没人可以回答”解释为拒绝执行，这是唯一安全的默认值。回答里的
    ``yes`` 与 ``y`` 都算同意，其他任何文本都算拒绝，不做二次追问。
    """
    question = _APPROVAL_PROMPT.format(name=name, args=json.dumps(args, ensure_ascii=True))
    try:
        answer = input_fn(question)
    except EOFError:
        return False
    return str(answer).strip().lower() in AFFIRMATIVE_ANSWERS

"""会话历史的记录形状，以及记录里出现的角色名称。

Pico 把历史保存为可 JSON 序列化的字典而不是模型对象，`Session` 因此不需要自定义编码器就能
落盘。本模块给出这些字典的字段约定与构造函数，让 Agent 迭代、上下文渲染和记忆沉淀读到
同一份形状；它不负责拼装 Prompt，也不判断某条记录是否还应该保留。
"""

from typing import Any

ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
ROLE_TOOL = "tool"

HISTORY_ROLES = (ROLE_USER, ROLE_ASSISTANT, ROLE_TOOL)


def user_message(content: str, created_at: str) -> dict[str, Any]:
    """构造一条用户请求记录。

    用户与助手记录只有 ``role``、``content``、``created_at`` 三个字段；工具记录额外携带
    ``name`` 与 ``args``，因为“读过哪个文件”本身就是后续决策需要的事实。
    """
    return {"role": ROLE_USER, "content": content, "created_at": created_at}


def assistant_message(content: str, created_at: str) -> dict[str, Any]:
    """构造一条助手输出记录。

    ``content`` 既可能是模型给出的最终答案，也可能是 runtime 回灌的重试提示，两者在历史里
    不做区分；区分依据留在 Trace 事件里。
    """
    return {"role": ROLE_ASSISTANT, "content": content, "created_at": created_at}


def tool_message(name: str, args: dict[str, Any], content: str, created_at: str) -> dict[str, Any]:
    """构造一条工具结果记录，参数按调用原样保留。

    ``args`` 会被上下文渲染直接读取用于折叠重复读取，因此不能在这里丢弃字段；``content``
    是裁剪后的结果文本，完整输出只在当次模型请求中出现在历史尾部。
    """
    return {
        "role": ROLE_TOOL,
        "name": name,
        "args": dict(args or {}),
        "content": content,
        "created_at": created_at,
    }

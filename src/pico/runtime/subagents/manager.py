"""子 Agent 的创建与约束。

委派的目标是“拆开一次调查”，不是“多要一份权限”：子 Agent 复用同一个模型客户端与工作区，
但以只读模式运行、审批固定为 ``never``、步数预算更小，最后只把结论文本交回父 Agent。它拥有
自己的会话与记忆状态，因此父会话的历史不会被子步骤污染。

深度上限在两个地方生效：工具目录里（深度耗尽就不再暴露 ``delegate``）与这里（执行时再检查
一次）。这里不判断任务是否值得委派——那是模型的决策。
"""

from typing import TYPE_CHECKING, Any

from pico.config.models.runtime import APPROVAL_NEVER, DELEGATE_DEFAULT_MAX_STEPS
from pico.runtime.context.history_trimmer import summary_text
from pico.shared.text import clip

if TYPE_CHECKING:
    from pico.runtime.agent.agent import Pico

#: 随委派带走的上文长度，只够子 Agent 知道“父任务在做什么”。
DELEGATE_CONTEXT_CLIP = 300
#: 结果前缀，让父模型区分这是子 Agent 的结论而不是自己的输出。
DELEGATE_RESULT_PREFIX = "delegate_result:"


def spawn(parent: "Pico", args: dict[str, Any]) -> str:
    """运行一个受限的子 Agent 并返回它的结论。

    ``max_steps`` 缺省取 `DELEGATE_DEFAULT_MAX_STEPS`，父 Agent 的 ``max_new_tokens`` 与环境
    白名单原样继承，保证同一个模型客户端在不同层级上的行为可比。子 Agent 的上文由
    `summary_text` 压缩后写进它自己的记忆，因此它看得见目标但看不见父会话的完整历史。

    深度由调用方保证；这里不自检，因为工具注册表与校验层已经各自挡过一次，重复判断只会让
    “为什么这次没开子 Agent”更难解释。
    """
    from pico.runtime.agent.agent import Pico

    task = str(args.get("task", "")).strip()
    child = Pico(
        model_client=parent.model_client,
        workspace=parent.workspace,
        session_store=parent.session_store,
        run_store=parent.run_store,
        approval_policy=APPROVAL_NEVER,
        max_steps=int(args.get("max_steps", DELEGATE_DEFAULT_MAX_STEPS)),
        max_new_tokens=parent.max_new_tokens,
        depth=parent.depth + 1,
        max_depth=parent.max_depth,
        read_only=True,
        secret_env_names=parent.secret_env_names,
        shell_env_allowlist=parent.shell_env_allowlist,
    )
    child.session["memory"]["task"] = task
    child.session["memory"]["notes"] = [clip(summary_text(parent.session["history"]), DELEGATE_CONTEXT_CLIP)]
    return f"{DELEGATE_RESULT_PREFIX}\n" + child.ask(task)

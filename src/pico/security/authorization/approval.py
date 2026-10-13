"""把审批策略翻译成三态决定。

Pico 支持 `ask`（默认）、`auto`、`never` 三种策略，只读子 Agent 会无条件收紧成拒绝写入。
策略判断与实际询问用户的动作分开：本模块回答“该不该放行”，交互提示属于
`pico.capabilities.tools.interaction.approvals`。这样同一段策略既能用于 REPL，也能用于无人值守
的评测与子 Agent，而不会在测试里真的去读 stdin。

审批只覆盖被标记为 ``risky`` 的工具；只读工具不进入这里。它也不判断“命令内容是否安全”，
命令白名单在 Pico 里刻意不存在——那会让模型无法执行任何用户仓库真正需要的构建脚本。
"""

from pico.config.models.runtime import APPROVAL_AUTO, APPROVAL_NEVER

APPROVAL_APPROVED = "approved"
APPROVAL_DENIED = "denied"
APPROVAL_ASK_USER = "ask_user"


def evaluate_approval(approval_policy: str, *, read_only: bool) -> str:
    """返回 `APPROVAL_APPROVED`、`APPROVAL_DENIED` 或 `APPROVAL_ASK_USER`。

    ``read_only`` 优先于策略：委派出的子 Agent 即使带着 ``auto`` 也只能调查，不能改文件。
    未知策略按最保守的“拒绝”处理，因为策略值可能来自配置文件，拼错的 ``atuo`` 不应该
    换来一个放权的执行环境。
    """
    if read_only:
        return APPROVAL_DENIED
    if approval_policy == APPROVAL_AUTO:
        return APPROVAL_APPROVED
    if approval_policy == APPROVAL_NEVER:
        return APPROVAL_DENIED
    return APPROVAL_ASK_USER

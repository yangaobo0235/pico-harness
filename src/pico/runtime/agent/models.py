"""Agent execution outcomes and provider failure categories."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TurnOutcome:
    """记录一次 ``_run_agent_loop`` 除文本回复之外的终态与恢复证据。

    Turn 是 Agent 围绕一条请求执行的一轮完整工作，不等同于模型生成的一段文字。调用方
    除了需要最终文本，还必须知道循环为何停止、是否留下部分编辑以及下轮应从哪里核对。
    这个值对象把这些控制面事实从回复正文中分离出来，避免调用方根据自然语言猜测状态。

    ``status`` 明确区分三种终态：``"completed"`` 表示正常完成，``"interrupted"`` 表示
    达到最大迭代预算后中断，``"error"`` 表示 LLM 调用出错。该区分落实 Bug2 / decision B：
    调用方绝不能把 "ran out of budget" 当成 "done"。``error_category`` 在错误终态下携带
    稳定分类，供边界外记录或展示，而不是要求读者解析 Provider 的原始异常文本。

    ``checkpoint_id`` 与 ``edited_files`` 携带本轮 shadow-git 快照标识和已编辑文件清单。
    `_stash_recovery` 只会为可恢复的中断保存它们，下一 Turn 的 `_inject_recovery_block`
    再据此构造恢复提示。它们提供的是“先检查哪些现场”的证据，不保证下一轮一定能自动
    恢复成功，也不会把模型回复本身当作文件状态的事实来源。
    """

    status: str = "completed"  # 可选 "completed" | "interrupted" | "error"
    checkpoint_id: str | None = None
    edited_files: list[str] = field(default_factory=list)
    error_category: str | None = None


class ProviderTurnError(RuntimeError):
    """在 Provider 无法完成 Turn 时，向运行边界传播安全、稳定的终止错误。

    Provider 是 Agent Loop 与具体 LLM 服务之间的适配层。底层服务可能返回包含供应商细节
    的异常，但上层只需要可记录、可比较的错误类别；因此本异常把 ``category`` 保存为字段，
    并把消息规范化为 ``provider_error:{category}``。它表示本轮已经进入错误终态，不是可供
    循环继续消费的普通模型回复；调用方应让 Spine 的失败事件处理这条路径。
    """

    def __init__(self, category: str) -> None:
        self.category = category
        super().__init__(f"provider_error:{category}")

"""执行护栏：模型意图落到外部世界之前的唯一通道。

`ToolExecutor` 按固定顺序做四步——查目录、校验参数、判断审批、执行并裁剪结果。每一条失败分支都
返回 `ToolExecutionResult`，把原因写成 `error:` 前缀的文本，因此一次工具调用总能给模型反馈、
让循环继续推进，而不是抛出 Python 堆栈。元数据（状态、错误码、只读与否、受影响路径）走 Trace 与
报告，不进入模型可见文本，这是 `ToolResult` 形状存在的理由：一条结果只有一个读者群之外的观察者。

这里不定义工具，也不判断动作在业务上是否正确；目录与参数规则属于 `mini_pico.tools`，路径归属
属于 `mini_pico.workspace`。主项目的执行层还多了允许名单、重复调用抑制、工作区快照差异与记忆回写
（`pico.capabilities.tools.executor`），教学版有意只做上面四步：这四步是“护栏”的最小可理解集合，
再加东西就会把读者的注意力从流程本身挪走。
"""

from dataclasses import dataclass
from typing import Any

from mini_pico import tools
from mini_pico.workspace import Workspace, clip


@dataclass(frozen=True)
class ToolExecutionResult:
    """一次工具调用的对外结果。

    ``content`` 一定是模型可读文本，成功是工具输出，失败是带原因的 `error:` 文本；
    ``metadata`` 是给工件与 Trace 看的事实，两者不共享通道，因此报告里能出现的判断不会偷偷
    改变 Prompt。
    """

    content: str
    metadata: dict[str, Any]


class ToolExecutor:
    """带护栏的工具入口，护栏由工作区与审批策略两件事决定。

    ``approval_policy`` 为 ``never`` 时所有 `risky` 工具在执行前就被拒绝，读取与搜索仍然可用，
    这是“只读调查”的最低配置。执行器实例随运行时构造一次并复用，本身不保存历史，
    因此同一份护栏可以被任意多次调用共享。
    """

    def __init__(self, workspace: Workspace, approval_policy: str = "auto") -> None:
        self.workspace = workspace
        self.approval_policy = approval_policy

    def execute(self, name: str, args: dict[str, Any] | None) -> ToolExecutionResult:
        """执行一次工具调用，任何分支都返回结果对象而不抛异常。

        顺序是有讲究的：先确认工具存在，再校验参数，最后才判断审批——把“没这个工具”和
        “参数写错”分在审批之前，模型收到的错误才不会互相掩盖。未知工具与非只读失败的
        ``read_only`` 都记为 ``False``，因为一次被拒的高风险尝试在审计上和一次成功写入同等重要。
        工具内部抛出的异常统一收敛成 `tool_failed`，正文里保留异常文本，让模型下一轮有机会改写参数。
        """
        spec = tools.TOOL_SPECS.get(name)
        if spec is None:
            return ToolExecutionResult(f"error: unknown tool '{name}'", _metadata("rejected", name, read_only=False))
        try:
            tools.validate_tool(self.workspace, name, args)
        except Exception as exc:
            return ToolExecutionResult(
                f"error: invalid arguments for {name}: {exc}",
                _metadata("rejected", name, error_code="invalid_arguments", read_only=not spec.risky),
            )
        if spec.risky and self.approval_policy == "never":
            return ToolExecutionResult(
                f"error: approval denied for {name}",
                _metadata("rejected", name, error_code="approval_denied", read_only=False),
            )
        try:
            content = clip(tools.run_tool(self.workspace, name, args))
            affected_paths = []
            if spec.risky and isinstance(args, dict) and args.get("path"):
                affected_paths.append(str(args["path"]))
            return ToolExecutionResult(
                content,
                _metadata(
                    "ok",
                    name,
                    read_only=not spec.risky,
                    workspace_changed=bool(affected_paths),
                    affected_paths=affected_paths,
                ),
            )
        except Exception as exc:
            return ToolExecutionResult(
                f"error: tool {name} failed: {exc}",
                _metadata("error", name, error_code="tool_failed", read_only=not spec.risky),
            )


def _metadata(
    status: str,
    name: str,
    error_code: str = "",
    read_only: bool = True,
    workspace_changed: bool = False,
    affected_paths: list[str] | None = None,
) -> dict[str, Any]:
    """产出一份固定键集合的工具元数据，缺省值即“只读、成功、没改工作区”。"""
    return {
        "tool_status": status,
        "tool_name": name,
        "tool_error_code": error_code,
        "read_only": bool(read_only),
        "workspace_changed": bool(workspace_changed),
        "affected_paths": list(affected_paths or []),
    }

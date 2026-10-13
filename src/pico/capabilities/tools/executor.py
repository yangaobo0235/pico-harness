"""工具执行层：在真正调用外部动作之前把所有护栏串起来。

`ToolExecutor` 是模型意图落到外部世界的唯一通道：允许名单、参数校验、重复调用、审批、
结果裁剪、Workspace 快照差异与记忆回写都在这一步完成。所有分支都返回 `ToolResult`，
执行失败也以文本形式回灌给模型，因此一次工具调用总能让控制循环继续推进，而不是抛出
Python 堆栈。

这里不定义工具，也不判断某个动作在业务上是否正确；工具目录属于 `registry`，是否放行属于
`pico.security.authorization`。
"""

import re
from typing import TYPE_CHECKING, Any

from pico.capabilities.tools.contracts import (
    RISK_LEVEL_HIGH,
    RISK_LEVEL_LOW,
    SECURITY_EVENT_APPROVAL_DENIED,
    SECURITY_EVENT_PATH_ESCAPE,
    SECURITY_EVENT_READ_ONLY_BLOCK,
    TOOL_ERROR_APPROVAL_DENIED,
    TOOL_ERROR_INVALID_ARGUMENTS,
    TOOL_ERROR_REPEATED_IDENTICAL_CALL,
    TOOL_ERROR_TOOL_FAILED,
    TOOL_ERROR_TOOL_NOT_ALLOWED,
    TOOL_ERROR_TOOL_PARTIAL_SUCCESS,
    TOOL_ERROR_UNKNOWN_TOOL,
    TOOL_STATUS_ERROR,
    TOOL_STATUS_OK,
    TOOL_STATUS_PARTIAL_SUCCESS,
    TOOL_STATUS_REJECTED,
    ToolResult,
)
from pico.config.models.runtime import MAX_TOOL_OUTPUT
from pico.security.authorization.workspace_paths import PathEscapeError
from pico.shared.text import clip

if TYPE_CHECKING:
    from pico.runtime.agent.agent import Pico

_EXIT_CODE_PATTERN = re.compile(r"exit_code:\s*(-?\d+)")


def _metadata(
    tool_status: str,
    tool_error_code: str = "",
    security_event_type: str = "",
    risk_level: str = RISK_LEVEL_LOW,
    read_only: bool = True,
    affected_paths: list[str] | None = None,
    workspace_changed: bool = False,
    workspace_fingerprint: str = "",
    diff_summary: list[str] | None = None,
) -> dict[str, Any]:
    """构造工具结果元数据。

    字段集合固定，`workspace_fingerprint` 只在有值时追加，这样没有执行副作用的调用不会在
    Trace 里留下一个空指纹。`affected_paths` 与 `diff_summary` 来自执行前后的 Workspace 快照
    对比，是“这次调用究竟改了什么”的唯一证据来源。
    """
    result: dict[str, Any] = {
        "tool_status": tool_status,
        "tool_error_code": tool_error_code,
        "security_event_type": security_event_type,
        "risk_level": risk_level,
        "read_only": read_only,
        "affected_paths": list(affected_paths or []),
        "workspace_changed": bool(workspace_changed),
        "diff_summary": list(diff_summary or []),
    }
    if workspace_fingerprint:
        result["workspace_fingerprint"] = workspace_fingerprint
    return result


class ToolExecutor:
    """按固定顺序执行工具调用的护栏链。

    检查顺序就是策略顺序：允许名单 → 工具是否存在 → 参数 → 重复调用 → 审批 → 执行。把
    允许名单放在最前，是因为 ``--allowed-tools`` 表达的是一次运行的能力边界，比“这个参数
    写得对不对”更优先；审批放在执行前最后一步，保证被拒绝的调用不会留下任何副作用。

    执行器持有 runtime 引用而不是复制状态：快照、指纹、记忆回写都需要当前会话与工作区事实，
    把这些塞进构造参数会让每次工具调用都要重新装配。
    """

    def __init__(self, agent: "Pico"):
        self.agent = agent

    def execute(self, name: str, args: dict[str, Any]) -> ToolResult:
        """执行一次工具调用，并把所有可预期的拒绝与失败规范化为文本结果。

        返回的 ``content`` 面向模型，``metadata`` 面向工件；``error:`` 前缀是模型识别失败的约定
        信号，因此各分支错误信息都保持同一形状。被拒绝的调用不执行任何外部动作，也不写入
        记忆。参数非法时附带该工具的示例调用，路径逃逸与安全事件一起记录。
        """
        agent = self.agent

        if agent.allowed_tools is not None and name not in agent.allowed_tools:
            return ToolResult(
                content=f"error: tool '{name}' is not allowed in this run",
                metadata=_metadata(
                    TOOL_STATUS_REJECTED,
                    tool_error_code=TOOL_ERROR_TOOL_NOT_ALLOWED,
                    risk_level=RISK_LEVEL_HIGH,
                    read_only=False,
                ),
            )

        tool = agent.tools.get(name)
        if tool is None:
            return ToolResult(
                content=f"error: unknown tool '{name}'",
                metadata=_metadata(
                    TOOL_STATUS_REJECTED,
                    tool_error_code=TOOL_ERROR_UNKNOWN_TOOL,
                    risk_level=RISK_LEVEL_HIGH,
                    read_only=False,
                ),
            )

        risky = bool(tool["risky"])
        try:
            agent.validate_tool(name, args)
        except Exception as exc:
            example = agent.tool_example(name)
            message = f"error: invalid arguments for {name}: {exc}"
            if example:
                message += f"\nexample: {example}"
            security_event_type = SECURITY_EVENT_PATH_ESCAPE if isinstance(exc, PathEscapeError) else ""
            return ToolResult(
                content=message,
                metadata=_metadata(
                    TOOL_STATUS_REJECTED,
                    tool_error_code=TOOL_ERROR_INVALID_ARGUMENTS,
                    security_event_type=security_event_type,
                    risk_level=RISK_LEVEL_HIGH if risky else RISK_LEVEL_LOW,
                    read_only=not risky,
                ),
            )

        if agent.repeated_tool_call(name, args):
            return ToolResult(
                content=f"error: repeated identical tool call for {name}; choose a different tool or return a final answer",
                metadata=_metadata(
                    TOOL_STATUS_REJECTED,
                    tool_error_code=TOOL_ERROR_REPEATED_IDENTICAL_CALL,
                    risk_level=RISK_LEVEL_HIGH if risky else RISK_LEVEL_LOW,
                    read_only=not risky,
                ),
            )

        if risky and not agent.approve(name, args):
            return ToolResult(
                content=f"error: approval denied for {name}",
                metadata=_metadata(
                    TOOL_STATUS_REJECTED,
                    tool_error_code=TOOL_ERROR_APPROVAL_DENIED,
                    security_event_type=SECURITY_EVENT_READ_ONLY_BLOCK
                    if agent.read_only
                    else SECURITY_EVENT_APPROVAL_DENIED,
                    risk_level=RISK_LEVEL_HIGH,
                    read_only=False,
                ),
            )

        return self._run(name, args, tool=tool, risky=risky)

    def _run(self, name: str, args: dict[str, Any], *, tool: dict[str, Any], risky: bool) -> ToolResult:
        """执行工具本体，并用 Workspace 快照差异补齐结果元数据。

        只有高风险工具才做快照对比：只读工具不可能改变仓库，为它们付出全仓库哈希成本不划算。
        成功路径里 `run_shell` 额外解析退出码——“改了文件但命令失败”记为
        ``partial_success``，因为那次调用确实留下了需要复盘的副作用。
        """
        agent = self.agent
        before_snapshot = agent.capture_workspace_snapshot() if risky else {}
        after_snapshot = before_snapshot
        try:
            content = clip(tool["run"](args), MAX_TOOL_OUTPUT)
            after_snapshot = agent.capture_workspace_snapshot() if risky else before_snapshot
            affected_paths, diff_summary = agent.diff_workspace_snapshots(before_snapshot, after_snapshot)
            workspace_changed = bool(affected_paths)
            tool_status = TOOL_STATUS_OK
            tool_error_code = ""
            if name == "run_shell":
                exit_code = _shell_exit_code(content)
                if exit_code != 0 and workspace_changed:
                    tool_status = TOOL_STATUS_PARTIAL_SUCCESS
                    tool_error_code = TOOL_ERROR_TOOL_PARTIAL_SUCCESS
                elif exit_code != 0:
                    tool_status = TOOL_STATUS_ERROR
                    tool_error_code = TOOL_ERROR_TOOL_FAILED
            agent.update_memory_after_tool(name, args, content)
            metadata = _metadata(
                tool_status,
                tool_error_code=tool_error_code,
                risk_level=RISK_LEVEL_HIGH if risky else RISK_LEVEL_LOW,
                read_only=not risky,
                affected_paths=affected_paths,
                workspace_changed=workspace_changed,
                workspace_fingerprint=agent.workspace.fingerprint(),
                diff_summary=diff_summary,
            )
            agent.record_process_note_for_tool(name, metadata)
            return ToolResult(content=content, metadata=metadata)
        except Exception as exc:
            # 工具可能在抛错之前已经写坏了一部分文件，异常路径同样要给出差异。
            after_snapshot = agent.capture_workspace_snapshot() if risky else before_snapshot
            affected_paths, diff_summary = agent.diff_workspace_snapshots(before_snapshot, after_snapshot)
            workspace_changed = bool(affected_paths)
            security_event_type = SECURITY_EVENT_PATH_ESCAPE if isinstance(exc, PathEscapeError) else ""
            metadata = _metadata(
                TOOL_STATUS_PARTIAL_SUCCESS if workspace_changed else TOOL_STATUS_ERROR,
                tool_error_code=TOOL_ERROR_TOOL_PARTIAL_SUCCESS if workspace_changed else TOOL_ERROR_TOOL_FAILED,
                security_event_type=security_event_type,
                risk_level=RISK_LEVEL_HIGH if risky else RISK_LEVEL_LOW,
                read_only=not risky,
                affected_paths=affected_paths,
                workspace_changed=workspace_changed,
                workspace_fingerprint=agent.workspace.fingerprint(),
                diff_summary=diff_summary,
            )
            agent.record_process_note_for_tool(name, metadata)
            return ToolResult(content=f"error: tool {name} failed: {exc}", metadata=metadata)


def _shell_exit_code(content: str) -> int:
    """从 Shell 结果文本里解析退出码，缺失时按 ``0`` 处理。

    工具输出格式由 `pico.capabilities.tools.builtin.shell` 决定，这里按同一个标记解析；
    解析不到通常意味着输出被裁剪掉了，此时不把它当作失败。
    """
    match = _EXIT_CODE_PATTERN.search(content)
    return int(match.group(1)) if match else 0

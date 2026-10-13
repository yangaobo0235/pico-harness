"""工具层与 runtime 之间的约定：调用上下文、结果与状态词汇。

`ToolContext` 是 runtime 交给工具的最小能力面（根目录、路径解析、Shell 环境、委派深度），
`ToolResult` 是工具返回给 runtime 的唯一形状。状态词汇在这里统一定义，使执行器、Trace 工件、
安全事件统计和记忆沉淀读到同一个词，而不是各自拼写字符串。

本模块不包含具体工具实现，也不做审批判断；执行边界属于 `pico.capabilities.tools.executor`，
是否放行属于 `pico.security.authorization`。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

TOOL_STATUS_OK = "ok"
TOOL_STATUS_PARTIAL_SUCCESS = "partial_success"
TOOL_STATUS_ERROR = "error"
TOOL_STATUS_REJECTED = "rejected"

TOOL_ERROR_INVALID_ARGUMENTS = "invalid_arguments"
TOOL_ERROR_UNKNOWN_TOOL = "unknown_tool"
TOOL_ERROR_TOOL_NOT_ALLOWED = "tool_not_allowed"
TOOL_ERROR_REPEATED_IDENTICAL_CALL = "repeated_identical_call"
TOOL_ERROR_APPROVAL_DENIED = "approval_denied"
TOOL_ERROR_TOOL_FAILED = "tool_failed"
TOOL_ERROR_TOOL_PARTIAL_SUCCESS = "tool_partial_success"

SECURITY_EVENT_PATH_ESCAPE = "path_escape"
SECURITY_EVENT_READ_ONLY_BLOCK = "read_only_block"
SECURITY_EVENT_APPROVAL_DENIED = "approval_denied"

RISK_LEVEL_LOW = "low"
RISK_LEVEL_HIGH = "high"


@dataclass
class ToolContext:
    """runtime 注入给工具函数的窄上下文。

    工具不直接读取 Agent 实例，因此单元测试可以用一个手工构造的 `ToolContext` 调用单个工具。
    ``path_resolver`` 与 ``shell_env_provider`` 是 runtime 已经绑定好边界与白名单的回调，工具
    拿不到绕过它们的方式；``spawn_delegate`` 只在委派工具里使用，其余工具为 ``None``。
    """

    root: Path
    path_resolver: Callable[[str], Path]
    shell_env_provider: Callable[[], dict[str, str]]
    depth: int
    max_depth: int
    spawn_delegate: Callable[[dict[str, Any]], str] | None = None

    def path(self, raw_path: object) -> Path:
        """把工具参数里的路径解析为 Workspace 内的绝对路径。

        越界由 runtime 注入的解析器抛出 `PathEscapeError`，本方法不吞异常，也不检查文件是否
        存在——那是各工具自己的语义。
        """
        return self.path_resolver(str(raw_path))

    def shell_env(self) -> dict[str, str]:
        """返回执行命令时使用的环境变量集合。"""
        return self.shell_env_provider()


@dataclass(frozen=True)
class ToolResult:
    """一次工具调用的对外结果。

    ``content`` 一定是模型可读文本：成功结果是工具输出，失败结果是带原因的 ``error:`` 前缀
    文本，这样模型下一轮总能拿到反馈而不需要理解 Python 异常。``metadata`` 记录状态、错误码、
    风险等级和受影响路径，供 Trace、报告与记忆沉淀使用，不进入模型可见文本。
    """

    content: str
    metadata: dict[str, Any]

    @property
    def status(self) -> str:
        """返回元数据里的工具状态，缺失时按 `TOOL_STATUS_ERROR` 处理。"""
        return str(self.metadata.get("tool_status", TOOL_STATUS_ERROR))

    @property
    def ok(self) -> bool:
        """判断这次调用是否被记为成功。"""
        return self.status == TOOL_STATUS_OK

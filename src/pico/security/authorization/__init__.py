"""判断一个动作在当前运行里是否被允许。

这里聚合三件事：文件路径能否落在 Workspace 内、命令能继承哪些环境变量、高风险动作是否需要
询问用户。它们共用同一个判断口径——“平台在执行前守住边界”，而不是指望模型自觉。

工具是否注册、参数是否合法属于 `pico.capabilities.tools`；本层不执行任何动作，也不记录结果。
"""

from pico.security.authorization.approval import (
    APPROVAL_APPROVED,
    APPROVAL_ASK_USER,
    APPROVAL_DENIED,
    evaluate_approval,
)
from pico.security.authorization.shell_environment import filter_shell_env
from pico.security.authorization.workspace_paths import PathEscapeError, resolve_within_root

__all__ = [
    "APPROVAL_ASK_USER",
    "APPROVAL_APPROVED",
    "APPROVAL_DENIED",
    "PathEscapeError",
    "evaluate_approval",
    "filter_shell_env",
    "resolve_within_root",
]

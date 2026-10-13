"""Workspace 职责组：仓库事实的采集与比较。

`snapshot` 提供进入 Prompt 的仓库第一印象与指纹，`diff` 提供高风险动作前后的文件差异。两者都
只描述事实，不判断是否允许执行，也不写入工件。

路径能否落在 Workspace 之内属于 `pico.security.authorization.workspace_paths`；把快照渲染进
Prompt 属于 `pico.runtime.context`。
"""

from pico.runtime.workspace.diff import capture_snapshot, diff_snapshots
from pico.runtime.workspace.snapshot import WorkspaceContext

__all__ = [
    "WorkspaceContext",
    "capture_snapshot",
    "diff_snapshots",
]

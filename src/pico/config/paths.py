"""Workspace 内 `.pico/` 状态目录的布局。

会话、运行工件与长期记忆各自占一个子目录，路径只在这里拼接一次，避免出现“某处硬编码了
`.pico/sessions`，另一处却写成 `.pico/session`”的分歧。所有状态都留在被操作的仓库内，随仓库
一起移动，也一起被 Git 忽略；需要仓库外目录的部署方式由调用方显式传入根路径。
"""

from dataclasses import dataclass
from pathlib import Path

STATE_DIR_NAME = ".pico"
SESSIONS_DIR_NAME = "sessions"
RUNS_DIR_NAME = "runs"
MEMORY_DIR_NAME = "memory"

SESSION_FILE_SUFFIX = ".json"
TASK_STATE_FILE_NAME = "task_state.json"
TRACE_FILE_NAME = "trace.jsonl"
REPORT_FILE_NAME = "report.json"


@dataclass(frozen=True)
class WorkspacePaths:
    """一个 Workspace 对应的 Pico 状态目录集合。

    ``root`` 是被 agent 操作的仓库根目录，不是 Pico 自身的安装位置。对象不创建目录：写入者
    （`SessionStore`、`RunStore`）在真正落盘时才建立缺失目录，避免“只是读一下路径”也产生副作用。
    """

    root: Path

    @property
    def state_dir(self) -> Path:
        """返回 `.pico/` 本身。"""
        return self.root / STATE_DIR_NAME

    @property
    def sessions_dir(self) -> Path:
        """返回会话 JSON 所在目录。"""
        return self.state_dir / SESSIONS_DIR_NAME

    @property
    def runs_dir(self) -> Path:
        """返回每次运行的工件根目录。"""
        return self.state_dir / RUNS_DIR_NAME

    @property
    def memory_dir(self) -> Path:
        """返回跨会话长期记忆目录。"""
        return self.state_dir / MEMORY_DIR_NAME

    def session_file(self, session_id: str) -> Path:
        """返回某个会话对应的 JSON 文件路径，文件可能尚不存在。"""
        return self.sessions_dir / f"{session_id}{SESSION_FILE_SUFFIX}"

    def run_dir(self, run_id: str) -> Path:
        """返回一次运行的工件目录。"""
        return self.runs_dir / run_id

    def session_ids(self) -> list[str]:
        """按 mtime 从旧到新列出已存在的会话 ID。

        只读取文件名，不解析内容，因此损坏的会话文件仍会出现在列表里；``latest`` 语义由调用方
        决定，恢复入口通常取最后一个。
        """
        files = sorted(self.sessions_dir.glob(f"*{SESSION_FILE_SUFFIX}"), key=lambda path: path.stat().st_mtime)
        return [path.stem for path in files]

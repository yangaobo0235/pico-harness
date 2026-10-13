"""会话的本地持久化。

`SessionStore` 只认一种格式：一个会话对应一个 JSON 文件，文件名就是会话 ID。恢复一次中断的
工作靠它，`/session` 命令报出路径也靠它。

写入使用原子替换，因此进程中途退出不会留下半截 JSON；但这里没有文件锁、没有版本迁移，也没有
并发写保护——同一会话同时被两个进程打开时，后保存的一方覆盖前一方，这是 Pico 单会话单使用者的
既定前提。运行工件（task_state、trace、report）不属于会话，由 `pico.observability` 负责。
"""

import json
from pathlib import Path
from typing import Any

from pico.shared.atomic_io import write_json_atomic
from pico.shared.paths import ensure_dir


class SessionStore:
    """按 ``<session-id>.json`` 存取会话字典。

    构造时就建立目录，因此“保存第一个会话”不需要额外的存在性检查；``root`` 通常是
    `pico.config.paths.WorkspacePaths.sessions_dir`。所有读取都返回普通字典，调用方可以在
    修改后原样保存，不需要额外的序列化协议。
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        ensure_dir(self.root)

    def path(self, session_id: str) -> Path:
        """返回某个会话对应的文件路径，文件可能还不存在。"""
        return self.root / f"{session_id}.json"

    def save(self, session: dict[str, Any]) -> Path:
        """原子写入整个会话，返回写入路径。

        键顺序保持插入顺序，`history` 因此在文件里也按时间排列，方便直接肉眼看一次会话。
        会话必须已经有 ``id``；缺少时抛 `KeyError`，因为这通常意味着上游构造现场出错，
        静默生成新 ID 会让一次保存变成两条会话。
        """
        path = self.path(session["id"])
        return write_json_atomic(path, session, sort_keys=False)

    def load(self, session_id: str) -> dict[str, Any]:
        """读取一个会话并原样返回。

        文件不存在时由 `pathlib` 抛出 `FileNotFoundError`，交给 CLI 翻译成“找不到该会话”的提示。
        这里不补齐字段：装配运行时的时候由 `Pico` 统一补齐一次，读出与会话文件一致的原始内容
        才是本方法的职责，否则导出与对比旧工件会被凭空多出的默认键干扰。
        """
        return json.loads(self.path(session_id).read_text(encoding="utf-8"))

    def latest(self) -> str | None:
        """返回最近修改的会话 ID，目录为空时返回 ``None``。

        “最近”依据文件 mtime 而不是会话内的时间戳：被显式恢复并再次保存的会话会重新成为最新，
        这正是 `--resume latest` 想表达的语义。mtime 在跨文件系统复制时可能失真。
        """
        files = sorted(self.root.glob("*.json"), key=lambda path: path.stat().st_mtime)
        return files[-1].stem if files else None

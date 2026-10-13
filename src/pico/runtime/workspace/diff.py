"""用文件哈希比较执行前后的 Workspace，回答“这次调用改了什么”。

高风险工具执行前后各取一次快照（`capture_snapshot`），再对两份 ``路径 -> 摘要`` 求差
（`diff_snapshots`）。这是平台层的客观证据：模型说“我只改了一个文件”不算数，差异算数。

不读取内容做行级 diff，也不跟踪权限变化——摘要只到“文件变过”这一层。跨会话的历史变更不保留，
每次比较都在一次工具调用内完成。
"""

import hashlib
from pathlib import Path

from pico.runtime.workspace.snapshot import is_ignored


def capture_snapshot(root: Path) -> dict[str, str]:
    """返回 ``root`` 下每个可见文件的 ``相对路径 -> SHA-256``。

    忽略目录（`.git`、`.venv`、`__pycache__`、`.pico` 等）整段跳过，只处理文件而不记录目录本身。
    读取失败（权限、正在写入、符号链接断裂）按单文件跳过：一次快照的目的是比较“多数文件有没有
    变”，一个读不出来的文件不应该让整次比较失败，也不该被误记成“已删除”。
    """
    snapshot: dict[str, str] = {}
    for path in root.rglob("*"):
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            continue
        if is_ignored(relative_parts):
            continue
        if not path.is_file():
            continue
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except Exception:
            continue
        snapshot[path.relative_to(root).as_posix()] = digest
    return snapshot


def diff_snapshots(before: dict[str, str], after: dict[str, str]) -> tuple[list[str], list[str]]:
    """比较两份快照，返回 ``(受影响路径, 变化摘要)``。

    路径按字典序输出，摘要形如 ``created:`` / ``modified:`` / ``deleted:``，两者长度一致，
    因此可以直接进入 Trace 而不需要额外配对。摘要只表达“变化类别”，不表达变化行数或内容，
    模型需要具体内容时应重新读取文件。
    """
    changed_paths: list[str] = []
    summaries: list[str] = []
    for path in sorted(set(before) | set(after)):
        if before.get(path) == after.get(path):
            continue
        changed_paths.append(path)
        if path not in before:
            summaries.append(f"created:{path}")
        elif path not in after:
            summaries.append(f"deleted:{path}")
        else:
            summaries.append(f"modified:{path}")
    return changed_paths, summaries

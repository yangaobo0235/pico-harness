"""Workspace 内的文件读取、写入、精确替换与目录列举。

四个工具共享同一个路径解析入口（`ToolContext.path`），因此 ``..``、符号链接和绝对路径都
绕不出仓库根。返回统一为模型可读文本，带行号的读取结果让模型可以在下一步用同一行号引用
内容，而不是自己数行。

这里不判断动作是否被允许：是否风险、是否审批、结果如何裁剪都由
`pico.capabilities.tools.executor` 负责；工具抛出的 `ValueError` 会被执行器规范化成
``error:`` 文本并记录状态。
"""

from pathlib import Path
from typing import Any

from pico.capabilities.tools.contracts import ToolContext
from pico.config.models.runtime import (
    IGNORED_PATH_NAMES,
    TOOL_LIST_FILES_MAX_ENTRIES,
    TOOL_READ_FILE_DEFAULT_END,
    TOOL_READ_FILE_DEFAULT_START,
)

LIST_FILES_SPEC = {
    "schema": {"path": "str='.'"},
    "risky": False,
    "description": "List files in the workspace.",
}
READ_FILE_SPEC = {
    "schema": {"path": "str", "start": "int=1", "end": "int=200"},
    "risky": False,
    "description": "Read a UTF-8 file by line range.",
}
WRITE_FILE_SPEC = {
    "schema": {"path": "str", "content": "str"},
    "risky": True,
    "description": "Write a text file.",
}
PATCH_FILE_SPEC = {
    "schema": {"path": "str", "old_text": "str", "new_text": "str"},
    "risky": True,
    "description": "Replace one exact text block in a file.",
}

LIST_FILES_EXAMPLE = '<tool>{"name":"list_files","args":{"path":"."}}</tool>'
READ_FILE_EXAMPLE = '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":80}}</tool>'
WRITE_FILE_EXAMPLE = '<tool name="write_file" path="binary_search.py"><content>def binary_search(nums, target):\n    return -1\n</content></tool>'
PATCH_FILE_EXAMPLE = '<tool name="patch_file" path="binary_search.py"><old_text>return -1</old_text><new_text>return mid</new_text></tool>'


def _read_text(path: Path) -> str:
    """以 UTF-8 读取文本，无法解码的字节替换而不是报错。

    模型面对的是仓库里可能存在的任意历史文件；因为一个坏字节就拒绝整个读取会让 agent 无法
    继续，替换字符至少保留了结构与可读部分。
    """
    return path.read_text(encoding="utf-8", errors="replace")


def validate_list_files(context: ToolContext, args: dict[str, Any]) -> None:
    """确认 ``path`` 存在且是一个目录。"""
    path = context.path(args.get("path", "."))
    if not path.is_dir():
        raise ValueError("path is not a directory")


def validate_read_file(context: ToolContext, args: dict[str, Any]) -> None:
    """确认目标文件存在，且行号区间 ``start``/``end`` 自洽。"""
    path = context.path(args["path"])
    if not path.is_file():
        raise ValueError("path is not a file")
    start = int(args.get("start", TOOL_READ_FILE_DEFAULT_START))
    end = int(args.get("end", TOOL_READ_FILE_DEFAULT_END))
    if start < 1 or end < start:
        raise ValueError("invalid line range")


def validate_write_file(context: ToolContext, args: dict[str, Any]) -> None:
    """确认目标不是已存在的目录，且提供了 ``content``。"""
    path = context.path(args["path"])
    if path.exists() and path.is_dir():
        raise ValueError("path is a directory")
    if "content" not in args:
        raise ValueError("missing content")


def validate_patch_file(context: ToolContext, args: dict[str, Any]) -> None:
    """确认 ``old_text`` 在文件中精确出现一次。

    替换刻意做得很严格：命中次数不是 1 就拒绝，这样修改是确定的，失败原因也解释得清楚。
    读取整个文件用于计数，大文件的成本由执行器统一裁剪结果，不在这里做分页。
    """
    path = context.path(args["path"])
    if not path.is_file():
        raise ValueError("path is not a file")
    old_text = str(args.get("old_text", ""))
    if not old_text:
        raise ValueError("old_text must not be empty")
    if "new_text" not in args:
        raise ValueError("missing new_text")
    text = _read_text(path)
    count = text.count(old_text)
    if count != 1:
        raise ValueError(f"old_text must occur exactly once, found {count}")


def list_files(context: ToolContext, args: dict[str, Any]) -> str:
    """按“目录在前、名称不区分大小写”的顺序列出 ``path`` 一层内容。

    条目数上限是 `TOOL_LIST_FILES_MAX_ENTRIES`，超出部分不报告数量，因为“这一层很大”本身
    已经足够指导下一步。空目录返回 ``(empty)``，让模型把它读成事实而不是错误。
    """
    path = context.path(args.get("path", "."))
    if not path.is_dir():
        raise ValueError("path is not a directory")
    entries = [
        item
        for item in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        if item.name not in IGNORED_PATH_NAMES
    ]
    lines = []
    for entry in entries[:TOOL_LIST_FILES_MAX_ENTRIES]:
        kind = "[D]" if entry.is_dir() else "[F]"
        lines.append(f"{kind} {entry.relative_to(context.root)}")
    return "\n".join(lines) or "(empty)"


def read_file(context: ToolContext, args: dict[str, Any]) -> str:
    """按 ``start``/``end``（1-based，含端点）读取文件并带上行号。

    标题行输出相对路径，便于模型在回答里引用；行号使用真实宽度对齐，复制片段时不会错位。
    """
    path = context.path(args["path"])
    if not path.is_file():
        raise ValueError("path is not a file")
    start = int(args.get("start", TOOL_READ_FILE_DEFAULT_START))
    end = int(args.get("end", TOOL_READ_FILE_DEFAULT_END))
    if start < 1 or end < start:
        raise ValueError("invalid line range")
    lines = _read_text(path).splitlines()
    body = "\n".join(f"{number:>4}: {line}" for number, line in enumerate(lines[start - 1 : end], start=start))
    return f"# {path.relative_to(context.root)}\n{body}"


def write_file(context: ToolContext, args: dict[str, Any]) -> str:
    """整体写入文本文件，必要时创建父目录。

    这是覆盖写而不是追加，返回字符数让模型能核对是否真的写出了预期规模。不做编码探测，
    统一 UTF-8；需要二进制或结构化改写时应改用 ``patch_file``。
    """
    path = context.path(args["path"])
    content = str(args["content"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"wrote {path.relative_to(context.root)} ({len(content)} chars)"


def patch_file(context: ToolContext, args: dict[str, Any]) -> str:
    """把文件里唯一一次出现的 ``old_text`` 换成 ``new_text``。

    校验阶段已经确认命中恰好一次，这里的 `count != 1` 复查是为了覆盖“校验与写入之间文件被
    外部改动”的窗口，宁可失败也不做模糊匹配。
    """
    path = context.path(args["path"])
    if not path.is_file():
        raise ValueError("path is not a file")
    old_text = str(args.get("old_text", ""))
    if not old_text:
        raise ValueError("old_text must not be empty")
    if "new_text" not in args:
        raise ValueError("missing new_text")
    text = _read_text(path)
    count = text.count(old_text)
    if count != 1:
        raise ValueError(f"old_text must occur exactly once, found {count}")
    path.write_text(text.replace(old_text, str(args["new_text"]), 1), encoding="utf-8")
    return f"patched {path.relative_to(context.root)}"

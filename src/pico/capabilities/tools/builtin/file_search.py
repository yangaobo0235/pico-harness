"""在 Workspace 内做内容搜索。

搜索发生在 agent 控制循环里，每一轮都在等它，所以优先使用 `rg`：`shutil.which` 命中就交给
外部程序，未命中才退回 Python 遍历。两条路径返回同一种文本形状
（``相对路径:行号:内容``），模型不需要知道这次用的是哪个实现。

结果上限是固定条数而不是分数，命中数达到上限即停止，返回的匹配可能不完整。这是有意的
取舍：一次宽泛 pattern 扫描整个仓库的成本不可预测，而 agent 通常更需要“先看到形状”。
"""

import shutil
import subprocess
from typing import Any

from pico.capabilities.tools.contracts import ToolContext
from pico.config.models.runtime import IGNORED_PATH_NAMES, TOOL_SEARCH_MAX_MATCHES

SEARCH_SPEC = {
    "schema": {"pattern": "str", "path": "str='.'"},
    "risky": False,
    "description": "Search the workspace with rg or a simple fallback.",
}

SEARCH_EXAMPLE = '<tool>{"name":"search","args":{"pattern":"binary_search","path":"."}}</tool>'

#: `rg` 的默认返回上限，与 Python 回退路径共用同一个数字，避免两种实现给出不同规模的结果。
_RG_MAX_COUNT = str(TOOL_SEARCH_MAX_MATCHES)


def validate_search(context: ToolContext, args: dict[str, Any]) -> None:
    """确认 ``pattern`` 非空，且搜索根目录在 Workspace 内。"""
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("pattern must not be empty")
    context.path(args.get("path", "."))


def _fallback_matches(context: ToolContext, path: Any, pattern: str) -> list[str]:
    """用纯 Python 逐文件、逐行做大小写不敏感的子串匹配。

    传入文件时只扫描该文件，传入目录时递归并跳过忽略目录。匹配列表在达到上限时立即返回，
    因此超大仓库里的宽泛 pattern 也只消耗有限成本。读取错误按单文件吞掉：一个不可读的
    二进制文件不应该让整次搜索失败。
    """
    files = (
        [path]
        if path.is_file()
        else [
            item
            for item in path.rglob("*")
            if item.is_file() and not any(part in IGNORED_PATH_NAMES for part in item.relative_to(context.root).parts)
        ]
    )
    matches: list[str] = []
    needle = pattern.lower()
    for file_path in files:
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if needle in line.lower():
                matches.append(f"{file_path.relative_to(context.root)}:{number}:{line}")
                if len(matches) >= TOOL_SEARCH_MAX_MATCHES:
                    return matches
    return matches


def search(context: ToolContext, args: dict[str, Any]) -> str:
    """返回 ``pattern`` 在 ``path`` 下的匹配行，无匹配时给出 ``(no matches)``。

    `rg` 存在时使用 ``--smart-case`` 与行号输出，并把 ``path`` 解析为 Workspace 内的绝对路径，
    避免 ``..`` 指到仓库外。外部程序失败（权限、非法 pattern）时不重试也不回退，直接把它的
    stderr 作为结果文本返回，让模型自己决定换一个 pattern 还是改用读取工具。
    """
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        raise ValueError("pattern must not be empty")
    path = context.path(args.get("path", "."))

    if shutil.which("rg"):
        result = subprocess.run(
            ["rg", "-n", "--smart-case", "--max-count", _RG_MAX_COUNT, pattern, str(path)],
            cwd=context.root,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip() or result.stderr.strip() or "(no matches)"

    return "\n".join(_fallback_matches(context, path, pattern)) or "(no matches)"

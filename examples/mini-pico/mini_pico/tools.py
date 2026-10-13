"""工具目录：模型能看见的签名、能用的参数规则与真正干活的实现。

`TOOL_SPECS` 是这五个工具的唯一事实来源：名称、描述、schema 文本和 `risky` 标记。
`tool_signature()` 把它渲染进 Prompt，`validate_tool()` 按名称分派到各自的参数校验，
`run_tool()` 在校验之后执行对应的私有实现。`risky` 是这里唯一的权限信息——写入与替换算高风险，
读取、列表与搜索算只读，执行层据此决定审批与受影响路径。

这里不判断“这次调用是否被允许”：审批策略、结果裁剪和错误回灌属于 `mini_pico.tool_executor`，
路径能否落在工作区之内属于 `mini_pico.workspace`。工具也不是动态发现的，而是显式列出的——
字典的插入顺序就是 Prompt 里的工具顺序，保持稳定才能让两次运行看到同一段文本。主项目把这份目录
拆成 `capabilities.tools.registry` 加 `capabilities.tools.builtin.*`，教学版合并成一个模块，
但有同样的分工：定义、校验、执行三层各自独立。
"""

import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from mini_pico.workspace import IGNORED_NAMES, Workspace


@dataclass(frozen=True)
class ToolSpec:
    """一个工具对外的定义：给模型看的描述、是否高风险、以及参数形状文本。

    ``schema`` 是给人和模型读的伪 JSON，不参与解析，只用于渲染 Prompt 签名；真正的约束写在
    `validate_tool` 的分支里。
    """

    description: str
    risky: bool
    schema: str


TOOL_SPECS = {
    "list_files": ToolSpec("List files in the workspace.", False, '{"path": "str=."}'),
    "read_file": ToolSpec(
        "Read a UTF-8 file by line range.", False, '{"path": "str", "start": "int=1", "end": "int=120"}'
    ),
    "search": ToolSpec("Search text in the workspace.", False, '{"pattern": "str", "path": "str=."}'),
    "write_file": ToolSpec("Write a text file.", True, '{"path": "str", "content": "str"}'),
    "patch_file": ToolSpec(
        "Replace one exact text block in a file.", True, '{"path": "str", "old_text": "str", "new_text": "str"}'
    ),
}


def tool_signature() -> str:
    """渲染 Prompt 里的工具清单，每行一个工具并标注只读或高风险。"""
    lines = []
    for name, spec in TOOL_SPECS.items():
        risk = "risky" if spec.risky else "read-only"
        lines.append(f"- {name} ({risk}) {spec.schema}: {spec.description}")
    return "\n".join(lines)


def validate_tool(workspace: Workspace, name: str, args: dict[str, Any] | None) -> None:
    """按名称分派到该工具自己的参数校验，不合法就抛 `ValueError`。

    ``args`` 为 ``None`` 时按空字典处理，让“给了工具名但没给参数”落到各工具自己的必填检查，而不是
    在校验层抛出一个没有信息量的类型错误。未登记名称在这里也报错，因为 `run_tool` 会被直接调用；
    执行层的调用点先查目录并返回 `unknown tool` 结果，两条路径的措辞保持一致，模型读到的反馈才不
    会因入口不同而变。
    """
    if name not in TOOL_SPECS:
        raise ValueError(f"unknown tool: {name}")
    args = args or {}
    if name == "list_files":
        path = workspace.path(args.get("path", "."))
        if not path.is_dir():
            raise ValueError("path is not a directory")
        return
    if name == "read_file":
        path = workspace.path(args["path"])
        if not path.is_file():
            raise ValueError("path is not a file")
        start = int(args.get("start", 1))
        end = int(args.get("end", 120))
        if start < 1 or end < start:
            raise ValueError("invalid line range")
        return
    if name == "search":
        pattern = str(args.get("pattern", "")).strip()
        if not pattern:
            raise ValueError("pattern must not be empty")
        workspace.path(args.get("path", "."))
        return
    if name == "write_file":
        path = workspace.path(args["path"])
        if path.exists() and path.is_dir():
            raise ValueError("path is a directory")
        if "content" not in args:
            raise ValueError("missing content")
        return
    if name == "patch_file":
        path = workspace.path(args["path"])
        if not path.is_file():
            raise ValueError("path is not a file")
        old_text = str(args.get("old_text", ""))
        if not old_text:
            raise ValueError("old_text must not be empty")
        if "new_text" not in args:
            raise ValueError("missing new_text")
        count = path.read_text(encoding="utf-8", errors="replace").count(old_text)
        if count != 1:
            raise ValueError(f"old_text must occur exactly once, found {count}")


def run_tool(workspace: Workspace, name: str, args: dict[str, Any]) -> str:
    """校验后执行工具，返回模型可读的纯文本结果。

    执行前重新校验一次，因此直接调用本函数也带着参数护栏；执行层的审批判断不在这里，
    它发生在调用之前。未登记名称在校验步就已经抛出，最后的 `raise` 只是把“目录里有、
    实现里没有”这种不一致暴露出来。
    """
    validate_tool(workspace, name, args)
    if name == "list_files":
        return _list_files(workspace, args)
    if name == "read_file":
        return _read_file(workspace, args)
    if name == "search":
        return _search(workspace, args)
    if name == "write_file":
        return _write_file(workspace, args)
    if name == "patch_file":
        return _patch_file(workspace, args)
    raise ValueError(f"unknown tool: {name}")


def _list_files(workspace: Workspace, args: dict[str, Any]) -> str:
    """列出目录顶层条目，目录在前、名称不区分大小写排序，最多 120 条。"""
    path = workspace.path(args.get("path", "."))
    entries = [
        item
        for item in sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower()))
        if item.name not in IGNORED_NAMES
    ]
    lines = []
    for entry in entries[:120]:
        kind = "[D]" if entry.is_dir() else "[F]"
        lines.append(f"{kind} {workspace.relative(entry)}")
    return "\n".join(lines) or "(empty)"


def _read_file(workspace: Workspace, args: dict[str, Any]) -> str:
    """按行范围读取文件并带上行号前缀，标题行让模型知道读的是哪个路径。"""
    path = workspace.path(args["path"])
    start = int(args.get("start", 1))
    end = int(args.get("end", 120))
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    body = "\n".join(f"{number:>4}: {line}" for number, line in enumerate(lines[start - 1 : end], start=start))
    return f"# {workspace.relative(path)}\n{body}"


def _search(workspace: Workspace, args: dict[str, Any]) -> str:
    """搜索文本：本机有 ripgrep 就用它，否则退回 Python 侧扫描，两条路径都上限 80 条。"""
    pattern = str(args["pattern"])
    path = workspace.path(args.get("path", "."))
    if shutil.which("rg"):
        result = subprocess.run(
            ["rg", "-n", "--smart-case", "--max-count", "80", pattern, str(path)],
            cwd=workspace.root,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() or "(no matches)"
    matches = []
    files = [path] if path.is_file() else [item for item in path.rglob("*") if item.is_file()]
    for file_path in files:
        if any(part in IGNORED_NAMES for part in file_path.relative_to(workspace.root).parts):
            continue
        for number, line in enumerate(file_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if pattern.lower() in line.lower():
                matches.append(f"{workspace.relative(file_path)}:{number}:{line}")
                if len(matches) >= 80:
                    return "\n".join(matches)
    return "\n".join(matches) or "(no matches)"


def _write_file(workspace: Workspace, args: dict[str, Any]) -> str:
    """整份写入文件，必要时创建父目录——覆盖是有意的，教学版没有差异确认。"""
    path = workspace.path(args["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(args["content"]), encoding="utf-8")
    return f"wrote {workspace.relative(path)}"


def _patch_file(workspace: Workspace, args: dict[str, Any]) -> str:
    """精确替换第一处匹配；“恰好出现一次”由校验步保证，这里不再重复判断。"""
    path = workspace.path(args["path"])
    text = path.read_text(encoding="utf-8")
    old_text = str(args["old_text"])
    new_text = str(args["new_text"])
    path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
    return f"patched {workspace.relative(path)}"

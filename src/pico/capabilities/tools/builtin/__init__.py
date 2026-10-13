"""内置工具集合：模型可以申请的静态动作目录。

每个条目声明 schema、风险标记、面向模型的描述、示例调用与参数校验函数，注册表
（`pico.capabilities.tools.registry`）只负责把这些定义绑定到一次具体调用上下文。新增工具
应该写在新模块里并在这里登记一行，而不是把实现塞进注册表。

这里的“内置”表示随发行提供、不依赖外部服务。可选能力（记忆、委派深度控制）仍然由 runtime
决定是否注册，因此本目录不代表模型每轮都会看到全部工具。
"""

from functools import partial
from typing import Any

from pico.capabilities.tools.builtin import file_search, filesystem, shell, spawn
from pico.capabilities.tools.contracts import ToolContext

#: 注册表按名称查找的定义集合；``run`` 与 ``validate`` 在绑定时才绑定 `ToolContext`。
TOOL_DEFINITIONS: dict[str, dict[str, Any]] = {
    "list_files": {
        "spec": filesystem.LIST_FILES_SPEC,
        "example": filesystem.LIST_FILES_EXAMPLE,
        "validate": filesystem.validate_list_files,
        "run": filesystem.list_files,
    },
    "read_file": {
        "spec": filesystem.READ_FILE_SPEC,
        "example": filesystem.READ_FILE_EXAMPLE,
        "validate": filesystem.validate_read_file,
        "run": filesystem.read_file,
    },
    "search": {
        "spec": file_search.SEARCH_SPEC,
        "example": file_search.SEARCH_EXAMPLE,
        "validate": file_search.validate_search,
        "run": file_search.search,
    },
    "run_shell": {
        "spec": shell.RUN_SHELL_SPEC,
        "example": shell.RUN_SHELL_EXAMPLE,
        "validate": shell.validate_run_shell,
        "run": shell.run_shell,
    },
    "write_file": {
        "spec": filesystem.WRITE_FILE_SPEC,
        "example": filesystem.WRITE_FILE_EXAMPLE,
        "validate": filesystem.validate_write_file,
        "run": filesystem.write_file,
    },
    "patch_file": {
        "spec": filesystem.PATCH_FILE_SPEC,
        "example": filesystem.PATCH_FILE_EXAMPLE,
        "validate": filesystem.validate_patch_file,
        "run": filesystem.patch_file,
    },
    "delegate": {
        "spec": spawn.DELEGATE_SPEC,
        "example": spawn.DELEGATE_EXAMPLE,
        "validate": spawn.validate_delegate,
        "run": spawn.delegate,
    },
}

DELEGATE_TOOL_NAME = spawn.DELEGATE_TOOL_NAME

#: 静态目录里的普通工具，不含需要深度判断才能暴露的委派工具。
STANDARD_TOOL_NAMES = tuple(name for name in TOOL_DEFINITIONS if name != DELEGATE_TOOL_NAME)


def bind(name: str, context: ToolContext) -> dict[str, Any]:
    """把某个工具定义绑定到具体上下文，产出注册表使用的可执行条目。

    返回的字典保留 ``schema``、``risky``、``description`` 三个定义字段，使 Prompt 前缀与工具签名
    只依赖声明部分；``run`` 与 ``validate`` 是已经带上上下文的偏函数。未登记名称直接抛
    `KeyError`，因为注册表拼装错误应该在启动时立刻暴露，而不是等到模型发起调用。
    """
    definition = TOOL_DEFINITIONS[name]
    bound = dict(definition["spec"])
    bound["example"] = definition["example"]
    bound["validate"] = partial(definition["validate"], context)
    bound["run"] = partial(definition["run"], context)
    return bound

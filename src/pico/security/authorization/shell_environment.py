"""命令执行环境的最小变量集。

Shell 工具继承父进程环境会把与任务无关的凭证一起带进去，因此执行命令时只传入白名单变量，
并把 `PWD` 改写成实际工作目录。白名单本身来自 `pico.config.models.runtime`，本模块只负责过滤，
不判断哪些变量应该被允许。

`PATH` 有特殊处理：多数仓库操作依赖它，若白名单里配置的 `PATH` 在当前进程中不存在，则回退到
进程环境的 `PATH`，而不是让命令因为找不到解释器而失败。
"""

import os
from pathlib import Path
from typing import Mapping


def filter_shell_env(
    allowlist: tuple[str, ...], root: Path | str, *, env: Mapping[str, str] | None = None
) -> dict[str, str]:
    """按 ``allowlist`` 复制环境变量，并把 ``PWD`` 指向 ``root``。

    白名单中不存在于环境的名称直接跳过，不补空值，避免子进程把空字符串当作“已配置”。
    返回值是新字典，调用方修改它不会影响进程环境。
    """
    source = os.environ if env is None else env
    filtered = {name: source[name] for name in allowlist if name in source}
    filtered["PWD"] = str(root)
    if "PATH" not in filtered and source.get("PATH"):
        filtered["PATH"] = source["PATH"]
    return filtered

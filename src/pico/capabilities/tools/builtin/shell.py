"""在仓库根目录执行一条 Shell 命令。

这是 Pico 风险最高的工具：命令内容由模型给出，平台无法预知它会改什么，因此它被登记为
``risky``，执行前要过审批，执行后由执行器对比 Workspace 快照。本模块只负责把命令跑起来并
把结果整理成模型可读文本，不做命令内容白名单，也不解释退出码的业务含义。

超时上限来自配置，`subprocess` 的 `timeout` 在超时后会杀掉进程并抛出 `TimeoutExpired`；
该异常由执行器捕获并记录为工具失败，不在这里转成文本，避免“超时”被模型读成一次普通输出。
"""

import subprocess
import textwrap
from typing import Any

from pico.capabilities.tools.contracts import ToolContext
from pico.config.models.runtime import (
    TOOL_SHELL_TIMEOUT_DEFAULT_S,
    TOOL_SHELL_TIMEOUT_MAX_S,
    TOOL_SHELL_TIMEOUT_MIN_S,
)

RUN_SHELL_SPEC = {
    "schema": {"command": "str", "timeout": "int=20"},
    "risky": True,
    "description": "Run a shell command in the repo root.",
}

RUN_SHELL_EXAMPLE = (
    '<tool>{"name":"run_shell","args":{"command":"uv run --with pytest python -m pytest -q","timeout":20}}</tool>'
)

#: 结果里固定出现的退出码标记，执行器按它判断 ``partial_success`` 与 ``error``。
EXIT_CODE_PREFIX = "exit_code:"


def validate_run_shell(context: ToolContext, args: dict[str, Any]) -> None:
    """确认命令非空，且超时落在配置的允许区间内。

    区间检查放在执行前，因为一个 ``timeout=0`` 或超大超时的调用会直接占住整轮请求；
    与其让模型等待，不如立刻给出可纠正的错误。
    """
    command = str(args.get("command", "")).strip()
    if not command:
        raise ValueError("command must not be empty")
    timeout = int(args.get("timeout", TOOL_SHELL_TIMEOUT_DEFAULT_S))
    if timeout < TOOL_SHELL_TIMEOUT_MIN_S or timeout > TOOL_SHELL_TIMEOUT_MAX_S:
        raise ValueError(f"timeout must be in [{TOOL_SHELL_TIMEOUT_MIN_S}, {TOOL_SHELL_TIMEOUT_MAX_S}]")


def run_shell(context: ToolContext, args: dict[str, Any]) -> str:
    """以 `shell=True` 在仓库根执行命令，输出退出码、stdout 与 stderr。

    三条信息总是全部给出，空内容写成 ``(empty)``，这样“命令没输出”和“输出被裁掉”在文本上
    可以区分。环境是过滤后的白名单变量而不是父进程完整环境，减少敏感信息被意外带进命令
    执行环境。``shell=True`` 意味着命令语义由平台 shell 决定，这也是它必须先过审批的原因。
    """
    command = str(args.get("command", "")).strip()
    if not command:
        raise ValueError("command must not be empty")
    timeout = int(args.get("timeout", TOOL_SHELL_TIMEOUT_DEFAULT_S))
    result = subprocess.run(
        command,
        cwd=context.root,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=context.shell_env(),
    )
    return textwrap.dedent(
        f"""\
        {EXIT_CODE_PREFIX} {result.returncode}
        stdout:
        {result.stdout.strip() or "(empty)"}
        stderr:
        {result.stderr.strip() or "(empty)"}
        """
    ).strip()

"""Pico 的命令行界面。

`app` 是发行包 `pico` 命令的入口，`repl` 提供交互循环，`rendering` 负责终端文本与排版。三者
只做输入输出：装配交给 `pico.bootstrap`，执行交给 `pico.runtime`。

入口可以导入任何下层，但下层不允许导入这里——这条边界由
``python -m scripts.ci.check_architecture`` 检查，评测脚本与未来的其他入口才能复用同一台运行时。
"""

from pico.interfaces.cli.app import build_arg_parser, main
from pico.interfaces.cli.repl import run_repl

__all__ = ["build_arg_parser", "main", "run_repl"]

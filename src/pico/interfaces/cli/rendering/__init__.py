"""入口层的文本与排版。

终端首屏和内置命令帮助属于这里：它们决定用户看到什么，但不决定系统做什么。宽度自适应与
裁剪规则集中在 `styles`，避免 REPL 和单次执行两条路径各写一套排版。
"""

from pico.interfaces.cli.rendering.styles import HELP_DETAILS, build_welcome

__all__ = ["HELP_DETAILS", "build_welcome"]

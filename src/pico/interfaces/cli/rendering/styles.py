"""终端首屏与内置命令帮助文本。

Pico 的第一屏同时承担两件事：确认“我确实接上了你要的这个仓库”，以及给出下一次请求可以依赖的
事实（模型、分支、审批策略、会话 ID）。排版按终端宽度自适应，宽度不足时优先裁掉值而不是标签，
因为看不清“在哪个仓库、什么审批模式”比不好看更糟。

这里不产生任何运行状态，也不发起模型请求；帮助文本属于入口层，工具清单的权威来源始终是
Prompt 前缀，两者不一致时以前缀为准。
"""

import shutil
import textwrap

from pico.config.identity import PRODUCT_LOGO, PRODUCT_NAME, PRODUCT_STATUS_LINE, PRODUCT_SUBTITLE
from pico.shared.text import middle

#: 首屏盒子的最小与最大宽度，超出终端宽度时按实际列数收敛。
MIN_BOX_WIDTH = 68
MAX_BOX_WIDTH = 84
#: 双列布局里两列之间的空格数。
COLUMN_GAP = 3

HELP_DETAILS = textwrap.dedent(
    """\
    Commands:
    /help    Show this help message.
    /memory  Show the agent's distilled working memory.
    /session Show the path to the saved session file.
    /reset   Clear the current session history and memory.
    /exit    Exit the agent.
    """
).strip()


def build_welcome(agent, model: str, host: str) -> str:
    """渲染首屏盒子。

    宽度取终端列数并夹在 `MIN_BOX_WIDTH` 与 `MAX_BOX_WIDTH` 之间，两列各占一半。显示的
    ``model`` 与 ``host`` 由调用方从模型客户端读取，本函数不判断它们是否可用，也不尝试连接；
    首屏的唯一职责是把已经装配好的现场如实报出来。
    """
    width = max(MIN_BOX_WIDTH, min(shutil.get_terminal_size((80, 20)).columns, MAX_BOX_WIDTH))
    inner = width - 4
    gap = COLUMN_GAP
    left_width = (inner - gap) // 2
    right_width = inner - gap - left_width

    def row(text: str) -> str:
        body = middle(text, width - 4)
        return f"| {body.ljust(width - 4)} |"

    def divider(char: str = "-") -> str:
        return "+" + char * (width - 2) + "+"

    def center(text: str) -> str:
        body = middle(text, inner)
        return f"| {body.center(inner)} |"

    def cell(label: str, value: str, size: int) -> str:
        body = middle(f"{label:<9} {value}", size)
        return body.ljust(size)

    def pair(left_label: str, left_value: str, right_label: str, right_value: str) -> str:
        left = cell(left_label, left_value, left_width)
        right = cell(right_label, right_value, right_width)
        return f"| {left}{' ' * gap}{right} |"

    line = divider("=")
    rows = [center(text) for text in PRODUCT_LOGO]
    rows.extend(
        [
            center(PRODUCT_NAME),
            center(PRODUCT_SUBTITLE),
            center(PRODUCT_STATUS_LINE),
            divider("-"),
            row(""),
            row("WORKSPACE  " + middle(agent.workspace.cwd, inner - 11)),
            pair("MODEL", model, "BRANCH", agent.workspace.branch),
            pair("APPROVAL", agent.approval_policy, "SESSION", agent.session["id"]),
            row(""),
        ]
    )
    return "\n".join([line, *rows, line])

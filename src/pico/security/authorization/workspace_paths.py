"""把文件类动作锚定在 Workspace 根目录之内。

Pico 允许模型读写文件和执行命令，因此“路径能不能出仓库”是平台层的边界，而不是每个工具各自
记得检查的约定。本模块提供唯一的解析入口：相对路径基于根目录拼接，随后解析符号链接与 ``..``，
再确认结果仍在根目录之下。

检查发生在解析之后，因此符号链接指向仓库外同样被拒绝。跨盘符或 UNC 路径在 Windows 上会由
`os.path.commonpath` 抛出 `ValueError`，这里不额外改写该异常，调用方按“参数不合法”处理。
"""

import os
from pathlib import Path

PATH_ESCAPE_MESSAGE = "path escapes workspace"


class PathEscapeError(ValueError):
    """解析后的路径落在 Workspace 根目录之外。

    继承 `ValueError`，因此只关心“参数不合法”的调用方不需要新增分支；需要区分逃逸与其他
    参数错误时（例如安全事件计数），按本类型判断而不是匹配消息文本。
    """


def resolve_within_root(root: Path, raw_path: object) -> Path:
    """把 ``raw_path`` 解析为 ``root`` 内的绝对路径。

    绝对路径原样参与比较，相对路径先与 ``root`` 拼接，再统一 `resolve()`。返回值不保证存在，
    写文件的工具需要自己判断目标是否已经是一个目录。
    """
    path = Path(raw_path)
    path = path if path.is_absolute() else root / path
    resolved = path.resolve()
    try:
        escaped = os.path.commonpath([str(root), str(resolved)]) != str(root)
    except ValueError:
        # 不在同一盘符时 commonpath 无法给出公共前缀，这本身就是一种逃逸。
        raise PathEscapeError(f"{PATH_ESCAPE_MESSAGE}: {raw_path}") from None
    if escaped:
        raise PathEscapeError(f"{PATH_ESCAPE_MESSAGE}: {raw_path}")
    return resolved

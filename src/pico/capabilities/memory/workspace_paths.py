"""记忆层眼里的路径：能解析、能命名、能比对新鲜度。

`resolve_workspace_path` 把一条自由文本路径锚回根目录之内（越界返回 ``None`` 而不是抛错），
`canonicalize_path` 给出写进记忆状态的那个相对 posix 名字，`file_freshness` 用整文件 SHA-256
表示「记忆里这条摘要对应的是哪一版文件」。

这里不做审批，也不抛 `PathEscapeError`：记忆只在渲染与召回时读路径，一条越界路径应该被安静地
保留原样，而不是打断整轮 prompt 的组装。真正阻止写操作出仓库属于 `pico.security.authorization`，
忽略哪些目录属于 `pico.config.models.runtime`，本模块不参与那两个决定。
"""

import hashlib
from pathlib import Path


def resolve_workspace_path(raw_path: object, workspace_root: str | Path | None = None) -> Path | None:
    """把 ``raw_path`` 解析成 ``workspace_root`` 内的绝对路径，越界时返回 ``None``。

    绝对路径直接参与比较，相对路径先与根目录拼接，再统一 `resolve()`，因此 ``..`` 与符号链接
    指向仓库外都会被拒。``workspace_root`` 为 ``None`` 时不做任何约束，原样返回拼接前的 `Path`，
    这对应「没有工作区上下文」的调用（例如纯单元测试）。

    返回值不保证存在：调用方需要文件是否存在另有判断（`file_freshness` 就是这么做的）。
    """
    path = Path(str(raw_path))
    if workspace_root is None:
        return path

    root = Path(workspace_root).resolve()
    candidate = path if path.is_absolute() else root / path
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    return resolved


def canonicalize_path(raw_path: object, workspace_root: str | Path | None = None) -> str:
    """给出用于记忆字典的路径写法：根目录内的相对 posix 路径。

    同一个文件在两次读取里必须写成同一个字符串，否则「最近文件」和「文件摘要」会因为
    ``./a.py`` 与 ``a.py`` 这种差别被拆成两条。解析不到根目录内、或 ``workspace_root`` 缺失时，
    退回原始字符串的 posix 写法：宁可留一个不那么规范的名字，也不要把整条记录丢掉。

    返回值永远是 `str`（可能是空串），调用方通常还需要再判一次真假。
    """
    resolved = resolve_workspace_path(raw_path, workspace_root)
    if resolved is None:
        return Path(str(raw_path)).as_posix()
    if workspace_root is None:
        return Path(str(raw_path)).as_posix()
    root = Path(workspace_root).resolve()
    return resolved.relative_to(root).as_posix()


def file_freshness(raw_path: object, workspace_root: str | Path | None = None) -> str | None:
    """返回文件内容的 SHA-256 十六进制摘要，读不到时返回 ``None``。

    「读不到」包括三种情况：路径越界、文件不存在、存在但不是普通文件（目录或设备节点）——
    它们都归一为 ``None``，让调用方可以用「摘要相等」这一条规则同时表达「内容没变」和
    「两边都不存在」。

    摘要按整文件字节计算，所以大文件的一次渲染会读满一遍磁盘；记忆层只把它当作廉价的存在性
    指纹，不承诺增量读取，也不试图识别「改了但长度没变」之外的更多结构信息。
    """
    resolved = resolve_workspace_path(raw_path, workspace_root)
    if resolved is None or not resolved.exists() or not resolved.is_file():
        return None
    return hashlib.sha256(resolved.read_bytes()).hexdigest()

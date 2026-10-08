"""Text operations."""


def split_message(content: str, max_len: int = 2000) -> list[str]:
    """把 Content 拆成不超过 ``max_len`` 的 Chunks，并优先在 Line Breaks 处分段。

    Args:
        content: 待拆分 Text Content。空字符串返回空列表，短文本原样作为唯一 Chunk。
        max_len: 每个 Chunk 的 Maximum Length；默认 2000，以兼容 Discord 限制。

    Returns:
        Message Chunks 列表，每项长度都不超过 ``max_len``。截断优先级是换行、空格、最后才是强制
        位置；续段会 `lstrip`，因此分隔处的前导空白不会保留。这里按 Python Character Count，而不是
        UTF-8 Bytes 或平台 Token Count。
    """
    if not content:
        return []
    if len(content) <= max_len:
        return [content]
    chunks: list[str] = []
    while content:
        if len(content) <= max_len:
            chunks.append(content)
            break
        cut = content[:max_len]
        # 优先在换行符处截断，其次是空格，最后才强制截断。
        pos = cut.rfind("\n")
        if pos <= 0:
            pos = cut.rfind(" ")
        if pos <= 0:
            pos = max_len
        chunks.append(content[:pos])
        content = content[pos:].lstrip()
    return chunks

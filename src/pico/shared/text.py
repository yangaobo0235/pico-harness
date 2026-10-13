"""面向 Prompt 与终端渲染的定长文本处理。

`clip` 保留开头、`middle` 保留两端、`tail_clip` 在尾部加省略号，三者都不解析文本语义，
只保证“超长内容也能带着截断事实继续流动”。预算数字由调用方所属层决定，本模块不保存
任何 Prompt 或工具输出上限。
"""

TRUNCATION_MARK = "..."


def clip(text: object, limit: int, *, marker: str = "\n...[truncated {n} chars]") -> str:
    """把 ``text`` 裁到至多 ``limit`` 个字符，并追加被裁掉的字符数。

    参数是非字符串时先 ``str()``，因此工具结果、异常文本都可以直接传入。返回值不超过
    ``limit`` 加上提示后缀；``marker`` 为 ``""`` 时静默截断。这里不做按行或按 Token 的
    对齐，截断点可能落在任意字符边界。
    """
    value = str(text)
    if len(value) <= limit:
        return value
    if not marker:
        return value[:limit]
    return value[:limit] + marker.format(n=len(value) - limit)


def middle(text: object, limit: int) -> str:
    """折叠换行后保留文本两端，中间用 ``...`` 代替。

    单行终端栏位需要“开头和结尾都看得见”，``clip`` 会丢掉结尾。先折叠换行是因为渲染宽度
    按单行计算；``limit`` 小于等于 3 时直接截断，不再保留尾部。
    """
    value = str(text).replace("\n", " ")
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    left = (limit - 3) // 2
    right = limit - 3 - left
    return value[:left] + TRUNCATION_MARK + value[-right:]


def tail_clip(text: object, limit: int) -> str:
    """按 ``limit`` 截断并在尾部补 ``...``，用于 Prompt Section 的定长渲染。

    与 `clip` 的区别是这里不报告被裁掉的字符数：Section 预算关心的是渲染结果长度，
    原始长度已经由 ``SectionRender.raw_chars`` 单独记录。``limit`` 小于等于 0 时返回空串，
    调用方据此可以把一段完全裁掉。
    """
    value = str(text)
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + TRUNCATION_MARK

"""把模型输出解析成 runtime 能执行的动作。

模型返回的是自然语言文本，控制循环需要的是结构化决策：这是一次工具调用、一个最终答案，还是
一次需要重问的格式错误。本模块是文本进入平台控制流的第一道关口，支持两种工具写法：
``<tool>{JSON}</tool>`` 适合短调用，XML 风格的属性与子标签适合写文件这类多行内容。

这里不校验参数是否合法（属于工具自己的校验），也不执行任何动作；解析不出结构时返回重试提示，
让模型自己修正格式，而不是由平台猜测意图。
"""

import json
import re
from typing import Any

KIND_TOOL = "tool"
KIND_FINAL = "final"
KIND_RETRY = "retry"

TOOL_TAG = "tool"
FINAL_TAG = "final"

#: 多行内容可能出现的子标签，按 XML 风格解析时逐个尝试。
BODY_TAGS = ("content", "old_text", "new_text", "command", "task", "pattern", "path")

_RETRY_NOTICE_PREFIX = "Runtime notice"

#: 某些工具的正文可以直接取自标签外的裸文本，避免模型必须再包一层。
_BARE_BODY_TOOLS = {
    "write_file": "content",
    "delegate": "task",
}


def parse(raw: object) -> tuple[str, Any]:
    """把一次模型输出解析成 ``(kind, payload)``。

    判定顺序体现偏好：只要出现工具标签且它排在 ``<final>`` 之前，就按工具调用处理——模型常常
    在调用前后附带解释文本，那部分不作为答案。工具写法先试 JSON 体，失败再试 XML 属性体；
    两者都不成立时返回重试提示，附带正确的格式示例。

    ``kind`` 为 `KIND_TOOL` 时 payload 是 ``{"name": ..., "args": {...}}``，为 `KIND_FINAL` 时
    是答案文本，为 `KIND_RETRY` 时是要回灌给历史的提示文本。完全没有标签但非空的输出按最终
    答案处理，因为“直接回答”在人类读起来仍然成立；空输出必须重试。
    """
    text = str(raw)
    tool_at = text.find(f"<{TOOL_TAG}>")
    final_at = text.find(f"<{FINAL_TAG}>")
    if tool_at != -1 and (final_at == -1 or tool_at < final_at):
        return _parse_json_tool(extract(text, TOOL_TAG))

    xml_at = text.find(f"<{TOOL_TAG}")
    if xml_at != -1 and (final_at == -1 or xml_at < final_at):
        payload = parse_xml_tool(text)
        if payload is not None:
            return KIND_TOOL, payload
        return KIND_RETRY, retry_notice()

    if final_at != -1:
        final = extract(text, FINAL_TAG).strip()
        if final:
            return KIND_FINAL, final
        return KIND_RETRY, retry_notice("model returned an empty <final> answer")

    stripped = text.strip()
    if stripped:
        return KIND_FINAL, stripped
    return KIND_RETRY, retry_notice("model returned an empty response")


def _parse_json_tool(body: str) -> tuple[str, Any]:
    """解析 ``<tool>`` 内的 JSON 调用体。

    JSON 不合法、不是对象、缺少工具名或 ``args`` 类型不对都返回重试提示，提示里带上具体问题，
    这样模型下一次有机会改对。``args`` 为 ``null`` 视作空参数而不是错误，因为模型常用它表示
    “这个工具不需要参数”。
    """
    try:
        payload = json.loads(body)
    except Exception:
        return KIND_RETRY, retry_notice("model returned malformed tool JSON")
    if not isinstance(payload, dict):
        return KIND_RETRY, retry_notice("tool payload must be a JSON object")
    if not str(payload.get("name", "")).strip():
        return KIND_RETRY, retry_notice("tool payload is missing a tool name")
    args = payload.get("args", {})
    if args is None:
        payload["args"] = {}
    elif not isinstance(args, dict):
        return KIND_RETRY, retry_notice()
    return KIND_TOOL, payload


def retry_notice(problem: str | None = None) -> str:
    """构造回灌给模型的重试提示。

    提示同时说明“哪里不对”和“应该怎么写”，并给出多行文件的首选写法；只说“格式错误”通常会让
    模型重复同一个错误写法。
    """
    prefix = _RETRY_NOTICE_PREFIX
    if problem:
        prefix += f": {problem}"
    else:
        prefix += ": model returned malformed tool output"
    return (
        f"{prefix}. Reply with a valid <tool> call or a non-empty <final> answer. "
        'For multi-line files, prefer <tool name="write_file" path="file.py"><content>...</content></tool>.'
    )


def parse_xml_tool(raw: str) -> dict[str, Any] | None:
    """解析 XML 风格工具标签，返回 ``{"name", "args"}`` 或 ``None``。

    属性里必须给出 ``name``；正文中的已知子标签（``content``、``old_text`` 等）按原样保留
    空白，写成文件的正文因此不会被二次加工。没有子标签时，``write_file`` 与 ``delegate``
    直接把裸正文当作对应字段，这是两种工具最常见的写法。
    """
    match = re.search(r"<tool(?P<attrs>[^>]*)>(?P<body>.*?)</tool>", raw, re.S)
    if not match:
        return None
    attrs = parse_attrs(match.group("attrs"))
    name = str(attrs.pop("name", "")).strip()
    if not name:
        return None

    body = match.group("body")
    args = dict(attrs)
    for key in BODY_TAGS:
        if f"<{key}>" in body:
            args[key] = extract_raw(body, key)

    body_text = body.strip("\n")
    bare_target = _BARE_BODY_TOOLS.get(name)
    if bare_target and bare_target not in args and body_text:
        args[bare_target] = body_text.strip() if name == "delegate" else body_text
    return {"name": name, "args": args}


def parse_attrs(text: str) -> dict[str, str]:
    """从标签属性串里取出 ``name="value"`` 形式的键值对。

    只支持引号包裹的值，单双引号都可以；不支持无引号简写或转义，因为 Prompt 里的示例都是
    引号形式，接受更多写法只会让错误更难复现。
    """
    attrs: dict[str, str] = {}
    for match in re.finditer(r"""([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""", text):
        attrs[match.group(1)] = match.group(2) if match.group(2) is not None else match.group(3)
    return attrs


def extract(text: str, tag: str) -> str:
    """取出 ``<tag>...</tag>`` 之间的内容并去掉两端空白。

    缺少结束标签时取到文本结尾，缺少开始标签时原样返回——解析层尽量给出可用内容，真正的
    合法性判断交给后续的工具校验。
    """
    start_tag = f"<{tag}>"
    end_tag = f"</{tag}>"
    start = text.find(start_tag)
    if start == -1:
        return text
    start += len(start_tag)
    end = text.find(end_tag, start)
    if end == -1:
        return text[start:].strip()
    return text[start:end].strip()


def extract_raw(text: str, tag: str) -> str:
    """取出标签之间的内容但保留内部空白。

    文件正文与代码块的缩进是内容的一部分，这里不能顺手 strip。
    """
    start_tag = f"<{tag}>"
    end_tag = f"</{tag}>"
    start = text.find(start_tag)
    if start == -1:
        return text
    start += len(start_tag)
    end = text.find(end_tag, start)
    if end == -1:
        return text[start:]
    return text[start:end]

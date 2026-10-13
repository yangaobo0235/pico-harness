"""SSE（Server-Sent Events）响应体的文本抽取：把分片流还原成一次完整回答。

两个函数都吃「已经整段读完」的事件流文本：`extract_openai_text_from_sse` 只关心文本，
`extract_openai_response_from_sse` 额外带回最后一个可见的响应对象，让 client 能从中读 usage
与 cache 字段。它们接住 Responses API 的三种形态——增量 ``delta``、整段 ``done``、以及
直接携带完整 ``response`` 的终止事件，顺序敏感地取第一个可用结果。

这里不发起请求、也不处理 HTTP 头，是否走这条路径由 client 根据 ``Content-Type`` 判断。
``data:`` 之外的事件行、心跳空行与 ``[DONE]`` 都被跳过，JSON 解析失败的片段（典型的网络截断
半截）被忽略而不是报错，因此流被切断时上层拿到的是「已经收到的部分」而不是一次崩溃；
代价是半截答案看起来与完整答案同样可信，这一点由上层结合 stop 原因判断。client 走的是带响应
对象的 `extract_openai_response_from_sse`（元数据要从同一份响应里读），只要文本的调用方用
`extract_openai_text_from_sse`，两者对同一份输入的取舍顺序保持独立。
"""

import json
from collections.abc import Iterator
from typing import Any

from pico.integrations.llm.responses import extract_openai_text

#: Responses API 里逐字增量事件与整段完成事件的名字。
EVENT_OUTPUT_TEXT_DELTA = "response.output_text.delta"
EVENT_OUTPUT_TEXT_DONE = "response.output_text.done"
#: 终止事件：携带完整响应对象，usage 与 cache 字段只在这里才齐全。
EVENT_RESPONSE_COMPLETED = "response.completed"


def _iter_data_events(body_text: str) -> Iterator[Any]:
    """逐行取出 ``data:`` 载荷并解析成事件对象，跳过空行、哨兵与坏片段。

    两个抽取函数共用这条遍历规则：只认 ``data:`` 前缀（``event:`` 行与 ``:`` 注释自然被丢掉），
    载荷为空或 ``[DONE]`` 时结束当前行，``json.JSONDecodeError`` 直接 continue——半截分片不该
    让整次调用失败。解析结果不做类型筛选，因此合法但非字典的载荷会像原实现一样在
    后续取字段时报错，而不是被静默当成没有事件。
    """
    for raw_line in body_text.splitlines():
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def extract_openai_text_from_sse(body_text: str) -> str:
    """从事件流文本里取出模型文本，取不到时返回空串。

    每个事件按固定顺序尝试：先累加 ``response.output_text.delta`` 增量；
    ``response.output_text.done`` 的整段 ``text`` 立刻返回；随后依次看 ``part``、``item``、
    ``response`` 与事件本身，第一个能抽出非空文本的就作为结果。全部走完都没有整段文本时，
    优先返回增量拼接结果，其次返回最后一个 ``response`` 对象的抽取结果。
    空 body、只有 ``[DONE]``、或全是无法解析的分片都返回 ``""``，由调用方决定报错方式。
    """
    last_response: dict[str, Any] | None = None
    deltas: list[str] = []
    for event in _iter_data_events(body_text):
        event_type = event.get("type", "")
        if event_type == EVENT_OUTPUT_TEXT_DELTA:
            delta = event.get("delta")
            if isinstance(delta, str):
                deltas.append(delta)
            continue
        if event_type == EVENT_OUTPUT_TEXT_DONE:
            text = event.get("text")
            if isinstance(text, str) and text:
                return text
        part = event.get("part")
        if isinstance(part, dict):
            text = part.get("text")
            if isinstance(text, str) and text:
                return text
        item = event.get("item")
        if isinstance(item, dict):
            text = extract_openai_text({"output": [item]})
            if text:
                return text
        response = event.get("response")
        if isinstance(response, dict):
            last_response = response
            text = extract_openai_text(response)
            if text:
                return text
        text = extract_openai_text(event)
        if text:
            return text
    if deltas:
        return "".join(deltas)
    if isinstance(last_response, dict):
        return extract_openai_text(last_response)
    return ""


def extract_openai_response_from_sse(body_text: str) -> tuple[str, dict[str, Any]]:
    """抽取文本，并带回该文本所属的响应对象，返回 ``(text, response_data)``。

    与 `extract_openai_text_from_sse` 的差别只在「返回什么才算找到」：增量事件继续累加；
    ``response.completed`` 里的完整响应一旦有文本就整对返回，因为 usage 与 cache 字段只有
    终止事件才齐全；``response.output_text.done`` 返回文本加最近一次看到的响应对象
    （没有则是空字典）；其余事件若自身能抽出文本，就把事件信封当作响应对象返回。
    流结束时退回到「拼接增量」或「最后一个响应对象」，两者都没有时返回 ``("", {})``。
    第二个元素可能是 ``{}``，调用方必须按「没有元数据」处理而不是当成 0 token。
    """
    last_response: dict[str, Any] | None = None
    deltas: list[str] = []
    for event in _iter_data_events(body_text):
        response = event.get("response")
        if isinstance(response, dict):
            last_response = response
            if event.get("type") == EVENT_RESPONSE_COMPLETED:
                text = extract_openai_text(response)
                if text:
                    return text, response
        event_type = event.get("type", "")
        if event_type == EVENT_OUTPUT_TEXT_DELTA:
            delta = event.get("delta")
            if isinstance(delta, str):
                deltas.append(delta)
        elif event_type == EVENT_OUTPUT_TEXT_DONE:
            text = event.get("text")
            if isinstance(text, str) and text:
                return text, last_response or {}
        else:
            text = extract_openai_text(event)
            if text:
                return text, event
    if deltas:
        return "".join(deltas), last_response or {}
    if isinstance(last_response, dict):
        return extract_openai_text(last_response), last_response
    return "", {}

"""runtime 与模型后端之间的形状约定：什么才算一个可用的 `ModelClient`。

协议描述上层唯一依赖的能力面：`complete` 吃一段 prompt 与输出预算，返回模型文本；`model` 说明
当前跑的是哪个模型；`supports_prompt_cache` 说明这个后端能否接住稳定前缀缓存；
`last_completion_metadata` 记录上一次调用的 usage 与 cache 命中事实，供 trace 与 report 读取。
`pico.integrations.llm.providers` 下的四个 client 靠形状自然满足它，不需要显式继承。

这里只做类型标注，不发请求、不做注册表校验，也不在任何运行路径上被检查。刻意不加
``@runtime_checkable``：`FakeModelClient` 并没有 `model` 属性，``isinstance`` 的形状检查会给出
误导性的结论，而测试里的 duck-typed mock 即便通过检查也不代表语义正确。协议把缓存参数写成
``**kwargs`` 也是有意的——runtime 统一带上 ``prompt_cache_key`` 与 ``prompt_cache_retention``，
不支持缓存的后端直接忽略，这样新增一个可选参数不会变成跨层改动。
"""

from typing import Any, Protocol


class ModelClient(Protocol):
    """一次模型调用的最小契约：文本进、文本出，外加一份可选的缓存能力声明。

    属性 ``model`` 是后端模型名，``supports_prompt_cache`` 只有明确接上缓存语义的后端才为真，
    ``last_completion_metadata`` 是 ``complete()`` 每次重写的一次性字典：没有元数据时是空字典，
    读取方必须按「字段可能缺失」处理，不能假设 provider 一定回报 token 数。
    """

    model: str
    supports_prompt_cache: bool
    last_completion_metadata: dict[str, Any]

    def complete(self, prompt: str, max_new_tokens: int, **kwargs: Any) -> str:
        """把整段 prompt 交给后端，返回至多 ``max_new_tokens`` 的模型文本。

        ``prompt`` 是 runtime 已经渲染好的完整字符串，本层不再理解它的分段含义；
        ``max_new_tokens`` 是输出预算，由上层决定，后端不支持时会原样带进请求而不做本地裁剪。
        关键字参数按后端能力自取：OpenAI-compatible 路径读取 ``prompt_cache_key`` 与
        ``prompt_cache_retention``，其余后端显式丢弃。后端不可达、返回非 2xx 或返回体里没有
        文本时抛 `RuntimeError`，消息里带上足以定位的 HTTP 状态与响应片段；这里不吞异常，
        也不重试到无限次，因为重试预算属于具体 transport。
        """
        ...

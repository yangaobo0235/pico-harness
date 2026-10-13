"""脚本化输出的假模型：不发网络请求，把预先准备好的文本按顺序吐出来。

`FakeModelClient` 是测试、评测与离线演示使用的后端：构造时给一串文本，`complete` 每次返回
队首一条，并把收到的 prompt 追加进 `prompts`，让调用方能事后断言「模型这一轮到底看到了什么」。
它实现了 `pico.integrations.llm.contracts.ModelClient` 的形状，因此可以原样注入真实控制循环。

这里不模拟 token 计数、延时、SSE 或 HTTP 错误，也不判断输出是否符合协议格式：脚本没有第二条
文本时抛 `RuntimeError`，因为这通常意味着测试用例与期望轮数已经不一致，静默返回空文本只会
让失败原因跑到更远的断言里。真实后端属于同目录下的其他模块。
"""

from collections.abc import Iterable
from typing import Any


class FakeModelClient:
    """按预设脚本回答的模型客户端，用于把控制循环与网络隔开。

    ``outputs`` 接受任意可迭代文本，构造时立刻 ``list()`` 复制一份，因此传入生成器也不会
    在第一次调用后耗尽。``prompts`` 初始为空列表，每次调用追加一条，顺序即调用顺序。
    ``supports_prompt_cache`` 恒为 ``False``：假后端没有缓存语义可复用。
    """

    def __init__(self, outputs: Iterable[str]):
        self.outputs = list(outputs)
        self.prompts: list[str] = []
        self.supports_prompt_cache = False
        self.last_completion_metadata: dict[str, Any] = {}

    def complete(self, prompt: str, max_new_tokens: int, **kwargs: Any) -> str:
        """记录 ``prompt`` 并弹出队首文本；脚本耗尽时抛 ``fake model ran out of outputs``。

        ``max_new_tokens`` 与 ``**kwargs``（含 runtime 固定传来的 ``prompt_cache_key`` 与
        ``prompt_cache_retention``）一律忽略，这样测试替身不需要跟着上层参数一起改。
        输出不裁剪、不校验格式，``<final>`` 之类的协议标记由上层解析逻辑负责，
        假客户端只负责把它们原样送回，从而也能测到解析分支。
        """
        self.prompts.append(prompt)
        # 子类或测试可能把元数据置成 None/空字典（例如自定义的 cache-aware 替身），
        # 这里补回空字典；不复用 __init__ 里的赋值，否则会抹掉上一轮写入的元数据。
        if not getattr(self, "last_completion_metadata", None):
            self.last_completion_metadata = {}
        if not self.outputs:
            raise RuntimeError("fake model ran out of outputs")
        return self.outputs.pop(0)

"""模型后端：一个不发网络请求、按脚本说话的假客户端。

`FakeModelClient` 是教学实现的默认后端，也是它最重要的教学设计：控制循环需要的只是
`complete(prompt, max_new_tokens)` 这一个形状，因此把真实 Provider 换成脚本化文本之后，
同一套循环、同一套协议解析、同一份工件都能原样运行。它记录收到的每一段 Prompt
（`prompts`），读者可以直接断言“模型这一轮到底看到了什么”；构造时给一串 `outputs` 就按顺序吐，
不给则按 Prompt 里有没有工具结果走两条固定分支，于是零配置也能演示“调工具再收尾”的完整一轮。

这里不模拟 token 计数、延时、流式响应与 HTTP 错误，也不判断输出是否符合协议格式：脚本耗尽时抛
`RuntimeError`，因为这通常意味着用例和期望轮数已经不一致，静默返回空文本只会把失败推到更远的断言里。
主项目在同一个形状背后接的是 DeepSeek、OpenAI 兼容、Anthropic 兼容与 Ollama 四类真实端点
（`pico.integrations.llm.providers`），教学版刻意不联网：示例不应该需要凭证才能跑起来。
"""

from collections.abc import Iterable
from typing import Any


class FakeModelClient:
    """按预设脚本回答的模型客户端，把控制循环与网络隔开。

    ``outputs`` 为 ``None`` 时进入“自动演示”模式，按 Prompt 内容返回固定的工具调用或最终答案；
    传入可迭代对象时立刻复制成列表，因此给生成器也不会在第一次调用后耗尽。``prompts`` 每次调用
    追加一条，顺序即调用顺序。类属性 ``supports_prompt_cache`` 恒为 ``False``：假后端没有缓存语义
    可复用，上层因此不会为它准备 prompt cache key。
    """

    supports_prompt_cache = False

    def __init__(self, outputs: Iterable[str] | None = None) -> None:
        self.outputs = list(outputs) if outputs is not None else None
        self.prompts: list[str] = []
        self.last_completion_metadata: dict[str, Any] = {}

    def complete(self, prompt: str, max_new_tokens: int = 512, **_kwargs: Any) -> str:
        """记录 ``prompt`` 并返回本轮脚本文本。

        ``outputs`` 用尽时抛 ``fake model ran out of outputs``，让“用例比预期多跑了一轮”当场暴露。
        ``max_new_tokens`` 只被记进 `last_completion_metadata`（保留与主项目一致的形状，教学版的
        报告目前不读它），不裁剪输出；``**_kwargs`` 吸收上层将来可能多传的参数，这样测试替身不必
        跟着上层一起改。协议标记（``<tool>``、``<final>``）原样返回，分支由 `Pico.parse` 判定，
        假客户端因此也能测到解析逻辑。
        """
        self.prompts.append(prompt)
        self.last_completion_metadata = {"model": "FakeModelClient", "max_new_tokens": max_new_tokens}
        if self.outputs is not None:
            if not self.outputs:
                raise RuntimeError("fake model ran out of outputs")
            return self.outputs.pop(0)
        # 没给脚本时靠“Prompt 里是否已出现工具结果”决定下一步，让默认配置也能跑完一轮工具。
        if "Tool result:" in prompt:
            return "<final>mini-pico read the workspace through a tool and returned a final answer.</final>"
        return '<tool>{"name":"read_file","args":{"path":"README.md","start":1,"end":40}}</tool>'

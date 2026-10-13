"""可选运行时能力的默认开关。

Feature Flag 决定“这一轮 prompt 里允不允许出现某段内容”，不决定能力是否实现。四个默认值
对应 Pico 的四个可调支柱：工作记忆、相关记忆检索、上下文预算收缩和 prompt 缓存。评测脚本
通过临时改写这些开关做消融实验，因此这里只保存名称与默认值，不含任何读取逻辑。
"""

MEMORY = "memory"
RELEVANT_MEMORY = "relevant_memory"
CONTEXT_REDUCTION = "context_reduction"
PROMPT_CACHE = "prompt_cache"

FEATURE_NAMES = (MEMORY, RELEVANT_MEMORY, CONTEXT_REDUCTION, PROMPT_CACHE)

DEFAULT_FEATURE_FLAGS: dict[str, bool] = {
    MEMORY: True,
    RELEVANT_MEMORY: True,
    CONTEXT_REDUCTION: True,
    PROMPT_CACHE: True,
}

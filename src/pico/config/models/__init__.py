"""配置模型：运行参数、能力开关与 Provider 目录的可读定义。

子模块只描述“有哪些可调项、默认是什么”，不读取环境变量，也不创建任何运行对象。读取顺序属于
`pico.config.loader`，把值翻译成运行现场属于 `pico.bootstrap`。
"""

from pico.config.models.features import DEFAULT_FEATURE_FLAGS
from pico.config.models.runtime import APPROVAL_POLICIES, DEFAULT_MAX_STEPS

__all__ = [
    "APPROVAL_POLICIES",
    "DEFAULT_FEATURE_FLAGS",
    "DEFAULT_MAX_STEPS",
]

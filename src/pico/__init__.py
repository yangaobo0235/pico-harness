"""Pico 是一个跑在仓库里的轻量本地 coding agent。

它把一次模型调用扩展成一个能持续工作的控制循环：读取工作区事实、按预算组装上下文、执行一组
受约束的工具、把结果回灌给模型继续下一轮，并把会话、状态、Trace 与报告留在本地 ``.pico/`` 目录
里可复盘。Public 与 Internal Python namespace 都是 ``pico``。

这个包按职责分层：`contracts` 是跨层词汇，`runtime` 推进执行，`capabilities` 提供工具与记忆，
`integrations` 适配外部模型服务，`interfaces` 面向用户，`bootstrap` 负责装配，`security` 判断
边界，`observability` 记录事实，`shared` 放无业务依赖的基础件。跨层代码请从具体模块导入，
根包只保留最常用的入口，避免“什么都能从 pico 拿到”的假象。
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from pico.config.identity import PRODUCT_NAME

try:
    __version__ = _pkg_version("pico")
except PackageNotFoundError:
    # 源码树里直接运行时没有发行元数据，用一个可读的开发版本占位。
    __version__ = "0.0.0+unknown"

__all__ = [
    "PRODUCT_NAME",
    "__version__",
]

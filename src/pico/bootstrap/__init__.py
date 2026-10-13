"""装配层：把配置变成一台可运行的 Agent。

`container` 负责一次运行的完整装配，`providers` 负责按配置挑选模型客户端。装配层可以知道所有
具体实现——这正是它的职责；反过来，任何执行代码都不应该反过来导入这里，否则入口就无法替换。

这里不解析命令行参数，也不处理交互；工作区快照的采集属于 `pico.runtime.workspace`，会话与运行
工件的读写分别属于 `pico.runtime.sessions` 与 `pico.observability`。
"""

from pico.bootstrap.container import build_runtime, configured_secret_names
from pico.bootstrap.providers import build_model_client, resolve_provider

__all__ = [
    "build_model_client",
    "build_runtime",
    "configured_secret_names",
    "resolve_provider",
]

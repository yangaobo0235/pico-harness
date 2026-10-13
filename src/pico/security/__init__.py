"""安全职责组：工件脱敏与动作授权。

`redaction` 处理“写出去的东西不能带凭证”，`authorization` 处理“执行前必须先过边界”。两者都
只回答是或否、替换或保留，不持有会话、不记录事件，也不判断任务是否完成。

入口不重导出全部符号：需要脱敏或授权的具体函数时从子模块显式导入，这样调用处的依赖意图
在 import 行就能看出来。
"""

from pico.security.redaction import REDACTED_VALUE, redact_artifact, redact_text

__all__ = [
    "REDACTED_VALUE",
    "redact_artifact",
    "redact_text",
]

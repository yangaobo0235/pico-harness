"""会话职责组：对话历史的持久化与结构定义。

`models` 定义会话字典的必要字段与补齐规则，`service` 负责按 ID 存取。二者都不参与 Prompt
组装，也不判断一次恢复是否可信——恢复状态由 `pico.runtime.agent.checkpoints` 依据 runtime
身份与文件新鲜度决定。
"""

from pico.runtime.sessions.models import ensure_session_shape, new_session, new_session_id
from pico.runtime.sessions.service import SessionStore

__all__ = [
    "SessionStore",
    "ensure_session_shape",
    "new_session",
    "new_session_id",
]

"""会话记录的结构。

会话是“可恢复的工作现场”：一次 `Pico` 运行会把历史、工作记忆、checkpoint、runtime 身份与
恢复状态写进同一个字典。本模块定义这份结构并负责把它补齐，让旧版本落盘的 JSON 在新版本读入
后仍然形状完整。

这里不读写文件（那是 `pico.runtime.sessions.service`），也不解释历史内容的语义；恢复判断属于
`pico.runtime.agent.checkpoints`。
"""

from datetime import datetime
from typing import Any
from uuid import uuid4

CHECKPOINTS_KEY = "checkpoints"
HISTORY_KEY = "history"
MEMORY_KEY = "memory"
RESUME_STATE_KEY = "resume_state"
RUNTIME_IDENTITY_KEY = "runtime_identity"


def new_session_id(created_at: datetime | None = None) -> str:
    """生成 ``%Y%m%d-%H%M%S-<6 hex>`` 形式的会话 ID。

    时间前缀让会话文件按名字就能看出先后，随机后缀避免同一秒内两次启动互相覆盖。这不是全局
    唯一 ID，跨机器合并会话目录时仍可能同名。
    """
    moment = created_at or datetime.now()
    return moment.strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]


def new_session(workspace_root: str, session_id: str, created_at: str) -> dict[str, Any]:
    """构造一份空白会话，字段与 `ensure_session_shape` 的补齐结果一致。

    记忆状态由调用方传入的默认结构填充，本模块不导入记忆层，避免“结构定义”反过来依赖业务能力。
    """
    return {
        "id": session_id,
        "created_at": created_at,
        "workspace_root": workspace_root,
        HISTORY_KEY: [],
        MEMORY_KEY: {},
        CHECKPOINTS_KEY: {"current_id": "", "items": {}},
        RUNTIME_IDENTITY_KEY: {},
        RESUME_STATE_KEY: {},
    }


def ensure_session_shape(session: dict[str, Any]) -> dict[str, Any]:
    """就地补齐会话字典的必要字段。

    旧工件可能缺少 `checkpoints`、`runtime_identity` 或 `resume_state`，把类型不对的值当作
    “没有这个字段”处理并重置为可用的空结构，因此恢复一条旧会话不会在第一次写入时才抛
    `TypeError`。函数返回同一个字典对象，方便调用方链式使用。
    """
    session.setdefault(HISTORY_KEY, [])
    session.setdefault(MEMORY_KEY, {})
    checkpoints = session.setdefault(CHECKPOINTS_KEY, {})
    if not isinstance(checkpoints, dict):
        checkpoints = {}
        session[CHECKPOINTS_KEY] = checkpoints
    checkpoints.setdefault("current_id", "")
    checkpoints.setdefault("items", {})
    if not isinstance(session.get(RUNTIME_IDENTITY_KEY), dict):
        session[RUNTIME_IDENTITY_KEY] = {}
    if not isinstance(session.get(RESUME_STATE_KEY), dict):
        session[RESUME_STATE_KEY] = {}
    return session

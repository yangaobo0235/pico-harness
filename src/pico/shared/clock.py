"""统一的时间来源。

会话条目、checkpoint、Trace 事件和运行工件都带 `created_at` 字段。时间格式化集中在这里，
持久化记录才有可比对的同一套时间戳；单元测试通过替换模块级 ``now`` 固定时间。
"""

from datetime import datetime, timezone


def now() -> str:
    """以 UTC ISO-8601 字符串返回当前时刻。

    持久化格式使用字符串而不是 ``datetime``，避免 JSON 往返时丢失时区信息。字符串按
    ISO-8601 排序，因此 ``sort_keys=True`` 写出的事件仍然保持字典序稳定。
    """
    return datetime.now(timezone.utc).isoformat()

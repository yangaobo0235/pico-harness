"""Clock operations."""

from datetime import datetime


def timestamp() -> str:
    """返回当前 Local Time 的 ISO Timestamp。

    结果来自 `datetime.now().isoformat()`，不附加强制 UTC 规范。它适合人类可读的本地时间戳；需要
    跨时区证据时应使用带 Timezone 的专门调用，不能假设这里的字符串是 UTC。
    """
    return datetime.now().isoformat()

"""单进程视角下的稳定落盘原语。

Pico 的运行工件需要在“随时可能被中断”的前提下可读：``task_state.json`` 和 ``report.json``
必须整份有效，``trace.jsonl`` 允许最后一行不完整但绝不能与其他记录交织。本模块只提供
写入方式，不决定何时写入，也不知道工件的业务含义。

没有使用跨进程文件锁：一个 Pico 实例独占自己的运行目录，并发写入由上层避免。真正的
多进程写入需要 `pico.shared.locking` 级别的协调，这里刻意不假装具备该能力。
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pico.shared.paths import ensure_dir


def write_json_atomic(path: Path, payload: Any, *, indent: int = 2, sort_keys: bool = True) -> Path:
    """把 ``payload`` 序列化为缩进 JSON 并原子替换到 ``path``。

    先写同目录临时文件再 `os.replace`，因此读取者只会看到替换前后的两份完整内容之一，
    不会读到写了一半的文件；中途异常时旧文件保持不变。临时文件用 ``delete=False`` 创建后
    立即关闭命名句柄，避免 Windows 上目标文件仍被占用导致替换失败。
    """
    ensure_dir(path.parent)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=indent, sort_keys=sort_keys)
        handle.write("\n")
        temp_name = handle.name
    try:
        os.replace(temp_name, path)
    except BaseException:
        # 替换失败时清掉临时文件，运行目录不堆积半成品。
        Path(temp_name).unlink(missing_ok=True)
        raise
    return path


def append_json_line(path: Path, event: Any) -> Path:
    """以 JSON Lines 追加一条记录，键排序且不使用非 ASCII 转义。

    Trace 是流式事件序列，逐条落盘比最后一次性写整份文件更稳：进程被中断时已经发生的
    事件仍然可读。``ensure_ascii=True`` 让工件保持纯 ASCII，方便只读取字节窗口的调试工具
    在多字节字符中间截断时仍能得到合法 JSON 前缀。
    """
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, ensure_ascii=True))
        handle.write("\n")
    return path

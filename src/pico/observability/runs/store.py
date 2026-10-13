"""运行工件的落盘：``task_state.json``、``trace.jsonl`` 与 ``report.json``。

一次 `ask()` 对应一个运行目录，三个文件各自回答不同问题：task_state 是“现在到哪了”，trace 是
“这一轮做了什么”，report 是“这次的结果和关键指标”。把它们与可恢复的会话状态分开，恢复现场
和复盘证据才不会混在一起。

写入时机由 Agent 控制，本模块不判断事件顺序，也不做保留策略——工件不会自动清理，因为“上一次
实验的原始记录”正是排查依据。内容进入磁盘前已经脱敏，这里不再改写取值。
"""

import json
from pathlib import Path
from typing import Any

from pico.config.paths import REPORT_FILE_NAME, TASK_STATE_FILE_NAME, TRACE_FILE_NAME
from pico.contracts.turns import TaskState
from pico.shared.atomic_io import append_json_line, ensure_dir, write_json_atomic


class RunStore:
    """按 ``run_id`` 组织一次运行的审计工件。

    目录在 `start_run` 时建立，因此“请求已经开始”这件事本身也留下了证据。状态与报告使用原子
    替换写入，Trace 使用逐行追加：前者保证读到的永远是完整 JSON，后者保证进程被中断时已经
    发生的事件仍然可读。
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        ensure_dir(self.root)

    def run_dir(self, run_id: TaskState | str) -> Path:
        """返回一次运行的工件目录。

        ``run_id`` 允许直接传入 `TaskState`，因为调用点几乎都握着状态对象；这样就不会出现
        “用 task_id 拼目录、用 run_id 写文件”的两套路径。
        """
        return self.root / _run_id(run_id)

    def task_state_path(self, run_id: TaskState | str) -> Path:
        """返回 ``task_state.json`` 路径。"""
        return self.run_dir(run_id) / TASK_STATE_FILE_NAME

    def trace_path(self, run_id: TaskState | str) -> Path:
        """返回 ``trace.jsonl`` 路径。"""
        return self.run_dir(run_id) / TRACE_FILE_NAME

    def report_path(self, run_id: TaskState | str) -> Path:
        """返回 ``report.json`` 路径。"""
        return self.run_dir(run_id) / REPORT_FILE_NAME

    def start_run(self, task_state: TaskState) -> Path:
        """建立运行目录并立刻写出第一份状态。

        先落状态再开始迭代，因此即使第一次模型请求就失败，磁盘上也已经有这次运行的存在证据，
        复盘时能把“失败的运行”和“根本没跑”区分开。
        """
        run_dir = self.run_dir(task_state)
        ensure_dir(run_dir)
        self.write_task_state(task_state)
        return run_dir

    def write_task_state(self, task_state: TaskState) -> Path:
        """原子写入当前状态快照。

        一次运行会调用多次，这是有意的：状态文件始终反映最近一次已知进展，中断的调试也能
        拿到最后一刻的尝试次数与停止原因。
        """
        return write_json_atomic(self.task_state_path(task_state), task_state.to_dict())

    def append_trace(self, run_id: TaskState | str, event: dict[str, Any]) -> Path:
        """向 ``trace.jsonl`` 追加一条事件记录。

        单行 JSON、键排序、纯 ASCII，因此可以用普通文本工具按行 grep，也能在同一 ``run_id``
        内保持稳定的字节序，方便 diff 两次运行的事件差异。
        """
        return append_json_line(self.trace_path(run_id), event)

    def write_report(self, run_id: TaskState | str, report: dict[str, Any]) -> Path:
        """写出最终报告。"""
        return write_json_atomic(self.report_path(run_id), report)

    def load_task_state(self, task_id: TaskState | str) -> dict[str, Any]:
        """读回一次运行的状态文件。

        文件名使用 run 目录名，因此这里的 ``task_id`` 参数实际接受的是 run 标识或状态对象；
        历史实验脚本按 run 目录遍历，沿用了这一约定。
        """
        return _read_json(self.task_state_path(task_id))

    def load_report(self, task_id: TaskState | str) -> dict[str, Any]:
        """读回一次运行的报告文件。"""
        return _read_json(self.report_path(task_id))


def _run_id(value: TaskState | str) -> str:
    """从状态对象或字符串里取出 run 标识。"""
    if hasattr(value, "run_id"):
        return str(value.run_id)
    return str(value)


def _read_json(path: Path) -> dict[str, Any]:
    """读取一份 JSON 工件，文件缺失时让 `FileNotFoundError` 原样传播。"""
    return json.loads(path.read_text(encoding="utf-8"))

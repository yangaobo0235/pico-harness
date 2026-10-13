"""运行事实的两种存在形式：内存里的 `TaskState` 和磁盘上的 `RunStore`。

`TaskState` 回答“这次请求进行到哪了”——尝试次数、工具步数、最后一个工具、状态与停止原因，
一次 `ask()` 建立一份，由循环逐步改写；`to_dict()` 是它唯一的出口形状，落盘与报告都读这份字段
集合，所以字段名一旦稳定就不要再改。`RunStore` 负责把这三份工件写到 ``.mini-pico/runs/<run_id>/``：
``task_state.json`` 是进展快照，``trace.jsonl`` 是逐行追加的事件流，``report.json`` 是收尾摘要。
`now()` 提供统一的时间戳，历史条目和工件读到的时间是同一种写法。

这里不判断什么时候该停（属于 `mini_pico.agent_loop`），也不定义事件顺序（由调用点决定写入时机）。
主项目把这两个类拆成 `contracts.turns.TaskState` 与 `observability.runs.store.RunStore`，教学版
把它们放在同一模块，好让“状态”和“状态的落盘方式”一次读完。工件写的是普通 `write_text`，没有原子
替换，也不做保留策略与脱敏——一次实验的原始记录正是排查依据。
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def now() -> str:
    """返回 UTC 当前时间的 ISO 8601 字符串，作为历史条目唯一的时间写法。"""
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskState:
    """一次运行过程中的状态记录。

    它只保存事实：这次请求是谁、跑到第几步、尝试了多少次、最后为什么停下、最终答案是什么。
    ``status`` 与 ``stop_reason`` 分开保存，用来区分“停下时是什么状态”和“怎么停下的”；
    ``attempts`` 统计所有模型请求，``tool_steps`` 只统计真正执行过的工具，因此格式错误的输出
    不会吃掉工具预算。
    """

    run_id: str
    user_request: str
    status: str = "running"
    attempts: int = 0
    tool_steps: int = 0
    last_tool: str = ""
    stop_reason: str = ""
    final_answer: str = ""

    @classmethod
    def create(cls, user_request: str) -> "TaskState":
        """按用户请求建立一份运行中的状态，``run_id`` 现场生成。

        ID 以本地时间的秒级前缀开头再接短随机后缀：前缀让同一工作区里的运行目录可以按时间排序，
        后缀避免同一秒内的两次请求相互覆盖。它不保证全局唯一，只保证“同一个工作区里足够区分”。
        """
        run_id = "run_" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]
        return cls(run_id=run_id, user_request=str(user_request))

    def record_attempt(self) -> None:
        """一次模型请求发生，计入尝试次数。"""
        self.attempts += 1

    def record_tool(self, name: str) -> None:
        """一次工具执行发生，计入步数预算并记下工具名。"""
        self.tool_steps += 1
        self.last_tool = str(name)

    def finish_success(self, final_answer: str) -> None:
        """拿到最终答案，状态转为 `completed`。"""
        self.status = "completed"
        self.stop_reason = "final_answer_returned"
        self.final_answer = str(final_answer)

    def stop_step_limit(self, final_answer: str) -> None:
        """工具步数预算耗尽而停下，状态是 `stopped` 而不是失败。"""
        self.status = "stopped"
        self.stop_reason = "step_limit_reached"
        self.final_answer = str(final_answer)

    def stop_retry_limit(self, final_answer: str) -> None:
        """连续格式错误、请求次数上限耗尽而停下。"""
        self.status = "stopped"
        self.stop_reason = "retry_limit_reached"
        self.final_answer = str(final_answer)

    def to_dict(self) -> dict[str, Any]:
        """返回落盘与报告共用的字段字典。

        这里显式列出每个键而不是 `asdict(self)`，好让“工件里有什么”是一眼可见的约定：新增字段要
        同时改这里，读旧工件的人也能一眼看出这份记录属于哪个版本。
        """
        return {
            "run_id": self.run_id,
            "user_request": self.user_request,
            "status": self.status,
            "attempts": self.attempts,
            "tool_steps": self.tool_steps,
            "last_tool": self.last_tool,
            "stop_reason": self.stop_reason,
            "final_answer": self.final_answer,
        }


class RunStore:
    """按 ``run_id`` 组织一次运行的三份审计工件。

    目录在 `start_run` 时建立，因此“这次请求已经开始”本身也留下证据。构造时就会创建根目录，
    调用方不需要先做目录检查；三份工件分别对应运行中观察、逐轮复盘和收尾报告三个问题。
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, task_state: TaskState) -> Path:
        """返回一次运行的工件目录。

        入参接受 `TaskState` 而不是裸 ID，因为调用点几乎都握着状态对象，这样不会出现
        “用另一个字段拼目录”的第二套写法。
        """
        return self.root / task_state.run_id

    def start_run(self, task_state: TaskState) -> Path:
        """建立运行目录并立刻写出第一份状态。

        先落状态再开始迭代，因此即使第一次模型请求就失败，磁盘上也已经有这次运行存在的证据，
        复盘时能把“失败的运行”和“根本没跑”区分开。
        """
        run_dir = self.run_dir(task_state)
        run_dir.mkdir(parents=True, exist_ok=True)
        self.write_task_state(task_state)
        return run_dir

    def write_task_state(self, task_state: TaskState) -> Path:
        """写出当前状态快照，一次运行会覆盖多次。

        这是有意的：状态文件始终反映最近一次已知进展，被中断的调试也能拿到最后一刻的尝试次数
        与停止原因。
        """
        path = self.run_dir(task_state) / "task_state.json"
        path.write_text(json.dumps(task_state.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def append_trace(self, task_state: TaskState, event: dict[str, Any]) -> Path:
        """以 JSON Lines 追加一条事件。

        逐行追加而不是整份重写，进程被中断时已经发生的事件仍然可读；`sort_keys` 让同一事件的
        字段顺序稳定，两次运行可以直接 diff。
        """
        path = self.run_dir(task_state) / "trace.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=True, sort_keys=True))
            handle.write("\n")
        return path

    def write_report(self, task_state: TaskState, report: dict[str, Any]) -> Path:
        """写出收尾报告，只在一次运行结束时调用一次。"""
        path = self.run_dir(task_state) / "report.json"
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

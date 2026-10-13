"""一次请求从创建到终态的空间词汇。

`TaskState` 描述“这次用户请求进行到哪了”，`RunIdentity` 负责给每次运行和每个任务生成可排序
且互不重复的 ID。这里只保存事实与状态迁移，不写文件、不调度迭代，也不判断是否应当停止；
写出 ``task_state.json`` 的责任属于 `pico.observability.run_store`。
"""

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_STOPPED = "stopped"
STATUS_FAILED = "failed"

STOP_REASON_FINAL_ANSWER_RETURNED = "final_answer_returned"
STOP_REASON_STEP_LIMIT_REACHED = "step_limit_reached"
STOP_REASON_RETRY_LIMIT_REACHED = "retry_limit_reached"
STOP_REASON_MODEL_ERROR = "model_error"
STOP_REASON_TOOL_TIMEOUT = "tool_timeout"
STOP_REASON_APPROVAL_DENIED = "approval_denied"
STOP_REASON_DELEGATE_FAILED = "delegate_failed"
STOP_REASON_PERSISTENCE_ERROR = "persistence_error"
STOP_REASON_RESUME_LOAD_ERROR = "resume_load_error"

_PERSISTED_FIELDS = (
    "run_id",
    "task_id",
    "user_request",
    "status",
    "tool_steps",
    "attempts",
    "last_tool",
    "stop_reason",
    "final_answer",
    "checkpoint_id",
    "resume_status",
)


def _stamp(prefix: str) -> str:
    """生成带秒级时间与短随机后缀的 ID。

    时间前缀让同一轮产生的目录名可按时间排序，随机后缀避免同一秒内并发请求相互覆盖。
    这不是全局唯一 ID，只保证“同一 Workspace 下足够区分”，因此不引入分布式序号。
    """
    return prefix + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6]


@dataclass
class TaskState:
    """一次运行过程中的状态机快照。

    它回答的是：这次用户请求当前进行到哪了、调了多少次工具、最后为什么停下。对象会被不断
    写入 ``task_state.json``，供运行中观察和运行后复盘。`stop_reason` 与 `status` 分开保存，
    用于区分“怎么停的”和“停下时是什么状态”。
    """

    run_id: str
    task_id: str
    user_request: str
    status: str = STATUS_RUNNING
    tool_steps: int = 0
    attempts: int = 0
    last_tool: str = ""
    stop_reason: str = ""
    final_answer: str = ""
    checkpoint_id: str = ""
    resume_status: str = ""

    @classmethod
    def create(cls, task_id: str, user_request: str, run_id: str = "") -> "TaskState":
        """按用户请求建立初始状态，``run_id`` 缺省时现场生成。

        一次 `ask()` 对应一个 run；调用方传入 ``run_id`` 时用于把外部已经分配的运行标识带进
        状态对象，例如评测框架需要先把 run 目录登记给 Worker。
        """
        if not run_id:
            run_id = new_run_id()
        return cls(run_id=run_id, task_id=task_id, user_request=user_request)

    @classmethod
    def from_dict(cls, data: dict) -> "TaskState":
        """从 ``task_state.json`` 的字典还原状态。

        所有字段都带默认值，缺字段视为“尚未发生”而不是损坏记录，因此旧工件在字段增加后
        仍然可读。类型不匹配的数值字段会被强制转换，无法转换时抛出标准 ``ValueError``。
        """
        return cls(
            run_id=str(data.get("run_id", "")),
            task_id=str(data.get("task_id", "")),
            user_request=str(data.get("user_request", "")),
            status=str(data.get("status", STATUS_RUNNING)),
            tool_steps=int(data.get("tool_steps", 0)),
            attempts=int(data.get("attempts", 0)),
            last_tool=str(data.get("last_tool", "")),
            stop_reason=str(data.get("stop_reason", "")),
            final_answer=str(data.get("final_answer", "")),
            checkpoint_id=str(data.get("checkpoint_id", "")),
            resume_status=str(data.get("resume_status", "")),
        )

    def record_attempt(self) -> "TaskState":
        """把一次模型请求计入 `attempts`。

        attempt 统计的是“模型被调用了几轮”，不等于 `tool_steps`：解析失败的重试同样消耗
        attempt，但不会执行任何工具。
        """
        self.attempts += 1
        return self

    def record_tool(self, name: str) -> "TaskState":
        """把一次真正进入执行阶段的工具调用计入 `tool_steps`。"""
        self.tool_steps += 1
        self.last_tool = str(name or "")
        return self

    def stop(self, stop_reason: str, status: str = STATUS_STOPPED, final_answer: str = "") -> "TaskState":
        """写入停止原因与终态，可选地补上最后一份答案文本。

        ``final_answer`` 缺省表示“保留已经记录的答案”，与显式空串不同，因此调用方可以在
        已经生成过答案的状态上继续覆盖停止原因。
        """
        self.status = status
        self.stop_reason = stop_reason
        if final_answer != "":
            self.final_answer = final_answer
        return self

    def stop_step_limit(self, final_answer: str = "") -> "TaskState":
        """工具预算耗尽且没有产出最终答案。"""
        return self.stop(STOP_REASON_STEP_LIMIT_REACHED, final_answer=final_answer)

    def stop_retry_limit(self, final_answer: str = "") -> "TaskState":
        """模型连续返回无法解析的输出，达到重试上限。"""
        return self.stop(STOP_REASON_RETRY_LIMIT_REACHED, final_answer=final_answer)

    def stop_model_error(self, final_answer: str = "") -> "TaskState":
        """模型请求抛错，这是本次运行唯一的失败终态。"""
        return self.stop(STOP_REASON_MODEL_ERROR, status=STATUS_FAILED, final_answer=final_answer)

    def finish_success(self, final_answer: str) -> "TaskState":
        """记录 `<final>` 答案并完成本次运行。"""
        self.status = STATUS_COMPLETED
        self.stop_reason = STOP_REASON_FINAL_ANSWER_RETURNED
        self.final_answer = str(final_answer)
        return self

    def to_dict(self) -> dict:
        """按持久化字段顺序导出可 JSON 序列化的字典。

        字段集合固定，缺失值使用空字符串或 ``0``，因此 ``sort_keys=True`` 写出的工件在多次
        运行之间只差内容，不因字段增减而 diff 出噪声。
        """
        return {name: getattr(self, name) for name in _PERSISTED_FIELDS}


def new_run_id() -> str:
    """返回 ``run_`` 前缀的运行标识。"""
    return _stamp("run_")


def new_task_id() -> str:
    """返回 ``task_`` 前缀的任务标识。"""
    return _stamp("task_")

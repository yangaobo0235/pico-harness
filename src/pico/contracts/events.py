"""定义一次运行会对外的记录事件，以及每条记录的字段约定。

`TraceEvent` 只描述“事件名 + 载荷 + 时间戳”，写入 ``trace.jsonl`` 由
`pico.observability.run_store.RunStore` 负责，脱敏由 `pico.security.redaction` 负责。事件名集中在这里，
使 Agent 迭代、Checkpoint、评测与实验脚本对同一阶段使用同一个词，而不是各自拼写字符串。
"""

from dataclasses import dataclass, field
from typing import Any

RUN_STARTED = "run_started"
PROMPT_BUILT = "prompt_built"
MODEL_REQUESTED = "model_requested"
MODEL_PARSED = "model_parsed"
TOOL_EXECUTED = "tool_executed"
CHECKPOINT_CREATED = "checkpoint_created"
RUNTIME_IDENTITY_MISMATCH = "runtime_identity_mismatch"
MODEL_FAILED = "model_failed"
RUN_FINISHED = "run_finished"


@dataclass
class TraceEvent:
    """一条 Trace 记录：阶段名称、当次携带的指标、写入时间。

    ``payload`` 只放可 JSON 序列化的值；Agent 在写入前会整体脱敏，因此这里不保存模型客户端
    对象或工具返回值本体。字段解释属于各事件本身，本对象不判断事件顺序，也不保证同一
    ``run_id`` 内的事件数量。
    """

    name: str
    created_at: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """把事件摊平成 ``trace.jsonl`` 单行记录。

        ``event`` 与 ``created_at`` 是保留键，载荷同名时会由保留键覆盖，确保每行都能按事件名
        过滤，而不是被调用方传入的同名字段改写。
        """
        merged = dict(self.payload)
        merged["event"] = self.name
        merged["created_at"] = self.created_at
        return merged

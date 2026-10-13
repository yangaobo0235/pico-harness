"""Agent 执行职责组：模型与工具的迭代、现场记录与输出解析。

`agent` 是运行时门面，持有装配好的能力；`loop` 推进一次请求的迭代；`checkpoints` 记录并核对
可恢复现场；`prompts` 把模型文本解析成动作。四者共同构成“一次 ask()”的完整链路。

本层不解析命令行参数，不创建模型客户端，也不判断动作是否被允许；迭代需要的工具目录与会话
存储都由门面持有，拆出来的函数显式接收它，避免隐式全局状态。
"""

from pico.runtime.agent.agent import Pico
from pico.runtime.agent.loop import AgentLoop

__all__ = ["AgentLoop", "Pico"]

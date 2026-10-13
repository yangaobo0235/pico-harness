"""需要人类参与的工具交互。

审批提问属于这里，策略判断不属于这里：`pico.security.authorization.approval` 决定该不该问，
本包决定怎么问。提问实现保持可注入，测试和无人值守运行都不会真的读 stdin。
"""

from pico.capabilities.tools.interaction.approvals import confirm_approval

__all__ = ["confirm_approval"]

"""段落渲染结果的统一形状。

`SectionRender` 同时记录“原始文本、分配预算、渲染结果、该段特有的细节”，组装器据此产出
元数据，实验脚本据此解释一段内容是被裁短了还是被完整保留了。

这里没有任何业务判断：谁该被裁、裁到多少由 `pico.runtime.context.budget` 决定，具体裁剪
由 `pico.shared.text.tail_clip` 完成。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SectionRender:
    """一段 Prompt 内容从原始文本到渲染结果的对照。

    ``raw`` 是未经裁剪的完整文本，``budget`` 是本次分给它字符数（当前请求段用 ``0`` 表示
    “不受预算约束”），``rendered`` 是真正进入 Prompt 的文本，``details`` 放该段特有的观察项
    （例如折叠了几次重复读取、每条笔记分到多少预算）。
    """

    raw: str
    budget: int
    rendered: str
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def raw_chars(self) -> int:
        """原始文本长度。"""
        return len(self.raw)

    @property
    def rendered_chars(self) -> int:
        """渲染结果长度，永远不会大于原始长度。"""
        return len(self.rendered)

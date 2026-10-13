"""把内置工具定义装配成一次运行可见的工具目录。

工具不是动态发现的，而是显式注册的：注册表按当前上下文产出「名称 → 可执行条目」的字典，
模型看到的就是这份有边界、可审计的动作集合。委派工具只在深度还够用时才登记，因此子 Agent
的目录天然比父 Agent 小。

这里不执行工具，也不判断审批与参数之外的策略；执行边界属于 `pico.capabilities.tools.executor`。
Prompt 前缀和工具签名只读取条目里的 `schema`、`risky`、`description`，因此换掉实现不会让
缓存的 prefix 失效。
"""

from typing import Any

from pico.capabilities.tools.builtin import DELEGATE_TOOL_NAME, STANDARD_TOOL_NAMES, TOOL_DEFINITIONS, bind
from pico.capabilities.tools.contracts import ToolContext

#: 允许出现在 ``--allowed-tools`` 里的全部名称，包含按深度条件才会注册的委派工具。
ALL_TOOL_NAMES = tuple(TOOL_DEFINITIONS)


def legal_tool_names() -> tuple[str, ...]:
    """返回当前发行版本登记的合法工具名称。

    供启动期校验使用：配置里写了不存在的工具名应该立刻报错，而不是静默少一个工具，让模型
    的行为差异变成需要逐条对比 Trace 才能发现的问题。
    """
    return ALL_TOOL_NAMES


def build_tool_registry(context: ToolContext) -> dict[str, dict[str, Any]]:
    """按上下文装配本次运行的工具目录。

    普通工具总是注册；``delegate`` 只在 ``depth < max_depth`` 时注册，这样“子 Agent 再开子
    Agent”在定义层就被切断，而不是等到调用时才报深度错误。返回字典的插入顺序影响 Prompt
    前缀里的工具列表顺序，因此保持登记顺序稳定。
    """
    tools = {name: bind(name, context) for name in STANDARD_TOOL_NAMES}
    if context.depth < context.max_depth:
        tools[DELEGATE_TOOL_NAME] = bind(DELEGATE_TOOL_NAME, context)
    return tools


def tool_example(name: str) -> str:
    """返回某个工具的示例调用文本，未登记名称返回空字符串。

    示例只在参数校验失败时随错误一起回灌给模型，因为“格式写错”最常见的补救方式就是再看一次
    正确样例；未登记名称没有可展示的样例，也不该编造一个。
    """
    definition = TOOL_DEFINITIONS.get(name)
    return definition["example"] if definition else ""


def validate_tool(context: ToolContext, name: str, args: dict[str, Any] | None) -> None:
    """按名称分派到该工具自己的参数校验。

    ``args`` 为 ``None`` 时按空字典处理，让“模型给了工具名但没给参数”落到各工具自己的必填检查，
    而不是在校验层抛出一个没有信息量的类型错误。未登记名称不报错：调用它的执行器已经先返回
    ``unknown tool`` 结果，这里再报一次只会掩盖真正的失败原因。
    """
    definition = TOOL_DEFINITIONS.get(name)
    if definition is None:
        return
    definition["validate"](context, args or {})

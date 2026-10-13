"""交互式会话循环（REPL）。

REPL 把同一个 `Pico` 实例跨轮复用，因此会话历史与工作记忆在多次输入之间延续；内置命令在本地
处理，不消耗模型请求。它只负责读入、呈现和命令分派，任务的推进始终落在 `agent.ask()`。

标准输入结束（管道跑完、用户按 Ctrl-D）视为正常退出，返回码 ``0``；模型请求失败按 ``1`` 返回，
让脚本调用方能感知。这里不重试，也不吞掉异常文本——用户需要看见原始失败原因。
"""

import sys

from pico.interfaces.cli.rendering.styles import HELP_DETAILS

PROMPT_PREFIX = "\npico> "
EXIT_COMMANDS = ("/exit", "/quit")
HELP_COMMAND = "/help"
MEMORY_COMMAND = "/memory"
SESSION_COMMAND = "/session"
RESET_COMMAND = "/reset"


def run_repl(agent) -> int:
    """进入交互循环直到用户退出或输入结束。

    空输入直接跳过，方便连续回车；``/reset`` 之后打印一条确认文本，因为“历史确实被清空了”
    这种状态变化如果静默发生，用户只能靠下一次回答是否失忆来推断。
    """
    while True:
        try:
            user_input = input(PROMPT_PREFIX).strip()
        except (EOFError, KeyboardInterrupt):
            print("")
            return 0

        if not user_input:
            continue
        if user_input in EXIT_COMMANDS:
            return 0
        if user_input == HELP_COMMAND:
            print(HELP_DETAILS)
            continue
        if user_input == MEMORY_COMMAND:
            print(agent.memory_text())
            continue
        if user_input == SESSION_COMMAND:
            print(agent.session_path)
            continue
        if user_input == RESET_COMMAND:
            agent.reset()
            print("session reset")
            continue

        print()
        try:
            print(agent.ask(user_input))
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)

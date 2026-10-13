"""命令行入口：参数解析、装配一个运行时、选择单次执行还是进入 REPL。

`main` 是 `mini-pico` 命令与 `python -m mini_pico` 的共同入口：解析参数、装配运行时、把位置参数
拼成一次性 Prompt 执行，或者在没有输入时进入一个只认 `/exit`、`/quit` 的最小 REPL。
`build_arg_parser` 是参数面，`build_agent` 把参数翻译成运行对象。帮助文本里写明默认值，因为审批
策略与步数预算会实质影响一次运行的行为，使用者要在按下回车前就看到它们。

它不实现任何 agent 语义：循环、上下文、工具与工件都来自 `mini_pico.runtime` 装配出来的对象。
命令行不接受任何凭证参数，也不需要——默认后端是 `FakeModelClient`，不联网。主项目的
`interfaces.cli` 在这里多了会话恢复、渲染、斜杠命令与首屏信息，教学版只保留“把一次请求接起来”
这条最小路径，返回值作为进程退出码。
"""

import argparse

from mini_pico.providers import FakeModelClient
from mini_pico.runtime import Pico
from mini_pico.state import RunStore
from mini_pico.workspace import Workspace


def build_arg_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。

    位置参数 `prompt` 可留空，留空即进入 REPL；`--approval` 只认 `auto` 与 `never` 两个取值，
    教学实现没有交互式审批这条路径。默认值与 `Pico` 构造参数的默认值保持一致，
    这样“不传参数”在 CLI 与 API 两条入口下得到同一次运行。
    """
    parser = argparse.ArgumentParser(description="Teaching-sized Pico agent harness.")
    parser.add_argument("prompt", nargs="*", help="One-shot prompt. If omitted, mini-pico starts a small REPL.")
    parser.add_argument("--cwd", default=".", help="Workspace directory.")
    parser.add_argument(
        "--approval", choices=("auto", "never"), default="auto", help="Whether risky tools are allowed."
    )
    parser.add_argument("--max-steps", type=int, default=4, help="Maximum tool/model iterations.")
    parser.add_argument("--max-new-tokens", type=int, default=512, help="Maximum model output tokens per step.")
    return parser


def build_agent(args: argparse.Namespace) -> Pico:
    """按解析好的参数装配一个运行时，工作区工件写在 ``<cwd>/.mini-pico/runs``。

    运行工件目录落在被操作的工作区里而不是当前进程目录，因为“这次运行的证据”属于那棵被读的树。
    模型客户端固定是 `FakeModelClient`，装配点因此也是唯一需要替换成真实 Provider 的位置。
    """
    workspace = Workspace.build(args.cwd)
    run_store = RunStore(workspace.root / ".mini-pico" / "runs")
    return Pico(
        model_client=FakeModelClient(),
        workspace=workspace,
        run_store=run_store,
        approval_policy=args.approval,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
    )


def main(argv: list[str] | None = None) -> int:
    """解析参数并执行一次请求或进入 REPL，返回进程退出码。

    ``argv`` 为 ``None`` 时读取 `sys.argv`，因此测试可以直接传列表驱动同一个函数。有位置参数就单次
    执行并返回 0；空输入在 REPL 里被跳过，`EOF` 与 Ctrl-C 都算正常结束。单次请求不因预算耗尽而
    返回非零——兜底文本已经说明了原因，退出码只表示“这次进程正常结束”。
    """
    args = build_arg_parser().parse_args(argv)
    agent = build_agent(args)
    prompt = " ".join(args.prompt).strip()
    if prompt:
        print(agent.ask(prompt))
        return 0

    while True:
        try:
            user_input = input("mini-pico> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("")
            return 0
        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            return 0
        print(agent.ask(user_input))

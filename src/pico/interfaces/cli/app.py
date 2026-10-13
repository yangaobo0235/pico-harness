"""命令行入口：参数解析、装配与运行方式分派。

`main` 是发行包里 `pico` 命令的入口：解析参数、装配一个运行时、打印首屏，然后按用户给的输入
选择单次执行还是进入交互循环。它不实现任何 agent 语义——所有能力都来自 `pico.bootstrap` 装配
出来的对象。

参数帮助文本里写默认值，因为审批策略、步数预算与 provider 选择都会实质影响一次运行的行为，
用户需要在使用前就看到它们。真实凭证只从环境变量与 `.env` 读取，命令行不接受 key。
"""

import argparse
import sys

from pico.bootstrap.container import build_runtime
from pico.bootstrap.providers import resolve_provider
from pico.config.models.runtime import (
    APPROVAL_ASK,
    APPROVAL_POLICIES,
    DEFAULT_MAX_NEW_TOKENS,
    DEFAULT_MAX_STEPS,
    DEFAULT_REQUEST_TIMEOUT_S,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
)
from pico.config.providers import DEFAULT_PROVIDER, PROVIDER_CHOICES, PROVIDER_OLLAMA, provider_profile
from pico.interfaces.cli.rendering.styles import build_welcome
from pico.interfaces.cli.repl import run_repl


def build_arg_parser() -> argparse.ArgumentParser:
    """构造命令行参数解析器。

    使用 `ArgumentDefaultsHelpFormatter`，让每个开关的默认值直接出现在 ``--help`` 里；provider
    与审批策略限制为枚举取值，非法值在解析阶段就失败，而不是等到装配时才报一个内部错误。
    """
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        description="Minimal coding agent for DeepSeek, OpenAI-compatible, Anthropic-compatible, or Ollama models.",
    )
    parser.add_argument("prompt", nargs="*", help="Optional one-shot prompt.")
    parser.add_argument("--cwd", default=".", help="Workspace directory.")
    parser.add_argument(
        "--provider",
        choices=PROVIDER_CHOICES,
        default=None,
        help=f"Model backend to use. Defaults to PICO_PROVIDER or {DEFAULT_PROVIDER}.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model name override. Defaults to the provider-specific PICO_*_MODEL variable.",
    )
    parser.add_argument("--host", default=None, help="Ollama server URL.")
    parser.add_argument("--base-url", default=None, help="Provider API base URL for deepseek, openai, or anthropic.")
    parser.add_argument(
        "--ollama-timeout", type=int, default=DEFAULT_REQUEST_TIMEOUT_S, help="Ollama request timeout in seconds."
    )
    parser.add_argument(
        "--openai-timeout",
        type=int,
        default=DEFAULT_REQUEST_TIMEOUT_S,
        help="OpenAI-compatible request timeout in seconds.",
    )
    parser.add_argument("--resume", default=None, help="Session id to resume or 'latest'.")
    parser.add_argument("--approval", choices=APPROVAL_POLICIES, default=None, help="Approval policy for risky tools.")
    parser.add_argument(
        "--secret-env-name",
        dest="secret_env_names",
        action="append",
        default=[],
        help="Extra environment variable names to treat as secrets for trace/report redaction.",
    )
    parser.add_argument(
        "--max-steps", type=int, default=DEFAULT_MAX_STEPS, help="Maximum tool/model iterations per request."
    )
    parser.add_argument(
        "--max-new-tokens", type=int, default=DEFAULT_MAX_NEW_TOKENS, help="Maximum model output tokens per step."
    )
    parser.add_argument(
        "--temperature", type=float, default=DEFAULT_TEMPERATURE, help="Sampling temperature sent to the model."
    )
    parser.add_argument("--top-p", type=float, default=DEFAULT_TOP_P, help="Top-p sampling value sent to Ollama.")
    return parser


def resolve_display_target(agent, args: argparse.Namespace) -> tuple[str, str]:
    """决定首屏上显示的模型名与服务地址。

    优先展示模型客户端真正使用的值，其次回落到命令行参数与 provider 默认值。这里不访问网络，
    也不校验地址是否可达——首屏只负责报告“这次配置用的是什么”，连接结果由第一次请求给出。
    """
    profile = provider_profile(args.provider or DEFAULT_PROVIDER)
    model = str(getattr(agent.model_client, "model", "") or args.model or profile.default_model)
    host = str(
        getattr(agent.model_client, "host", None)
        or getattr(agent.model_client, "base_url", None)
        or args.host
        or profile.default_base_url
    )
    return model, host


def run_once(agent, prompt: str) -> int:
    """执行一次请求并打印结果。

    模型请求失败时把异常文本写到标准错误并返回 ``1``：单次调用常常出现在脚本里，返回码比一段
    打印在 stdout 里的错误更容易被上层判断。
    """
    print()
    try:
        print(agent.ask(prompt))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """命令行主入口。"""
    args = build_arg_parser().parse_args(argv)
    agent = build_runtime(
        cwd=args.cwd,
        resume=args.resume,
        approval_policy=args.approval or APPROVAL_ASK,
        max_steps=args.max_steps,
        max_new_tokens=args.max_new_tokens,
        secret_env_names=args.secret_env_names,
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        host=args.host,
        temperature=args.temperature,
        top_p=args.top_p,
        timeout=args.ollama_timeout if resolve_provider(args.provider).name == PROVIDER_OLLAMA else args.openai_timeout,
    )

    model, host = resolve_display_target(agent, args)
    print(build_welcome(agent, model=model, host=host))

    if args.prompt:
        prompt = " ".join(args.prompt).strip()
        if prompt:
            return run_once(agent, prompt)
        return 0

    return run_repl(agent)

"""真实模型后端的对照实验：同一份固定 benchmark 在不同 provider 上各跑一遍。

`_provider_profile` 把项目 `.env` 与进程环境读成一份「这个后端现在能不能用」的结论（``ready`` 带
模型、Base URL 与凭证，``blocked`` 带一句缺什么），`_make_provider_client` 据此构造对应协议的 client，
`run_provider_experiments` 则对 ``gpt`` / ``claude`` / ``deepseek`` 逐个跑 `run_fixed_benchmark`，用
`_provider_summary_from_artifact` 把工件摊成可对比的通过率、平均步数与缓存命中率。
`_normalize_text` 是这套对照里唯一的小工具：把答案去掉两端空白、转小写并剪掉尾部标点，让
「同一句话有没有带句号」不至于影响正确率判定。

边界与有意取舍：这里的环境变量回退顺序与默认 Base URL 属于实验口径，刻意不复用
`pico.config.providers` 的目录——例如 ``gpt`` 在本层默认落到 ``https://api.openai.com/v1``，而产品配置
落到共享网关，两者不同是历史事实，改写就会让新旧工件对不上。这些函数会真的发出付费请求，因此只由带
``real_llm`` marker 的实验或显式的脚本入口调用，默认回归不触发；provider 缺凭证时按 ``blocked`` 记录
而不是抛错，好让「哪一档没配」本身成为一条可读的结论。
"""

from pathlib import Path
from typing import Any

from pico.config.loader import load_project_env, provider_env
from pico.extensions.evaluation.metrics.aggregates import _safe_mean, _safe_ratio
from pico.integrations.llm.providers.anthropic_compat import AnthropicCompatibleModelClient
from pico.integrations.llm.providers.openai_compat import OpenAICompatibleModelClient


def _provider_summary_from_artifact(payload: dict[str, Any]) -> dict[str, Any]:
    """把一份 benchmark 工件压成 provider 对照用的字段。"""
    rows = list(payload.get("rows", []))
    cached_tokens: list[int] = []
    cache_hits: list[bool] = []
    tool_steps: list[int] = []
    attempts: list[int] = []
    for row in rows:
        report = row.get("report", {})
        prompt_metadata = report.get("prompt_metadata", {})
        cached_tokens.append(int(prompt_metadata.get("cached_tokens", 0) or 0))
        cache_hits.append(bool(prompt_metadata.get("cache_hit")))
        tool_steps.append(int(row.get("tool_steps", 0)))
        attempts.append(int(row.get("attempts", 0)))
    summary = payload.get("summary", {})
    return {
        "status": "completed",
        "task_count": int(summary.get("total_tasks", len(rows))),
        "pass_rate": float(summary.get("pass_rate", 0.0)),
        "avg_tool_steps": _safe_mean(tool_steps),
        "avg_attempts": _safe_mean(attempts),
        "cache_hit_rate": _safe_ratio(sum(1 for hit in cache_hits if hit), len(cache_hits)),
        "avg_cached_tokens": _safe_mean(cached_tokens),
        # 工件路径由调用方在 payload 里补记（``_artifact_path``），缺失时留空串而不是猜一个。
        "artifact_path": payload.get("_artifact_path", ""),
    }


def _provider_profile(provider: str) -> dict[str, Any]:
    """先加载项目 `.env`，再按 provider 名称读出凭证、模型与 Base URL。

    ``provider`` 取 ``gpt`` / ``deepseek``，其余值都落到 ``claude`` 分支——沿用历史调用方式，因此
    未知名称也会按 claude 的变量集尝试，而不是抛错。三项配置都按「``PICO_*`` 优先，其后旧命名与共享
    网关 key，最后代码默认值」的顺序解析；任何一档取不到 key 时返回
    ``{"provider": ..., "status": "blocked", "reason": ...}``，把缺什么写在 ``reason`` 里。

    先 `load_project_env(Path.cwd())` 再读环境变量是这条路径的既定顺序：仓库里的 `.env` 应当覆盖
    shell 里残留的旧值，否则同一份配置在两个终端下会给出不同结论。这里不校验凭证是否有效，也不发
    探测请求——是否真的能用只有第一次完整请求才知道。
    """
    load_project_env(Path.cwd())
    if provider == "gpt":
        api_key = provider_env(
            "PICO_OPENAI_API_KEY",
            (
                "OPENAI_API_KEY",
                "PICO_RIGHT_CODES_API_KEY",
                "RIGHT_CODES_API_KEY",
                "PICO_ANTHROPIC_API_KEY",
                "ANTHROPIC_API_KEY",
            ),
        )
        if not api_key:
            return {
                "provider": provider,
                "status": "blocked",
                "reason": "PICO_OPENAI_API_KEY, OPENAI_API_KEY, or shared right.codes key missing",
            }
        return {
            "provider": provider,
            "status": "ready",
            "model": provider_env("PICO_OPENAI_MODEL", ("OPENAI_MODEL",), "gpt-5.4"),
            "base_url": provider_env("PICO_OPENAI_API_BASE", ("OPENAI_API_BASE",), "https://api.openai.com/v1"),
            "api_key": api_key,
        }
    if provider == "deepseek":
        api_key = provider_env("PICO_DEEPSEEK_API_KEY", ("DEEPSEEK_API_KEY",))
        if not api_key:
            return {
                "provider": provider,
                "status": "blocked",
                "reason": "PICO_DEEPSEEK_API_KEY or DEEPSEEK_API_KEY missing",
            }
        return {
            "provider": provider,
            "status": "ready",
            "model": provider_env("PICO_DEEPSEEK_MODEL", ("DEEPSEEK_MODEL",), "deepseek-v4-pro"),
            "base_url": provider_env(
                "PICO_DEEPSEEK_API_BASE", ("DEEPSEEK_API_BASE",), "https://api.deepseek.com/anthropic"
            ),
            "api_key": api_key,
        }
    api_key = provider_env(
        "PICO_ANTHROPIC_API_KEY",
        (
            "ANTHROPIC_API_KEY",
            "PICO_RIGHT_CODES_API_KEY",
            "RIGHT_CODES_API_KEY",
            "PICO_OPENAI_API_KEY",
            "OPENAI_API_KEY",
        ),
    )
    if not api_key:
        return {
            "provider": "claude",
            "status": "blocked",
            "reason": "PICO_ANTHROPIC_API_KEY or ANTHROPIC_API_KEY missing",
        }
    return {
        "provider": "claude",
        "status": "ready",
        "model": provider_env("PICO_ANTHROPIC_MODEL", ("ANTHROPIC_MODEL",), "claude-sonnet-4-6"),
        "base_url": provider_env(
            "PICO_ANTHROPIC_API_BASE", ("ANTHROPIC_API_BASE",), "https://www.right.codes/claude/v1"
        ),
        "api_key": api_key,
    }


def _make_provider_client(provider: str) -> Any:
    """按 profile 构造一个可用的模型 client；配置不齐时抛出带原因的 `RuntimeError`。

    ``provider`` 同 `_provider_profile` 的取值。温度固定 ``0.0`` 保证可复现，超时固定 60 秒：这条构造
    路径服务的是单次真实请求（`_build_real_agent`），而整轮 benchmark 要跑很多步，所以
    `run_provider_experiments` 另外构造 300 秒超时的 client。``gpt`` 走 OpenAI 兼容协议，其余走
    Anthropic 兼容协议，缺凭证时抛的 `RuntimeError` 直接用 profile 里的 ``reason``，让调用方不必再猜。
    """
    profile = _provider_profile(provider)
    if profile["status"] != "ready":
        raise RuntimeError(profile["reason"])
    timeout = 60
    if provider == "gpt":
        return OpenAICompatibleModelClient(
            model=profile["model"],
            base_url=profile["base_url"],
            api_key=profile["api_key"],
            temperature=0.0,
            timeout=timeout,
        )
    return AnthropicCompatibleModelClient(
        model=profile["model"],
        base_url=profile["base_url"],
        api_key=profile["api_key"],
        temperature=0.0,
        timeout=timeout,
    )


def _normalize_text(value: object) -> str:
    """把一段答案压成小写、去掉两端空白，并反复剪掉尾部的 ``.!?\"'``。

    循环而不是单次裁剪，因为「答案后面跟了多个标点或标点加空白」是同一种情况；只剪尾部，正文里的
    标点保留，否则带引号的行就被改坏了。
    """
    text = str(value).strip().lower()
    while text.endswith((".", "!", "?", '"', "'")):
        text = text[:-1].strip()
    return text


def run_provider_experiments(
    benchmark_path: str | Path,
    workspace_root: str | Path,
    artifact_root: str | Path,
    max_new_tokens: int = 64,
) -> dict[str, list[dict[str, Any]]]:
    """对三个 provider 各跑一遍固定 benchmark，返回 ``{"providers": [...]}``。

    ``benchmark_path`` 是任务定义 JSON，``workspace_root`` 是实验根目录（每个 provider 实际落在它下面
    的同名子目录，互不干扰），``artifact_root`` 决定 ``<provider>-benchmark.json`` 的存放位置，
    ``max_new_tokens`` 默认 64。返回的列表按 ``gpt``、``claude``、``deepseek`` 固定顺序，每项要么是
    ``blocked``（缺配置，没有跑），要么是 ``completed``（`_provider_summary_from_artifact` 的字段加上
    ``provider`` 与 ``model`` 归因），要么是 ``error``（跑了但失败，``reason`` 是异常文本）。

    重复运行会覆盖同一个 ``<provider>-benchmark.json`` 工件，因此对比时以最后一次为准。三个 provider
    全部失败也返回结构完整的字典，不提前退出——「这轮谁都没跑成」正是需要被记录下来的结论。
    凭证齐不齐在这里只做静态判断，不做真实探测请求，是否可用只有跑完 benchmark 才知道。
    """
    from pico.extensions.evaluation.engine import run_fixed_benchmark

    benchmark_path = Path(benchmark_path)
    workspace_root = Path(workspace_root)
    artifact_root = Path(artifact_root)
    providers: list[dict[str, Any]] = []
    for provider_name in ("gpt", "claude", "deepseek"):
        profile = _provider_profile(provider_name)
        if profile["status"] != "ready":
            providers.append(profile)
            continue
        if provider_name == "gpt":

            def factory(task: Any, workspace: Any, profile: dict[str, Any] = profile) -> Any:
                del task, workspace
                return OpenAICompatibleModelClient(
                    model=profile["model"],
                    base_url=profile["base_url"],
                    api_key=profile["api_key"],
                    temperature=0.0,
                    timeout=300,
                )
        else:

            def factory(task: Any, workspace: Any, profile: dict[str, Any] = profile) -> Any:
                del task, workspace
                return AnthropicCompatibleModelClient(
                    model=profile["model"],
                    base_url=profile["base_url"],
                    api_key=profile["api_key"],
                    temperature=0.0,
                    timeout=300,
                )

        artifact_path = artifact_root / f"{provider_name}-benchmark.json"
        try:
            payload = run_fixed_benchmark(
                benchmark_path=benchmark_path,
                artifact_path=artifact_path,
                workspace_root=workspace_root / provider_name,
                # 归因字段来自 profile：provider 名进 model_name，具体型号进 model_version，
                # 工件路径由调用方补写进 payload 再被摘要读取。
                model_name=profile["provider"],
                model_version=profile["model"],
                max_new_tokens=max_new_tokens,
                model_client_factory=factory,
            )
            payload["_artifact_path"] = str(artifact_path)
            result = _provider_summary_from_artifact(payload)
            result["provider"] = provider_name
            result["model"] = profile["model"]
            providers.append(result)
        except Exception as exc:
            # 单个后端失败只让这一档变成 error 记录：整轮对照的价值在于「其他两档仍然可比」。
            providers.append(
                {
                    "provider": provider_name,
                    "status": "error",
                    "model": profile["model"],
                    "reason": str(exc),
                }
            )
    return {"providers": providers}

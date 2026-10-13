"""把凭证从对外工件里摘掉。

Pico 会把 Prompt 元数据、工具参数和异常文本写进 Trace 与 Report；这些工件的价值在于可复盘，
风险在于顺手把环境变量里的 key 带出去。本模块按“变量名像凭证”和“调用方显式声明”两条线索
识别敏感值，并在写入前替换成固定占位符。

覆盖范围是环境变量值，不承诺识别出现在配置文件、命令输出或模型回答里的其他密钥形态；
需要额外名称时使用 `PICO_SECRET_ENV_NAMES` 或 CLI 的 ``--secret-env-name`` 补充。
"""

import os
from typing import Any

SENSITIVE_ENV_NAME_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
REDACTED_VALUE = "<redacted>"


def _normalized_secret_names(secret_env_names: Any) -> set[str]:
    """把调用方传入的变量名集合规范化成大写集合。

    环境变量名大小写不敏感地使用，名单也按大写比较，避免 ``pico_openai_api_key`` 这样
    写进 `.env` 的名字漏掉脱敏。
    """
    return {str(name).upper() for name in (secret_env_names or ())}


def looks_sensitive_env_name(name: str) -> bool:
    """按名称判断环境变量是否像凭证。

    等于标记、以标记结尾、或以 ``_`` 加标记结尾都算命中，因此 ``OPENAI_API_KEY`` 与
    ``GITHUB_TOKEN`` 都能识别。这是命名启发式：``DATABASE_URL`` 这类名称像配置但值里可能
    带密码的变量不会被判定为敏感。
    """
    upper = str(name).upper()
    return any(
        upper == marker or upper.endswith(marker) or upper.endswith(f"_{marker}")
        for marker in SENSITIVE_ENV_NAME_MARKERS
    )


def is_secret_env_name(name: str, secret_env_names: Any = None) -> bool:
    """综合“显式名单”和“命名启发式”判断某个变量名是否需要脱敏。"""
    upper = str(name).upper()
    return upper in _normalized_secret_names(secret_env_names) or looks_sensitive_env_name(upper)


def configured_secret_env_items(
    env: dict[str, str] | None = None, secret_env_names: Any = None
) -> list[tuple[str, str]]:
    """只返回显式名单里、且当前有值的环境变量条目。

    用于回答“用户声明要保护的变量确实配上了吗”，与自动识别结果不同，这里不受命名启发式影响。
    空值跳过，结果按变量名排序，便于写入工件后做稳定 diff。
    """
    env = os.environ if env is None else env
    configured_names = _normalized_secret_names(secret_env_names)
    items = [(name, value) for name, value in env.items() if str(name).upper() in configured_names and value]
    items.sort(key=lambda item: item[0])
    return items


def detected_secret_env_items(env: dict[str, str] | None = None, secret_env_names: Any = None) -> list[tuple[str, str]]:
    """返回“名单命中或名称像凭证、且有值”的全部环境变量。"""
    env = os.environ if env is None else env
    items = [
        (name, value)
        for name, value in env.items()
        if is_secret_env_name(name, secret_env_names=secret_env_names) and value
    ]
    items.sort(key=lambda item: item[0])
    return items


def secret_env_summary(env: dict[str, str] | None = None, secret_env_names: Any = None) -> dict[str, Any]:
    """汇总显式声明的敏感变量数量与名称，只输出名称不输出值。"""
    names = [name for name, _ in configured_secret_env_items(env=env, secret_env_names=secret_env_names)]
    return {
        "secret_env_count": len(names),
        "secret_env_names": names,
    }


def detected_secret_env_summary(env: dict[str, str] | None = None, secret_env_names: Any = None) -> dict[str, Any]:
    """汇总自动识别到的敏感变量数量与名称，随 Prompt 元数据一起写入工件。

    复盘时用它解释“为什么某个字段变成了 `<redacted>`”；识别为名称启发式，因此这里列出的
    变量并不一定真的出现在工件内容里。
    """
    names = [name for name, _ in detected_secret_env_items(env=env, secret_env_names=secret_env_names)]
    return {
        "secret_env_count": len(names),
        "secret_env_names": names,
    }


def redact_text(text: object, env: dict[str, str] | None = None, secret_env_names: Any = None) -> str:
    """把环境里检测到的敏感值从 ``text`` 中替换为占位符。

    按值长度从长到短替换，避免短 token 先把长 key 的前缀吃掉而留下残段。替换是纯字面匹配，
    不认识 base64 变体或大小写差异；``text`` 非字符串时先转字符串，保证调用方可以直接传入
    异常对象转出的文本。
    """
    value = str(text)
    for _, secret in sorted(
        detected_secret_env_items(env=env, secret_env_names=secret_env_names),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        value = value.replace(secret, REDACTED_VALUE)
    return value


def redact_artifact(
    value: Any, key: str | None = None, env: dict[str, str] | None = None, secret_env_names: Any = None
) -> Any:
    """递归脱敏一件工件：按字段名整段替换，按字段值做文本替换。

    ``key`` 命中敏感命名时整个值替换为占位符，用于 ``{"api_key": "..."}`` 这种结构；字典、
    列表与元组继续下钻，元组会降级成列表，因为 JSON 往返本来也不区分两者。返回结构与输入
    保持同形，调用方仍可安全序列化。
    """
    if key and is_secret_env_name(key, secret_env_names=secret_env_names):
        return REDACTED_VALUE
    if isinstance(value, dict):
        return {
            str(item_key): redact_artifact(item_value, key=item_key, env=env, secret_env_names=secret_env_names)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_artifact(item, key=key, env=env, secret_env_names=secret_env_names) for item in value]
    if isinstance(value, tuple):
        return [redact_artifact(item, key=key, env=env, secret_env_names=secret_env_names) for item in value]
    if isinstance(value, str):
        return redact_text(value, env=env, secret_env_names=secret_env_names)
    return value

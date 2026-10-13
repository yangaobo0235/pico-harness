"""读取项目级 `.env` 并按优先级解析配置值。

配置优先级固定为：显式 CLI 参数 > 项目 `.env` 里的 `PICO_*` 变量 > 旧环境变量 > 代码默认值。
本模块只做这件事，不构造 Provider、不解释模型名称，也不校验凭证是否可用；凭证是否够用属于
外部服务，只有真正发起请求时才知道。

`.env` 在构建 provider client 之前加载，并覆盖当前进程里的同名环境变量，这样“仓库里配置的
Pico”和“用户 shell 里残留的旧值”之间不会出现谁赢得不确定的情况。值按字面量读取，不做 shell
变量展开：``KEY=$OTHER`` 会原样成为 ``$OTHER``。
"""

import os
import re
from pathlib import Path

ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_quotes(value: str) -> str:
    """去掉成对的首尾引号，其余字符原样保留。

    只识别单引号与双引号，且不处理转义；需要字面反斜杠的 Base URL 因此可以安全加引号，
    而无法表达引号本身。
    """
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_env_line(line: str) -> tuple[str, str] | None:
    """解析一行 `.env`，注释与空行返回 ``None``。

    允许 ``export NAME=value`` 写法，方便直接从 shell 脚本粘贴。``=`` 缺失或变量名不合法都按
    配置错误抛出 `ValueError`，因为静默跳过会让“key 没生效”这类问题很难定位。值中等号保留，
    只按第一个 ``=`` 切分。
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[len("export ") :].strip()
    if "=" not in line:
        raise ValueError(f"invalid .env line: {line}")
    name, value = line.split("=", 1)
    name = name.strip()
    if not ENV_KEY_PATTERN.match(name):
        raise ValueError(f"invalid .env variable name: {name}")
    return name, _strip_quotes(value)


def find_project_env(start: str | Path) -> Path | None:
    """从 ``start`` 向上查找第一个存在的 `.env`。

    传入文件时先取父目录，因此从任意脚本路径启动都能命中同一份项目配置。查找止于文件系统
    根，找不到返回 ``None``，调用方按“没有项目级配置”继续。
    """
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for path in (current, *current.parents):
        env_path = path / ".env"
        if env_path.exists():
            return env_path
    return None


def load_project_env(start: str | Path, override: bool = True) -> dict[str, str]:
    """加载项目 `.env` 到进程环境，返回本次读到的键值。

    ``override=True``（默认）时 `.env` 覆盖同名环境变量，让仓库配置成为权威来源；设为 ``False``
    则只填充尚未设置的变量，用于“外部编排已经给定值”的场景。返回的字典包含文件中全部有效
    条目，即使某些条目因为 ``override=False`` 没有写入环境。
    """
    env_path = find_project_env(start)
    if env_path is None:
        return {}
    loaded: dict[str, str] = {}
    for line in env_path.read_text(encoding="utf-8").splitlines():
        parsed = _parse_env_line(line)
        if parsed is None:
            continue
        name, value = parsed
        loaded[name] = value
        if override or name not in os.environ:
            os.environ[name] = value
    return loaded


def provider_env(name: str, legacy_names: tuple[str, ...] = (), default: str = "") -> str:
    """按 ``name`` → ``legacy_names`` → ``default`` 的顺序取第一个非空值。

    保留旧变量名是为了让历史 `.env` 不必一次改完；空字符串视为“没有配置”，因此显式写空值
    等于回退到下一项，而不是把空凭证传给 Provider。
    """
    for env_name in (name, *legacy_names):
        value = os.environ.get(env_name)
        if value:
            return value
    return default

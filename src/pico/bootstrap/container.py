"""装配一次运行的现场。

`build_runtime` 是「启动参数」到「可请求的 Agent」之间唯一的装配点：采集工作区快照、加载项目
配置、整理脱敏名单、创建模型客户端、决定新建还是恢复会话，最后把这些交给 `Pico`。装配之后的
对象不再关心参数来自命令行、测试还是评测脚本。

这里不解析命令行，也不输出任何内容；入口层负责把用户输入翻译成参数，展示层负责呈现结果。
"""

import os
from pathlib import Path
from typing import Any

from pico.bootstrap.providers import build_model_client
from pico.config.loader import load_project_env
from pico.config.models.runtime import (
    APPROVAL_ASK,
    DEFAULT_MAX_NEW_TOKENS,
    DEFAULT_MAX_STEPS,
    DEFAULT_REQUEST_TIMEOUT_S,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOP_P,
)
from pico.config.paths import WorkspacePaths
from pico.config.providers import DEFAULT_SECRET_ENV_NAMES, SECRET_ENV_NAMES_VAR
from pico.runtime.agent.agent import Pico
from pico.runtime.sessions.service import SessionStore
from pico.runtime.workspace.snapshot import WorkspaceContext


def configured_secret_names(extra: Any = None) -> list[str]:
    """合并默认脱敏名单、显式追加项与 `PICO_SECRET_ENV_NAMES` 里的逗号分隔列表。

    全部转成大写并去重排序：脱敏比较不区分大小写，稳定的输出顺序让 Trace 与报告在做 diff 时
    不会因为名单顺序变化而产生噪声。默认名单里已经覆盖常见 provider 变量，追加项用于用户自己
    引入的凭证名称。
    """
    names = set(DEFAULT_SECRET_ENV_NAMES)
    names.update(str(item).upper() for item in (extra or ()))
    additional = os.environ.get(SECRET_ENV_NAMES_VAR, "")
    if additional.strip():
        names.update(item.strip().upper() for item in additional.split(",") if item.strip())
    return sorted(names)


def build_runtime(
    *,
    cwd: Path | str = ".",
    resume: str | None = None,
    approval_policy: str = APPROVAL_ASK,
    max_steps: int = DEFAULT_MAX_STEPS,
    max_new_tokens: int = DEFAULT_MAX_NEW_TOKENS,
    secret_env_names: Any = None,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    host: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    top_p: float = DEFAULT_TOP_P,
    timeout: int = DEFAULT_REQUEST_TIMEOUT_S,
) -> Pico:
    """装配出一个可用的 `Pico` 实例。

    顺序是有意的：先确定仓库根，再按仓库根加载 `.env`，这样项目配置可以覆盖进程里残留的旧
    变量；模型客户端在配置加载之后创建，凭证才可能来自刚刚读入的文件。

    ``resume`` 接受会话 ID 或字面量 ``latest``（取最近修改的会话）。恢复路径不重新采集工作区
    之外的状态：会话里的历史与记忆原样带入，恢复是否可信由运行时在构造阶段核对。
    未指定 provider 时按配置优先级解析，默认走 DeepSeek。
    """
    workspace = WorkspaceContext.build(cwd)
    load_project_env(workspace.repo_root)
    paths = WorkspacePaths(Path(workspace.repo_root))
    store = SessionStore(paths.sessions_dir)

    common: dict[str, Any] = {
        "model_client": build_model_client(
            provider=provider,
            model=model,
            base_url=base_url,
            host=host,
            temperature=temperature,
            top_p=top_p,
            timeout=timeout,
        ),
        "workspace": workspace,
        "session_store": store,
        "approval_policy": approval_policy,
        "max_steps": max_steps,
        "max_new_tokens": max_new_tokens,
        "secret_env_names": configured_secret_names(secret_env_names),
    }
    if resume == "latest":
        resume = store.latest()
    if resume:
        return Pico.from_session(session_id=resume, **common)
    return Pico(**common)

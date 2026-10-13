"""配置层的稳定入口。

外部只需要三件事：加载项目 `.env`（`load_project_env`、`provider_env`）、按名称取 Provider
配置（`provider_profile`）、解析 Workspace 状态路径（`WorkspacePaths`）。运行参数的默认值与
能力开关从 `pico.config.models` 子模块显式导入，避免把整份配置表塞进包级命名空间。

本层不创建 Provider、不装配 Agent，也不读取任何运行工件。
"""

from pico.config.loader import load_project_env, provider_env
from pico.config.paths import WorkspacePaths
from pico.config.providers import provider_profile

__all__ = [
    "WorkspacePaths",
    "load_project_env",
    "provider_env",
    "provider_profile",
]

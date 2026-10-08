"""Workspace operations."""

from pathlib import Path


def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
    """把 Bundled Templates 同步到 Workspace，只创建 Missing Files。

    流程先把 Legacy Memory/Profile Files 一次性迁移到 L4 Layout，再为仍缺失的支柱文件写入包内模板
    或空文件，最后确保 ``skills`` 目录存在。已有 Destination 永不覆盖，因此用户直接修改的 L4 内容
    优先。返回本次 Added Relative Paths；`silent=False` 时同时在 Stderr 打印 Created Items。

    模板资源不可用时返回空列表。成功返回只说明文件布局准备完成，不验证其中的 Agent Persona、
    Memory 或 Skills 内容是否有效。
    """
    from importlib.resources import files as pkg_files

    try:
        tpl = pkg_files("pico") / "resources" / "templates"
    except Exception:
        return []
    if not tpl.is_dir():
        return []

    added: list[str] = []

    def _write(src, dest: Path):
        if dest.exists():
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8") if src else "", encoding="utf-8")
        added.append(str(dest.relative_to(workspace)))

    def _migrate(src: Path, dest: Path):
        """把 Legacy Content One-shot Copy 到 L4 Path。

        Source Missing 或 Destination 已存在时 No-op，因此每次 Workspace Sync 重跑都安全，且绝不
        覆盖已经迁移或由用户创建的新文件。读取先采用 Binary，再用 UTF-8 ``errors="replace"`` 解码，
        使 Non-UTF-8 Windows Code Page 写出的 Legacy Files 也能迁移而不崩溃；不可解码字节会以替换
        字符保留证据，而不是静默丢弃整份内容。
        """
        if not src.is_file() or dest.exists():
            return
        try:
            text = src.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8")
        added.append(f"{dest.relative_to(workspace)} (migrated from {src.relative_to(workspace)})")

    # 第一步：把旧版工作区文件迁移到 L4 布局。只有旧文件存在且 L4 目标
    # 尚不存在时规则才生效，因此用户直接对 L4 路径所做的修改优先。
    _migrate(workspace / "memory" / "MEMORY.md", workspace / "user_memory" / "profile" / "user.md")
    _migrate(workspace / "memory" / "HISTORY.md", workspace / "user_memory" / "episodic" / "episodes.md")
    _migrate(workspace / "SOUL.md", workspace / "agent_memory" / "profile" / "soul.md")
    _migrate(workspace / "AGENTS.md", workspace / "agent_memory" / "profile" / "agent.md")
    _migrate(workspace / "USER.md", workspace / "user_memory" / "profile" / "user.md")
    # 第二步：其余缺失文件回退到内置模板。先处理 L4 支柱文件；
    # TOOLS.md 仍保留在工作区根目录。
    _write(tpl / "SOUL.md", workspace / "agent_memory" / "profile" / "soul.md")
    _write(tpl / "AGENTS.md", workspace / "agent_memory" / "profile" / "agent.md")
    _write(tpl / "USER.md", workspace / "user_memory" / "profile" / "user.md")
    _write(None, workspace / "user_memory" / "episodic" / "episodes.md")
    # 程序性记忆文件在旧版布局中没有对应来源。
    _write(None, workspace / "agent_memory" / "procedural" / "skills.md")
    _write(None, workspace / "agent_memory" / "procedural" / "case.md")
    _write(tpl / "TOOLS.md", workspace / "TOOLS.md")
    (workspace / "skills").mkdir(exist_ok=True)

    if added and not silent:
        from rich.console import Console

        _c = Console(stderr=True)
        for name in added:
            _c.print(f"  [dim]Created {name}[/dim]")
    return added

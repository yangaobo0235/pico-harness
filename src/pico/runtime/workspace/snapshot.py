"""Workspace 快照：在 agent 按需读文件之前先给它一份便宜的仓库第一印象。

`WorkspaceContext` 汇集 Git 事实（分支、默认分支、工作区状态、最近提交）与少量白名单项目文档，
`fingerprint` 把这些压成一个哈希，用来判断“世界是否变了到需要重建 Prompt 前缀”。这份快照刻意
保持小而稳定：不遍历源码树，不做语言识别，也不建立文件索引。

它不负责安全边界（路径能否越界属于 `pico.security`），也不负责把内容拼进 Prompt（那是
`pico.runtime.context`）。Git 不可用或不在仓库内时全部退回占位值，让 agent 仍能在普通目录里工作。
"""

import hashlib
import json
import subprocess
import textwrap
from pathlib import Path
from typing import Any

from pico.config.models.runtime import IGNORED_PATH_NAMES, PROJECT_DOC_NAMES
from pico.shared.text import clip

#: 单份项目文档进入快照的字符上限。
DOC_SNIPPET_LIMIT = 1200
#: 工作区状态文本上限。
STATUS_LIMIT = 1500
#: 最近提交条数。
RECENT_COMMIT_COUNT = 5
#: 单次 Git 调用的超时秒数；快照在启动路径上，不能因为仓库锁或大仓挂死。
GIT_TIMEOUT_S = 5


def _run_git(args: list[str], fallback: str = "", cwd: Path | None = None) -> str:
    """执行一次 Git 命令，失败时返回 ``fallback``。

    任何异常（无 Git、不在仓库、超时、权限）都按“这项事实缺失”处理而不是向上抛，因为缺信息
    只让 Prompt 少一段，让 CLI 启动失败则完全不可用。标准输出为空时也使用 fallback，避免
    下游拿到空字符串却以为“命令成功且确实没有内容”。
    """
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=GIT_TIMEOUT_S,
        )
        return result.stdout.strip() or fallback
    except Exception:
        return fallback


def _strip_remote_prefix(branch: str) -> str:
    """把 ``origin/main`` 这类远端引用还原成分支名。"""
    return branch[len("origin/") :] if branch.startswith("origin/") else branch


class WorkspaceContext:
    """一次构建得到的仓库事实集合，附带可比较的指纹。

    ``repo_root`` 是文件工具的锚点，``cwd`` 只影响相对路径的阅读体验；两者在子目录启动时故意
    不同。``project_docs`` 以相对 repo_root 的路径为 key，因此同一份文档在 repo_root 和 cwd
    都可见时只收集一次。对象本身是不可变使用约定，不阻止调用方修改字段，指纹只在需要时重算。
    """

    def __init__(
        self,
        cwd: str,
        repo_root: str,
        branch: str,
        default_branch: str,
        status: str,
        recent_commits: list[str],
        project_docs: dict[str, str],
    ):
        self.cwd = cwd
        self.repo_root = repo_root
        self.branch = branch
        self.default_branch = default_branch
        self.status = status
        self.recent_commits = recent_commits
        self.project_docs = project_docs

    @classmethod
    def build(cls, cwd: Path | str, repo_root_override: Path | str | None = None) -> "WorkspaceContext":
        """从 ``cwd`` 出发采集 Git 事实与项目文档。

        ``repo_root_override`` 用于测试与被挂载的目录：给出时不再询问 `git rev-parse`，仓库根
        直接采用该值。文档同时扫描 repo_root 与 cwd，所以在仓库子目录启动时也能读到本地 README，
        越靠近当前目录的副本先命中。
        """
        current = Path(cwd).resolve()

        repo_root = (
            Path(repo_root_override).resolve()
            if repo_root_override is not None
            else Path(_run_git(["rev-parse", "--show-toplevel"], str(current), cwd=current)).resolve()
        )
        docs: dict[str, str] = {}
        for base in (repo_root, current):
            for name in PROJECT_DOC_NAMES:
                path = base / name
                if not path.exists():
                    continue
                key = str(path.relative_to(repo_root))
                if key in docs:
                    continue
                docs[key] = clip(_read_text(path), DOC_SNIPPET_LIMIT)

        return cls(
            cwd=str(current),
            repo_root=str(repo_root),
            branch=_run_git(["branch", "--show-current"], "-", cwd=current) or "-",
            default_branch=_default_branch(current),
            status=clip(_run_git(["status", "--short"], "clean", cwd=current) or "clean", STATUS_LIMIT),
            recent_commits=[
                line
                for line in _run_git(["log", "--oneline", f"-{RECENT_COMMIT_COUNT}"], cwd=current).splitlines()
                if line
            ],
            project_docs=docs,
        )

    def text(self) -> str:
        """渲染成进入 Prompt 前缀的文本块。

        字段顺序稳定，空集合显式写成 ``- none``，让模型读到“确实没有”而不是“没提到”。
        文本长度不受额外预算控制，超限时由上下文层的 `prefix` 预算统一裁剪。
        """
        commits = "\n".join(f"- {line}" for line in self.recent_commits) or "- none"
        docs = "\n".join(f"- {path}\n{snippet}" for path, snippet in self.project_docs.items()) or "- none"
        return textwrap.dedent(
            f"""\
            Workspace:
            - cwd: {self.cwd}
            - repo_root: {self.repo_root}
            - branch: {self.branch}
            - default_branch: {self.default_branch}
            - status:
            {self.status}
            - recent_commits:
            {commits}
            - project_docs:
            {docs}
            """
        ).strip()

    def fingerprint(self) -> str:
        """返回快照内容的 SHA-256，用于判断是否需要重建 Prompt 前缀。

        指纹覆盖全部字段并按 key 排序序列化，因此字典插入顺序变化不会造成误判，而分支、状态
        或任一文档片段变化都会得到不同值。它是“变了没有”的信号，不用于跨机器校验同一仓库。
        """
        payload: dict[str, Any] = {
            "cwd": self.cwd,
            "repo_root": self.repo_root,
            "branch": self.branch,
            "default_branch": self.default_branch,
            "status": self.status,
            "recent_commits": list(self.recent_commits),
            "project_docs": dict(self.project_docs),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _read_text(path: Path) -> str:
    """按 UTF-8 读取文档，无法解码的字节替换而不是报错。"""
    return path.read_text(encoding="utf-8", errors="replace")


def _default_branch(cwd: Path) -> str:
    """读出远端默认分支名，去掉 ``origin/`` 前缀。

    ``symbolic-ref`` 在浅克隆或从未 fetch 过的仓库里会失败，此时退回 ``main`` 这个最常见取值，
    而不是让快照缺少这一项。
    """
    branch = _run_git(["symbolic-ref", "--short", "refs/remotes/origin/HEAD"], "origin/main", cwd=cwd) or "origin/main"
    return _strip_remote_prefix(branch)


def is_ignored(relative_parts: tuple[str, ...]) -> bool:
    """判断一段相对路径中是否出现需要整段跳过的目录名。"""
    return any(part in IGNORED_PATH_NAMES for part in relative_parts)

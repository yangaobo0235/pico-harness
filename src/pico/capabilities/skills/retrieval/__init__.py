"""Local Skill Retrieval、Fusion、Gate 与 Rendering Machinery。

初级读者可把 Skill 理解为可按当前请求检索并注入 Prompt 的局部操作说明。Active Runtime 先由
`LocalSkillCatalog` 读取文件，再通过 `LocalSkillSource` Search，`SkillForgeRouter` 可重写 Query、融合
多路排名、运行 LLM Gate，最后由 Resolver 展开引用并形成可注入内容。

:class:`SkillSource` Protocol 是 Host-internal，而不是 Plugin Contribution Point。当前 Runtime 只在
:class:`LocalSkillSource` 上构建 Router；Generic Router 与 Fusion Helpers 仍用于 Deterministic
Evaluation。检索 Hit、Gate 通过、Skill 注入和任务成功是四个不同阶段。
"""

from __future__ import annotations

from pico.capabilities.skills.retrieval.catalog import LocalSkillCatalog
from pico.capabilities.skills.retrieval.fusion import RRF_K, rrf_merge_weighted
from pico.capabilities.skills.retrieval.gate import LLMGateFilter
from pico.capabilities.skills.retrieval.local_source import LocalSkillSource
from pico.capabilities.skills.retrieval.refs import resolve_refs
from pico.capabilities.skills.retrieval.resolver import LocalSkillResolver, SkillResolution
from pico.capabilities.skills.retrieval.rewriter import QueryRewriter, RewriteResult
from pico.capabilities.skills.retrieval.router import SkillForgeRouter
from pico.capabilities.skills.retrieval.types import RouterHit, SkillSource

__all__ = [
    "LLMGateFilter",
    "LocalSkillCatalog",
    "LocalSkillSource",
    "LocalSkillResolver",
    "QueryRewriter",
    "RRF_K",
    "RewriteResult",
    "RouterHit",
    "SkillForgeRouter",
    "SkillResolution",
    "SkillSource",
    "resolve_refs",
    "rrf_merge_weighted",
]

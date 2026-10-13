"""把状态字典与一个 Workspace 绑在一起的门面。

`LayeredMemory` 是 runtime 唯一需要认识的记忆对象：构造时规范化一次，`set_task_summary`、
`remember_file`、`append_note`、`set_file_summary` 等方法把 `state` 层的纯函数以自己的
``workspace_root`` 调用一遍，结果存回 ``self.state``，多数方法返回 ``self`` 以支持链式写法。
`retrieval_candidates`、`retrieval_view` 与 `render_memory_text` 是读取转发，`promote_durable`
则顺带刷新磁盘上的主题清单。

这一层不决定「什么时候该记」、也不判断哪条笔记值得晋升，那是 runtime 与模型的事；它只保证
所有调用都带上同一个根目录，因此调用方不需要在每个参数上重复传 ``workspace_root``。
``workspace_root`` 为 ``None`` 时 `durable_store` 也是 ``None``，所有长期记忆读写安静降级为
不做事，工作记忆本身仍然完整可用。
"""

from pathlib import Path
from typing import Any, Iterable

from pico.capabilities.memory.contracts import MEMORY_KIND_EPISODIC
from pico.capabilities.memory.durable import DurableMemoryStore
from pico.capabilities.memory.state import (
    append_note,
    invalidate_file_summary,
    invalidate_stale_file_summaries,
    normalize_memory_state,
    remember_file,
    render_memory_text,
    retrieval_candidates,
    retrieval_view,
    set_file_summary,
    set_task_summary,
)
from pico.capabilities.memory.workspace_paths import canonicalize_path


class LayeredMemory:
    """绑定单个 Workspace 的记忆门面，内部保存一份规范化过的状态字典。

    ``state`` 可以是 `None` 或任何来自磁盘的旧结构，构造时会被规范化；``workspace_root`` 决定
    相对路径怎么拼、摘要指纹怎么算、长期记忆落在哪里。实例不是线程安全的：所有写入都会原地
    替换 ``self.state``，同一份状态应由单条控制循环持有。
    """

    def __init__(self, state: dict[str, Any] | None = None, workspace_root: str | Path | None = None) -> None:
        """以 ``state`` 起步并绑定 ``workspace_root``。

        构造只做一次规范化（顺带读一遍主题清单填充 `durable_topics`），不创建任何目录；
        首次 `promote_durable` 才会真正建立 ``.pico/memory``。
        """
        self.workspace_root = workspace_root
        self.state = normalize_memory_state(state, workspace_root)
        self.durable_store = DurableMemoryStore.for_workspace(workspace_root)

    def to_dict(self) -> dict[str, Any]:
        """规范化并返回内部状态字典本身，供序列化使用。

        返回的是同一个对象而不是副本：调用方若要边改边留快照，需要自己 `deepcopy`。这样做的
        代价是外部持有者能看见后续写入，好处是持久化路径上少一次大字典复制。
        """
        self.state = normalize_memory_state(self.state, self.workspace_root)
        return self.state

    def canonical_path(self, path: object) -> str:
        """用本实例的根目录规范化一条路径，写法与状态里保存的一致。"""
        return canonicalize_path(path, self.workspace_root)

    def set_task_summary(self, summary: object) -> "LayeredMemory":
        """写入当前任务摘要，返回自身以便链式调用。"""
        self.state = set_task_summary(self.state, summary, self.workspace_root)
        return self

    def remember_file(self, path: object) -> "LayeredMemory":
        """把 ``path`` 移到「最近接触」的末尾，返回自身。"""
        self.state = remember_file(self.state, path, self.workspace_root)
        return self

    def append_note(
        self,
        text: object,
        tags: Iterable[object] = (),
        source: str = "",
        created_at: str | None = None,
        kind: str = MEMORY_KIND_EPISODIC,
    ) -> "LayeredMemory":
        """追加一条笔记；正文为空时状态不变，仍然返回自身。

        参数含义与 `state.append_note` 相同，只是不必再传 ``workspace_root``。
        """
        self.state = append_note(
            self.state,
            text,
            tags=tags,
            source=source,
            created_at=created_at,
            workspace_root=self.workspace_root,
            kind=kind,
        )
        return self

    def set_file_summary(self, path: object, summary: object) -> "LayeredMemory":
        """为某个文件写下短摘要与内容指纹，返回自身。"""
        self.state = set_file_summary(self.state, path, summary, self.workspace_root)
        return self

    def invalidate_file_summary(self, path: object) -> "LayeredMemory":
        """显式删掉某个文件的摘要，路径没有记录时不做任何事。"""
        self.state = invalidate_file_summary(self.state, path, self.workspace_root)
        return self

    def invalidate_stale_file_summaries(self) -> list[str]:
        """清除内容已变过的文件摘要，返回被清掉的路径列表。

        返回值只用于日志与 trace；状态已在原地更新，调用方不需要再写回。
        """
        self.state, invalidated = invalidate_stale_file_summaries(self.state, self.workspace_root)
        return invalidated

    def retrieval_candidates(self, query: object, limit: int = 3) -> list[dict[str, Any]]:
        """按 ``query`` 召回工作笔记与磁盘主题的笔记条目。"""
        return retrieval_candidates(self.state, query, limit=limit, workspace_root=self.workspace_root)

    def retrieval_view(self, query: object, limit: int = 3) -> str:
        """渲染 ``Relevant memory:`` 文本，没有命中时返回带 ``- none`` 的标题行。"""
        return retrieval_view(self.state, query, limit=limit, workspace_root=self.workspace_root)

    def render_memory_text(self) -> str:
        """渲染给模型看的记忆仪表盘文本。"""
        return render_memory_text(self.state, self.workspace_root)

    def promote_durable(self, promotions: Iterable[tuple[str, str]]) -> tuple[list[str], list[str]]:
        """把 ``(topic, note_text)`` 晋升到长期记忆，返回「已写入」与「被替换」两组说明。

        ``self.durable_store`` 为 ``None``（没有 Workspace）时直接返回两个空列表，晋升请求被
        静默丢弃：工作记忆不该因为缺少落盘位置而抛错。写入前后各规范化一次，因此返回的
        `durable_topics` 立刻反映这次晋升新建的主题。
        """
        if self.durable_store is None:
            return [], []
        self.state = normalize_memory_state(self.state, self.workspace_root)
        promoted, superseded = self.durable_store.promote(promotions)
        self.state = normalize_memory_state(self.state, self.workspace_root)
        return promoted, superseded

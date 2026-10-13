"""只依赖字典的规范化、写入与召回。

`normalize_memory_state` 把任何来源的记忆字典整理成 `contracts.default_memory_state()` 的形状，
`set_task_summary`、`remember_file`、`append_note`、`set_file_summary` 等写入函数都先规范化再改
一处，`retrieval_candidates`、`retrieval_view`、`render_memory_text` 与 `is_effectively_empty`
则把同一份状态读成召回条目、模型可见文本和「这一轮还需不需要提记忆」的判断。

这一层不认识磁盘：路径能否落到仓库内交给 `pico.capabilities.memory.workspace_paths`，跨会话主题
的读写交给 `pico.capabilities.memory.durable`，只有 ``workspace_root`` 一路透传下去。所有函数
原地修改并返回同一个字典，这是调用方赖以保存引用的既有契约，因此这里刻意不做深拷贝；截断上限
按字段固定（摘要 300 字符、条目正文 500 字符），不做按 Token 的预算。
"""

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable

from pico.capabilities.memory.contracts import (
    EPISODIC_NOTE_LIMIT,
    FILE_SUMMARY_LIMIT,
    MEMORY_KIND_EPISODIC,
    WORKING_FILE_LIMIT,
    default_memory_state,
)
from pico.capabilities.memory.workspace_paths import canonicalize_path, file_freshness
from pico.shared.clock import now
from pico.shared.text import clip

if TYPE_CHECKING:
    from pico.capabilities.memory.durable import DurableMemoryStore

#: 按字段固定的字符上限；沿用旧实现的原始数字，改它们等于改变持久化内容的截断点。
TASK_SUMMARY_CHARS = 300
NOTE_TEXT_CHARS = 500
FILE_SUMMARY_CHARS = 500

#: 一段读文件结果放进记忆时的默认摘要长度；比笔记正文短，因为它只是「刚读到什么」的提示。
READ_RESULT_SUMMARY_CHARS = 180


def _ensure_list(value: object) -> list[Any]:
    """把「可能是标量、集合或空值」的字段折叠成列表，供各段统一迭代。

    `list`/`tuple`/`set` 原样转换，``None`` 与空串得到 ``[]``，其余值包成单元素列表。
    `set` 分支的顺序不做保证：调用方随后都会去重并截断，这里不额外排序。
    """
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _dedupe_preserve_order(items: Iterable[Any]) -> list[Any]:
    """按首次出现顺序去重，元素本身不做任何归一化。

    需要的是「重复项只留最早那条」：`recent_files` 与 `tags` 的语义都是越靠前越新或越重要，
    用 `set` 会打乱顺序。不可哈希的元素不会出错，因为记录的是已经见过的对象而不是集合。
    """
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _tokenize(text: object) -> set[str]:
    """抽出 ASCII 单词与数字，小写后作为召回用的词袋。

    非 ASCII（含中文）会被直接丢弃，这是有意的取舍：词袋只用于打分排序，不参与展示，
    漏掉的词只会让相关性判定变宽松，不会让内容出错。为中文引入分词器会拉进新依赖，
    而 `_subject_key` 里已经用整串匹配处理了主要的中文句式。
    """
    return {token.lower() for token in re.findall(r"[A-Za-z0-9_]+", str(text))}


def _parse_timestamp(value: object) -> float:
    """把 `created_at` 字符串解析成可比较的 Unix 秒，解析不了就按「最旧」算。

    空值与任何异常都返回 ``0.0``：时间戳只参与排序，一条手写坏掉的时间不该让整次召回抛错，
    退到最小值恰好把它排到最后。这里吞掉的是 `Exception` 而不是裸 `except`，键盘中断之类
    仍然会照常传播。
    """
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(str(value)).timestamp()
    except Exception:
        return 0.0


def _normalize_note(note: Any, index: int) -> dict[str, Any]:
    """把一条笔记整理成固定六字段的字典，``index`` 是它在列表里的位置。

    纯文本、非字典对象和字典三条分支都会补出 `text`/`tags`/`source`/`created_at`/`note_index`/
    `kind`。正文裁到 500 字符，标签去空白去重；缺 `created_at` 时用当前时间填空——这意味着
    一条没有带时间戳的笔记每轮规范化都会拿到新的时间，排序里它总是「最新的那条」。

    `note_index` 优先取笔记自带的整数值，缺失才用 ``index``；旧状态迁移时这个字段决定
    `next_note_index` 的下界，所以不能一律按位置重写。
    """
    if isinstance(note, str):
        text = clip(note.strip(), NOTE_TEXT_CHARS)
        return {
            "text": text,
            "tags": [],
            "source": "",
            "created_at": now(),
            "note_index": index,
            "kind": MEMORY_KIND_EPISODIC,
        }

    if not isinstance(note, dict):
        text = clip(str(note).strip(), NOTE_TEXT_CHARS)
        return {
            "text": text,
            "tags": [],
            "source": "",
            "created_at": now(),
            "note_index": index,
            "kind": MEMORY_KIND_EPISODIC,
        }

    text = clip(str(note.get("text", "")).strip(), NOTE_TEXT_CHARS)
    tags = [str(tag).strip() for tag in _ensure_list(note.get("tags", [])) if str(tag).strip()]
    source = str(note.get("source", "")).strip()
    created_at = str(note.get("created_at", "")).strip() or now()
    note_index = int(note.get("note_index", index))
    kind = str(note.get("kind", MEMORY_KIND_EPISODIC)).strip() or MEMORY_KIND_EPISODIC
    return {
        "text": text,
        "tags": _dedupe_preserve_order(tags),
        "source": source,
        "created_at": created_at,
        "note_index": note_index,
        "kind": kind,
    }


def _durable_store_for(workspace_root: str | Path | None) -> "DurableMemoryStore | None":
    """按 ``workspace_root`` 绑定长期记忆存储，没有根目录时返回 ``None``。

    本模块要读 durable 的主题清单与候选笔记，而 durable 的打分又要复用这里的 `_tokenize`
    与 `_parse_timestamp`，两者构成模块级 import 环，所以在这个函数里就地导入。
    """
    from pico.capabilities.memory.durable import DurableMemoryStore

    return DurableMemoryStore.for_workspace(workspace_root)


def normalize_memory_state(state: dict[str, Any] | None, workspace_root: str | Path | None = None) -> dict[str, Any]:
    """把任意来源的记忆状态整理成当前 runtime 可直接使用的紧凑结构，原地返回 ``state``。

    ``state`` 为 ``None`` 时用 `default_memory_state()` 起步；不是映射时抛 `TypeError`，因为那
    通常意味着上游序列化写错了整份文件，静默替换会让错误一路带到 prompt 里。

    规范化层的作用是处理「磁盘里可能长得不太一样」的旧状态：`task`/`files`/`notes` 这三组旧字段
    只在对应新字段为空时被当作迁移来源读取，随后又在结尾被写回成新字段的镜像，所以读写两侧看到的
    是同一份事实。三段列表都只保留尾部（最近）若干条，`file_summaries` 丢弃路径或正文为空的条目，
    `next_note_index` 取「原值」与「最大 `note_index` 加一」的较大者以保证单调递增。

    结尾的 `durable_topics` 每次都会重新读一次磁盘索引：主题清单是外部可编辑的事实，缓存它就会在
    别处晋升后渲染出过期列表。这里不合并新旧笔记内容，也不校验 `freshness` 是否过期——判断摘要
    还该不该留下是 `invalidate_stale_file_summaries` 与渲染各自的事。
    """
    if state is None:
        state = default_memory_state()
    elif not isinstance(state, dict):
        raise TypeError("memory state must be a mapping")

    working = state.get("working")
    if not isinstance(working, dict):
        working = {}
    working.setdefault("task_summary", "")
    working.setdefault("recent_files", [])
    working["task_summary"] = clip(str(working.get("task_summary", "")).strip(), TASK_SUMMARY_CHARS)
    working["recent_files"] = _dedupe_preserve_order(
        [
            canonicalize_path(path, workspace_root)
            for path in _ensure_list(working.get("recent_files", []))
            if str(path).strip()
        ]
    )[-WORKING_FILE_LIMIT:]
    state["working"] = working

    # 旧字段只在新字段确实为空时才填，避免一份同时带着两套值的状态把摘要来回覆盖。
    if not str(working["task_summary"]).strip() and state.get("task"):
        working["task_summary"] = clip(str(state.get("task", "")).strip(), TASK_SUMMARY_CHARS)
    if not working["recent_files"] and state.get("files"):
        working["recent_files"] = _dedupe_preserve_order(
            [
                canonicalize_path(path, workspace_root)
                for path in _ensure_list(state.get("files", []))
                if str(path).strip()
            ]
        )[-WORKING_FILE_LIMIT:]

    episodic_notes = state.get("episodic_notes")
    if not isinstance(episodic_notes, list):
        episodic_notes = []

    if not episodic_notes and state.get("notes"):
        # 迁移路径：纯文本的旧 `notes` 按位置补 `note_index`，空串直接丢掉。
        episodic_notes = [
            _normalize_note(note, index)
            for index, note in enumerate(_ensure_list(state.get("notes", [])))
            if str(note).strip()
        ]
    else:
        normalized_notes = []
        for index, note in enumerate(episodic_notes):
            if isinstance(note, str) and not str(note).strip():
                continue
            normalized_notes.append(_normalize_note(note, index))
        episodic_notes = normalized_notes
    episodic_notes = episodic_notes[-EPISODIC_NOTE_LIMIT:]
    state["episodic_notes"] = episodic_notes

    file_summaries = state.get("file_summaries")
    if not isinstance(file_summaries, dict):
        file_summaries = {}
    normalized_file_summaries: dict[str, dict[str, Any]] = {}
    for path, summary in file_summaries.items():
        path = canonicalize_path(path, workspace_root)
        if isinstance(summary, dict):
            text = clip(str(summary.get("summary", "")).strip(), FILE_SUMMARY_CHARS)
            created_at = str(summary.get("created_at", "")).strip() or now()
            freshness = summary.get("freshness")
            freshness = None if freshness in (None, "") else str(freshness).strip() or None
        else:
            # 早期状态把摘要写成纯字符串，这里照样收下来，只是丢掉了它的 `freshness`。
            text = clip(str(summary).strip(), FILE_SUMMARY_CHARS)
            created_at = now()
            freshness = None
        if not path or not text:
            continue
        normalized_file_summaries[path] = {
            "summary": text,
            "created_at": created_at,
            "freshness": freshness,
        }
    state["file_summaries"] = normalized_file_summaries

    next_note_index = state.get("next_note_index")
    if not isinstance(next_note_index, int) or next_note_index < 0:
        next_note_index = 0
    max_index = max([note["note_index"] for note in episodic_notes], default=-1)
    state["next_note_index"] = max(next_note_index, max_index + 1)

    state["task"] = working["task_summary"]
    state["files"] = list(working["recent_files"])
    state["notes"] = [note["text"] for note in episodic_notes]
    durable_store = _durable_store_for(workspace_root)
    state["durable_topics"] = durable_store.topic_slugs() if durable_store is not None else []
    return state


def set_task_summary(
    state: dict[str, Any],
    summary: object,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """写入当前任务摘要，同步旧字段 `task`。

    先规范化再覆盖，所以传入的 ``state`` 拿到的一定是完整结构；摘要裁到 300 字符。空串是合法
    输入（表示「这轮没有明确任务」），不会退回旧值，因为清空本身就是调用者的意图。
    """
    state = normalize_memory_state(state, workspace_root)
    state["working"]["task_summary"] = clip(str(summary).strip(), TASK_SUMMARY_CHARS)
    state["task"] = state["working"]["task_summary"]
    return state


def remember_file(state: dict[str, Any], path: object, workspace_root: str | Path | None = None) -> dict[str, Any]:
    """把 ``path`` 记为最近接触的文件，重复记录会被移到末尾。

    路径先规范化再比较，因此 ``./a.py`` 与 ``a.py`` 只占一格；规范化后为空串就原样返回，不新增
    空条目。列表保留最后 `WORKING_FILE_LIMIT` 条，`state["files"]` 同步为同一份拷贝。
    """
    state = normalize_memory_state(state, workspace_root)
    path_key = canonicalize_path(path, workspace_root).strip()
    if not path_key:
        return state
    files = [item for item in state["working"]["recent_files"] if item != path_key]
    files.append(path_key)
    state["working"]["recent_files"] = files[-WORKING_FILE_LIMIT:]
    state["files"] = list(state["working"]["recent_files"])
    return state


def append_note(
    state: dict[str, Any],
    text: object,
    tags: Iterable[object] = (),
    source: str = "",
    created_at: str | None = None,
    workspace_root: str | Path | None = None,
    kind: str = MEMORY_KIND_EPISODIC,
) -> dict[str, Any]:
    """追加一条跨轮笔记，同文本的旧笔记会被新条目替换并移到末尾。

    正文裁到 500 字符，为空时直接返回原状态——空笔记没有召回价值，占一格反而会把真实内容挤出
    上限。``tags`` 允许任何可迭代对象（`str` 也会按 `_ensure_list` 当成单个标签），去空白去重后
    保存；``created_at`` 缺失时用当前时间，``kind`` 为空白时退回 `episodic`。

    `note_index` 取自 `next_note_index` 并立刻自增，所以淘汰与重排都不会让两条笔记共用序号。
    笔记数量保留最后 `EPISODIC_NOTE_LIMIT` 条，`state["notes"]` 同步为正文列表。
    """
    state = normalize_memory_state(state, workspace_root)
    note_text = clip(str(text).strip(), NOTE_TEXT_CHARS)
    if not note_text:
        return state

    normalized_tags = _dedupe_preserve_order([str(tag).strip() for tag in _ensure_list(tags) if str(tag).strip()])
    note: dict[str, Any] = {
        "text": note_text,
        "tags": normalized_tags,
        "source": str(source).strip(),
        "created_at": str(created_at).strip() if created_at else now(),
        "note_index": int(state.get("next_note_index", 0)),
        "kind": str(kind).strip() or MEMORY_KIND_EPISODIC,
    }
    state["next_note_index"] = note["note_index"] + 1

    notes = [item for item in state["episodic_notes"] if item["text"] != note_text]
    notes.append(note)
    state["episodic_notes"] = notes[-EPISODIC_NOTE_LIMIT:]
    state["notes"] = [item["text"] for item in state["episodic_notes"]]
    return state


def set_file_summary(
    state: dict[str, Any],
    path: object,
    summary: object,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """为某个文件写下短摘要，并记住写下它时文件的内容指纹。

    路径或摘要为空时不改状态，这样「读了一半」的结果不会覆盖上一次的有效摘要。摘要裁到 500
    字符，`created_at` 取当前时间，`freshness` 由 `file_freshness` 现场计算；文件此刻不存在也没
    关系，指纹留 ``None``，等渲染时再自然失效。
    """
    state = normalize_memory_state(state, workspace_root)
    path_key = canonicalize_path(path, workspace_root).strip()
    summary_text = clip(str(summary).strip(), FILE_SUMMARY_CHARS)
    if not path_key or not summary_text:
        return state
    state["file_summaries"][path_key] = {
        "summary": summary_text,
        "created_at": now(),
        "freshness": file_freshness(path_key, workspace_root),
    }
    return state


def invalidate_file_summary(
    state: dict[str, Any],
    path: object,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """删掉某个文件的摘要，路径不在记录里时静默返回。

    写入前的显式失效用得上：旧摘要一旦被认定为不可信就不该继续出现在 prompt 里。规范化只在
    开头做一次，避免为了删一个键而重新读一遍磁盘索引。
    """
    state = normalize_memory_state(state, workspace_root)
    path_key = canonicalize_path(path, workspace_root).strip()
    if not path_key:
        return state
    state["file_summaries"].pop(path_key, None)
    return state


def invalidate_stale_file_summaries(
    state: dict[str, Any],
    workspace_root: str | Path | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """清除内容已经变过的文件摘要，返回新状态和被清掉的路径列表。

    比较的是「当前指纹」与「摘要记录的指纹」，两者不等就删。注意边界：文件不存在或越界时当前
    指纹是 ``None``，若摘要记录的也是 ``None`` 就视为相等并保留——「摘要本来就没指纹」和
    「文件消失了」在这条规则下无法区分，这是为了不把没有指纹历史的状态一次清空而接受的取舍。

    返回值里的列表按字典迭代顺序给出，只用于日志与 trace，不承诺按失效严重程度排序。
    """
    state = normalize_memory_state(state, workspace_root)
    invalidated: list[str] = []
    for path, summary in list(state["file_summaries"].items()):
        current_freshness = file_freshness(path, workspace_root)
        if summary.get("freshness") == current_freshness:
            continue
        invalidated.append(path)
        state["file_summaries"].pop(path, None)
    return state, invalidated


def summarize_read_result(result: object, limit: int = READ_RESULT_SUMMARY_CHARS) -> str:
    """把一次读文件的结果压成一行短提示，供 `set_file_summary` 直接使用。

    先丢掉空行，若首行是 ``# `` 开头的标题（Markdown 文档标题或工具自己加的页眉）就跳过它，
    再取前三行用 ``" | "`` 拼接，最后按 ``limit`` 裁剪。整份内容为空、或只有一个标题时返回
    字面量 ``(empty)``，让调用方仍能写下一条有意义的摘要而不是空串。

    这里不理解代码结构，也不做语法着色或符号抽取：记忆层只需要「刚读到的大概是这些」。
    """
    lines = [line.strip() for line in str(result).splitlines() if line.strip()]
    if not lines:
        return "(empty)"
    if lines[0].startswith("# "):
        lines = lines[1:]
    if not lines:
        return "(empty)"
    summary = " | ".join(lines[:3])
    return clip(summary, limit)


def retrieval_candidates(
    state: dict[str, Any],
    query: object,
    limit: int = 3,
    workspace_root: str | Path | None = None,
) -> list[dict[str, Any]]:
    """按 ``query`` 从工作笔记和磁盘主题里挑出最相关的若干条笔记。

    打分是三级字典序：标签精确命中、关键词重叠数、时间新旧（工作笔记再加一级 `note_index`
    作为最后的稳定序）。排序故意保持简单透明，不引入 embedding——召回质量够用并且可解释，比
    接近语义搜索更重要。

    工作笔记里两者都为 0 的条目会被跳过，但 durable 候选只补分不筛：它们的分数由本函数二次
    计算，因此一条空 ``query`` 仍可能带回按时间排好序的长期笔记。``workspace_root`` 为 ``None``
    时完全不读磁盘。``limit`` 只截断最终列表，不限制各自读取的条数；排序稳定，同分条目保持
    「工作笔记在前、磁盘笔记在后」的写入顺序。
    """
    state = normalize_memory_state(state, workspace_root)
    query_tokens = _tokenize(query)
    ranked: list[tuple[tuple[int, int, float, int], dict[str, Any]]] = []
    for note in state["episodic_notes"]:
        note_tags = {tag.lower() for tag in note.get("tags", [])}
        note_tokens = _tokenize(note.get("text", "")) | _tokenize(note.get("source", "")) | note_tags
        exact_tag_match = int(bool(query_tokens & note_tags))
        keyword_overlap = len(query_tokens & note_tokens)
        if exact_tag_match == 0 and keyword_overlap == 0:
            continue
        recency = _parse_timestamp(note.get("created_at"))
        note_index = int(note.get("note_index", 0))
        ranked.append(((exact_tag_match, keyword_overlap, recency, note_index), note))

    durable_store = _durable_store_for(workspace_root)
    if durable_store is not None:
        for note in durable_store.retrieval_candidates(query, limit=limit):
            note_tags = {tag.lower() for tag in note.get("tags", [])}
            note_tokens = _tokenize(note.get("text", "")) | _tokenize(note.get("source", "")) | note_tags
            exact_tag_match = int(bool(query_tokens & note_tags))
            keyword_overlap = len(query_tokens & note_tokens)
            recency = _parse_timestamp(note.get("created_at"))
            # 磁盘笔记没有 `note_index`，用 -1 占位，保证同分时排在状态内笔记之前。
            ranked.append(((exact_tag_match, keyword_overlap, recency, -1), note))

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [note for _, note in ranked[:limit]]


def retrieval_view(
    state: dict[str, Any],
    query: object,
    limit: int = 3,
    workspace_root: str | Path | None = None,
) -> str:
    """渲染一段 ``Relevant memory:`` 列表文本，没有命中时输出一条 ``- none``。

    只打印笔记正文：标签、来源和时间留在结构化结果里由调用方使用，进入 prompt 只会挤占预算。
    空结果仍然返回标题行，这样 prompt 组装不需要为「有没有命中」写分支。
    """
    candidates = retrieval_candidates(state, query, limit=limit, workspace_root=workspace_root)
    lines = ["Relevant memory:"]
    if not candidates:
        lines.append("- none")
        return "\n".join(lines)
    for note in candidates:
        lines.append(f"- {note['text']}")
    return "\n".join(lines)


def render_memory_text(state: dict[str, Any], workspace_root: str | Path | None = None) -> str:
    """渲染给模型看的紧凑「仪表盘」：任务、最近文件、有效摘要、笔记计数与主题清单。

    开头会规范化一次，因此调用方传进来的半旧状态也能读。笔记正文默认不展开，只在数量里出现，
    真正相关时由 `retrieval_view` 按需带出；文件摘要只覆盖最近 `FILE_SUMMARY_LIMIT` 个文件，
    而且必须指纹仍与磁盘一致才写出来，一条都对不上就退化成 ``- file_summaries: -``。

    这里不判断内容是否值得记住，也不做长度预算分配：整段文本的取舍属于 runtime 的上下文组装。
    """
    state = normalize_memory_state(state, workspace_root)
    lines = [
        "Memory:",
        f"- task: {state['working']['task_summary'] or '-'}",
        f"- recent_files: {', '.join(state['working']['recent_files']) or '-'}",
    ]

    summaries = []
    for path in state["working"]["recent_files"][:FILE_SUMMARY_LIMIT]:
        summary = state["file_summaries"].get(path, {})
        current_freshness = file_freshness(path, workspace_root)
        if summary.get("summary", "") and summary.get("freshness") == current_freshness:
            summaries.append(f"- {path}: {summary['summary']}")
    if summaries:
        lines.append("- file_summaries:")
        lines.extend(f"  {line}" for line in summaries)
    else:
        lines.append("- file_summaries: -")

    lines.append(f"- episodic_notes: {len(state['episodic_notes'])}")
    durable_topics = state.get("durable_topics", [])
    lines.append(f"- durable_topics: {', '.join(durable_topics) or '-'}")
    return "\n".join(lines)


def is_effectively_empty(state: dict[str, Any], workspace_root: str | Path | None = None) -> bool:
    """判断这份状态是否还值得一提。

    四段全空才算空：`task`/`files`/`notes` 等镜像字段不参与判断，它们总是由规范化重写。
    `durable_topics` 也不算内容——磁盘上有主题文件但本轮工作集为空时，答案仍是 ``True``，
    因为「要不要在 prompt 里插一段 Memory」取决于当前任务是否连着这些事实。
    """
    state = normalize_memory_state(state, workspace_root)
    return (
        not str(state["working"]["task_summary"]).strip()
        and not state["working"]["recent_files"]
        and not state["episodic_notes"]
        and not state["file_summaries"]
    )

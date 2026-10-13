"""基于文件的长期记忆：一份 markdown 索引加若干主题笔记文件。

`DurableMemoryStore` 把跨会话事实存在 ``<workspace>/.pico/memory`` 下：``MEMORY.md`` 登记主题清单
（标题、摘要、标签），``topics/<slug>.md`` 的 ``## Notes`` 段落逐条记录笔记。`promote` 负责写入，
并按「同一主语只保留最新一条」替换被淘汰的旧事实；`retrieval_candidates` 复用 `state` 层的分词与
时间解析，把从磁盘读回的笔记打成分数。

这里不碰工作记忆状态字典，也不决定哪些笔记值得晋升——那是 runtime 与模型的判断。格式刻意保持为
人可以直接编辑的 markdown，因此读写都是整行匹配：认不出的行跳过而不是报错，手工改坏文件只会让
那一条信息暂时消失。写入沿用整份 `write_text` 而不是 `pico.shared.atomic_io`：那里提供的是 JSON
原子替换，而索引与笔记之间并不是一次事务，读侧本就允许两者短暂不一致。
"""

import re
from pathlib import Path
from typing import Any, Iterable

from pico.capabilities.memory.contracts import DURABLE_TOPIC_DEFAULTS, MEMORY_KIND_DURABLE
from pico.capabilities.memory.state import _parse_timestamp, _tokenize
from pico.shared.clock import now
from pico.shared.paths import ensure_dir

#: 长期记忆目录相对 Workspace 根的位置；`for_workspace` 之外的调用方不需要知道它。
_DURABLE_DIR = Path(".pico") / "memory"

#: 索引行的形状：``- [slug](topics/slug.md): Title``。
_INDEX_LINE = re.compile(r"- \[([^\]]+)\]\([^)]+\):\s*(.+)")
_SUMMARY_LINE = re.compile(r"- summary:\s*(.+)")
_TAGS_LINE = re.compile(r"- tags:\s*(.+)")

#: 「同一主语」的识别句式：抽出 be/使用/should 之前的部分作为替换键。
_SUBJECT_PATTERNS = (
    r"^(.+?)\s+is\s+.+$",
    r"^(.+?)\s+are\s+.+$",
    r"^(.+?)\s+uses?\s+.+$",
    r"^(.+?)\s+should\s+.+$",
    r"^(.+?)是.+$",
    r"^(.+?)使用.+$",
)


class DurableMemoryStore:
    """一个 Workspace 的跨会话主题存储。

    构造只做路径拼接，不创建目录，也不读文件；所以随手的 `DurableMemoryStore` 实例没有副作用，
    首次落盘才建立 ``MEMORY.md`` 与 ``topics/``。实例不持有缓存，每次读取都回到磁盘，这样别处
    编辑过的主题立刻可见。
    """

    def __init__(self, root: str | Path) -> None:
        """绑定存储根目录 ``root``，索引为 ``root/MEMORY.md``，笔记在 ``root/topics``。"""
        self.root = Path(root)
        self.index_path = self.root / "MEMORY.md"
        self.topics_dir = self.root / "topics"

    @staticmethod
    def for_workspace(workspace_root: str | Path | None) -> "DurableMemoryStore | None":
        """按 Workspace 根目录构造存储；``workspace_root`` 为 ``None`` 时返回 ``None``。

        三个调用点（状态规范化、召回、`LayeredMemory`）都用同一个子路径，集中在这里可以避免
        拼写漂移。返回 ``None`` 表示「没有可写的磁盘位置」，调用方据此把长期记忆降级为不做。
        """
        if workspace_root is None:
            return None
        return DurableMemoryStore(Path(workspace_root) / _DURABLE_DIR)

    def topic_slugs(self) -> list[str]:
        """返回索引里登记的主题 slug，顺序与 ``MEMORY.md`` 的行顺序一致。"""
        return [topic["topic"] for topic in self.load_index()]

    def load_index(self) -> list[dict[str, Any]]:
        """解析 ``MEMORY.md``，得到每个主题的 `topic`/`title`/`summary`/`tags`。

        文件不存在返回空列表。只有匹配 `- [slug](...)：标题` 的行开启一条新记录，随后的
        `- summary:` 与 `- tags:` 缩进行填进当前记录；出现在第一条主题之前的字段行被忽略，缺
        summary 或 tags 的记录保留空串与空列表——主题清单不完整通常只是手工编辑的中途状态，
        不值得为此抛错。
        """
        if not self.index_path.exists():
            return []
        lines = self.index_path.read_text(encoding="utf-8").splitlines()
        topics: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for raw in lines:
            line = raw.strip()
            match = _INDEX_LINE.match(line)
            if match:
                current = {
                    "topic": match.group(1).strip(),
                    "title": match.group(2).strip(),
                    "summary": "",
                    "tags": [],
                }
                topics.append(current)
                continue
            if current is None:
                continue
            summary_match = _SUMMARY_LINE.match(line)
            if summary_match:
                current["summary"] = summary_match.group(1).strip()
                continue
            tags_match = _TAGS_LINE.match(line)
            if tags_match:
                current["tags"] = [tag.strip() for tag in tags_match.group(1).split(",") if tag.strip()]
        return topics

    def load_topic_notes(self, topic: str) -> list[dict[str, Any]]:
        """读出某个主题的笔记，返回带 `kind`/`source` 的笔记字典列表。

        文件不存在返回空列表。只有 ``## Notes`` 之后的 ``- `` 行算作笔记；``- tags:`` 与
        ``- updated_at:`` 是文件级元数据，出现在笔记之前，因此它们作用到其后读到的每一条笔记上。
        缺少 `updated_at` 时该条笔记的 `created_at` 退回当前时间，代价是同一份文件在不同时刻读出
        的「新旧」并不稳定。

        返回的字典没有 `note_index`：磁盘笔记不属于状态里的追加序列，混用会让 `next_note_index`
        失去单调性。
        """
        path = self.topics_dir / f"{topic}.md"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        notes: list[dict[str, Any]] = []
        capture = False
        updated_at = ""
        tags: list[str] = []
        for raw in lines:
            line = raw.strip()
            if line.startswith("- tags:"):
                tags = [tag.strip() for tag in line.split(":", 1)[1].split(",") if tag.strip()]
            elif line.startswith("- updated_at:"):
                updated_at = line.split(":", 1)[1].strip()
            elif line == "## Notes":
                capture = True
            elif capture and line.startswith("- "):
                notes.append(
                    {
                        "text": line[2:].strip(),
                        "tags": tags,
                        "source": topic,
                        "created_at": updated_at or now(),
                        "kind": MEMORY_KIND_DURABLE,
                    }
                )
        return notes

    @staticmethod
    def _subject_key(text: object) -> str | None:
        """抽出一条事实的主语，作为「同一件事的旧版本」的判定键；句式不匹配时返回 ``None``。

        只认 `_SUBJECT_PATTERNS` 里那几种「X is/are/uses/should Y」「X 是 Y」「X 使用 Y」的写法，
        因为可替换的事实大多长成这样。主语随后过一遍 `_tokenize` 再 join，得到与大小写、多余
        空白无关的键；匹配不到就不替换，直接追加新条目。
        """
        subject_text = str(text).strip()
        for pattern in _SUBJECT_PATTERNS:
            match = re.match(pattern, subject_text, re.I)
            if match:
                subject = " ".join(_tokenize(match.group(1)))
                return subject or None
        return None

    def retrieval_candidates(self, query: object, limit: int = 3) -> list[dict[str, Any]]:
        """遍历所有主题的笔记，按标签命中、关键词重叠与时间新旧排一次序后取前 ``limit`` 条。

        ``query`` 里出现主题标题或笔记标签都算命中，因此「用主题名当查询」也能召回。分数为 0 的
        笔记被跳过，不返回任何内容时给出空列表而不是抛错。这里不缓存文件读取结果：主题数量很小，
        每次都重读索引与笔记，避免在一个可能被人手工编辑的目录上维护过期视图。
        """
        query_tokens = _tokenize(query)
        ranked: list[tuple[tuple[int, int, float], dict[str, Any]]] = []
        for topic in self.load_index():
            notes = self.load_topic_notes(topic["topic"])
            for note in notes:
                note_tags = {tag.lower() for tag in note.get("tags", [])}
                note_tokens = _tokenize(note.get("text", "")) | _tokenize(topic.get("title", "")) | note_tags
                exact_tag_match = int(bool(query_tokens & note_tags))
                keyword_overlap = len(query_tokens & note_tokens)
                if exact_tag_match == 0 and keyword_overlap == 0:
                    continue
                recency = _parse_timestamp(note.get("created_at"))
                ranked.append(((exact_tag_match, keyword_overlap, recency), note))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [note for _, note in ranked[:limit]]

    def _write_index(self, topics: list[dict[str, Any]]) -> None:
        """按传入顺序整份重写 ``MEMORY.md``。

        每个主题三行：清单行、summary、tags。末尾统一 `rstrip` 再补一个换行，保证文件永远以
        单个换行结束，重复写入得到逐字节相同的输出。目录由 `ensure_dir` 就地创建，调用方不需要
        先建立存储根。
        """
        ensure_dir(self.root)
        ensure_dir(self.topics_dir)
        lines = ["# Durable Memory Index", ""]
        for topic in topics:
            lines.append(f"- [{topic['topic']}](topics/{topic['topic']}.md): {topic['title']}")
            lines.append(f"  - summary: {topic['summary']}")
            lines.append(f"  - tags: {', '.join(topic['tags'])}")
        self.index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _write_topic(self, topic: str, notes: list[str]) -> None:
        """整份重写 ``topics/<topic>.md``，元数据取自主题默认值。

        ``topic`` 必须是 `DURABLE_TOPIC_DEFAULTS` 里的 key，否则抛 `KeyError`：只有已知主题才有
        可信的标题与摘要，未知 slug 写出来就是一段没有来源的文本。`updated_at` 每次写入刷新，
        因此读侧把它当作「整个主题的最后修改时间」，而不是单条笔记的时间。
        """
        ensure_dir(self.topics_dir)
        meta = DURABLE_TOPIC_DEFAULTS[topic]
        lines = [
            f"# {meta['title']}",
            "",
            f"- topic: {topic}",
            f"- summary: {meta['summary']}",
            f"- tags: {', '.join(meta['tags'])}",
            f"- updated_at: {now()}",
            "",
            "## Notes",
        ]
        for note in notes:
            lines.append(f"- {note}")
        (self.topics_dir / f"{topic}.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def promote(self, promotions: Iterable[tuple[str, str]]) -> tuple[list[str], list[str]]:
        """把 ``(topic, note_text)`` 序列写进长期记忆，返回「已写入」与「被替换」两组说明。

        空输入直接得到两个空列表，不碰磁盘。已知主题若尚未出现在索引里，会按默认标题、摘要与
        标签新建一条；未知主题在 `_write_topic` 里抛 `KeyError`。完全相同的文本视为已经记住，
        跳过；主语相同而表述不同的旧文本被新文本原地替换，并在第二个列表里留下
        ``"topic: 旧 -> 新"`` 的替换证据。

        索引按 slug 字典序写回，主题文件按本次涉及到的主题逐个重写；一次调用只保证「先索引后
        笔记」的顺序，不是原子事务，中途失败会留下已经写入的部分主题。没有跨进程锁：一个 Pico
        实例独占它的工作区，并发晋升由上层避免。
        """
        if not promotions:
            return [], []
        topics: dict[str, dict[str, Any]] = {topic["topic"]: topic for topic in self.load_index()}
        # 先把每个主题的正文笔记读成字符串列表，最后再整份写回，避免边读边写产生半更新状态。
        topic_notes: dict[str, list[str]] = {
            slug: [note["text"] for note in self.load_topic_notes(slug)] for slug in topics
        }
        results: list[str] = []
        superseded: list[str] = []
        for topic, note_text in promotions:
            meta = DURABLE_TOPIC_DEFAULTS[topic]
            topics.setdefault(
                topic,
                {
                    "topic": topic,
                    "title": meta["title"],
                    "summary": meta["summary"],
                    "tags": list(meta["tags"]),
                },
            )
            existing = topic_notes.setdefault(topic, [])
            if note_text in existing:
                continue
            new_subject = self._subject_key(note_text)
            replaced = False
            if new_subject:
                for index, old_text in enumerate(list(existing)):
                    if self._subject_key(old_text) == new_subject:
                        superseded.append(f"{topic}: {old_text} -> {note_text}")
                        existing[index] = note_text
                        replaced = True
                        break
            if not replaced:
                existing.append(note_text)
            results.append(f"{topic}: {note_text}")
        self._write_index([topics[slug] for slug in sorted(topics)])
        for topic, notes in topic_notes.items():
            self._write_topic(topic, notes)
        return results, superseded

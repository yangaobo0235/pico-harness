"""记忆层的稳定词汇：状态骨架、各段容量上限与 durable topic 名称。

`default_memory_state()` 规定一份工作记忆唯一允许的形状——当前任务摘要、最近接触的文件、
跨轮笔记与文件短摘要，外加 `task`/`files`/`notes` 三个给旧读取方看的镜像字段；
`WORKING_FILE_LIMIT`、`EPISODIC_NOTE_LIMIT`、`FILE_SUMMARY_LIMIT` 决定这几段各保留多少条；
`DURABLE_TOPIC_DEFAULTS` 列出跨会话主题的名称、标题、摘要与标签，`DurableMemoryStore` 只会为
其中出现过的主题落盘。

本模块只声明常量与骨架，不读写文件系统，也不判断条目内容是否合法；把磁盘上长得各异的旧状态
整理成这个形状属于 `pico.capabilities.memory.state`。上限集中定义是为了让「留几条」只有一处
可以改，规范化、渲染与召回引用的是同一组数字；主题集合刻意保持为代码事实，新增主题要同时
调整写入与文档，因此没有提供运行时注册入口。
"""

from typing import Any

#: 各段记忆的条目上限；截断都保留尾部（最近的），因此这三处用的是「切掉开头」的语义。
WORKING_FILE_LIMIT = 8
EPISODIC_NOTE_LIMIT = 12
FILE_SUMMARY_LIMIT = 6

#: 跨会话主题名：既是磁盘上的 ``topics/<slug>.md`` 文件名，也是晋升调用必须使用的 key。
TOPIC_PROJECT_CONVENTIONS = "project-conventions"
TOPIC_KEY_DECISIONS = "key-decisions"
TOPIC_DEPENDENCY_FACTS = "dependency-facts"
TOPIC_USER_PREFERENCES = "user-preferences"

#: 笔记属于哪一层：``episodic`` 由工作记忆状态携带，``durable`` 由主题文件读回时补上。
MEMORY_KIND_EPISODIC = "episodic"
MEMORY_KIND_DURABLE = "durable"

#: 主题的默认元数据。`tags` 保持可变列表而不是元组，写入索引时会直接 `join`。
DURABLE_TOPIC_DEFAULTS: dict[str, dict[str, Any]] = {
    TOPIC_PROJECT_CONVENTIONS: {
        "title": "Project Conventions",
        "summary": "Stable repository conventions.",
        "tags": ["convention"],
    },
    TOPIC_KEY_DECISIONS: {
        "title": "Key Decisions",
        "summary": "Long-lived decisions and rationale anchors.",
        "tags": ["decision"],
    },
    TOPIC_DEPENDENCY_FACTS: {
        "title": "Dependency Facts",
        "summary": "Stable dependency and environment facts.",
        "tags": ["dependency"],
    },
    TOPIC_USER_PREFERENCES: {
        "title": "User Preferences",
        "summary": "Stable user preferences.",
        "tags": ["preference"],
    },
}


def default_memory_state() -> dict[str, Any]:
    """返回一份空但结构完整的记忆状态，可直接交给 `normalize_memory_state`。

    输入为空、输出固定包含 `working`/`episodic_notes`/`file_summaries` 三段，以及
    `task`/`files`/`notes`/`next_note_index` 四个兼容字段。用一个小而结构化的状态，而不是一大段
    自由文本摘要：旧状态只填了兼容字段时，规范化层仍能把它们迁移进新结构。

    每次调用都返回全新对象（嵌套列表与字典也不共享），因此调用方可以原地修改而不影响下一次
    构造。这里不校验内容长度，也不预填 `durable_topics`——那是读取磁盘后才能得到的字段。
    """
    return {
        "working": {
            "task_summary": "",
            "recent_files": [],
        },
        "episodic_notes": [],
        "file_summaries": {},
        "task": "",
        "files": [],
        "notes": [],
        "next_note_index": 0,
    }

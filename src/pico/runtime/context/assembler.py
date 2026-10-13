"""把一轮请求组装成真正发给模型的 Prompt。

`ContextAssembler` 是发送前的最后一道工序：收集稳定指令、工作记忆、相关记忆、历史与本轮请求，
按预算渲染每一段，超预算时按固定顺序收缩，并产出一份解释“这段 Prompt 是怎么来的”的元数据。
元数据随后进入 Trace 与报告，因此复盘时可以重建每一段的原始长度、分配预算与实际渲染长度。

它不决定段内文本长什么样（属于 `pico.runtime.context.segments`），也不决定预算数字
（属于 `pico.runtime.context.budget`），更不调用模型。收缩的偏好写在顺序里：先牺牲相关笔记和
历史，再动工作记忆，稳定指令最后；本轮用户请求永远不裁剪。
"""

from typing import TYPE_CHECKING, Any

from pico.config.models.features import CONTEXT_REDUCTION, MEMORY, RELEVANT_MEMORY
from pico.runtime.context.budget import (
    BUDGETED_SECTIONS,
    CURRENT_REQUEST_SECTION,
    DEFAULT_REDUCTION_ORDER,
    DEFAULT_SECTION_BUDGETS,
    DEFAULT_TOTAL_BUDGET,
    HISTORY_SECTION,
    INSTRUCTIONS_SECTION,
    MEMORY_SECTION,
    RELEVANT_MEMORY_LIMIT,
    RELEVANT_MEMORY_SECTION,
    SECTION_ORDER,
    compute_section_floors,
    next_reduction,
    reduction_record,
)
from pico.runtime.context.history_trimmer import raw_text as raw_history_text
from pico.runtime.context.segments import (
    SectionRender,
    render_history,
    render_instructions,
    render_memory,
    render_relevant_memory,
)
from pico.runtime.context.segments.memory import MEMORY_DISABLED_TEXT

if TYPE_CHECKING:
    from pico.runtime.agent.agent import Pico


class ContextAssembler:
    """按预算拼装一轮 Prompt，并解释每个段落的裁剪结果。

    构造时接受覆盖后的预算与收缩顺序，消融实验因此可以在不改运行时代码的前提下把某一段压到
    下限或整段关闭。预算之间的比例关系保持默认，除非调用方显式给出 ``section_budgets``；
    ``section_floors`` 只覆盖需要偏离“四分之一”默认比例的段落。

    组装器持有 runtime 引用：指令文本、会话历史、记忆检索和 checkpoint 文本都是运行时当下
    的事实，复制进构造参数会让每轮都要重建一个组装器。
    """

    def __init__(
        self,
        agent: "Pico",
        total_budget: int = DEFAULT_TOTAL_BUDGET,
        section_budgets: dict[str, int] | None = None,
        section_floors: dict[str, int] | None = None,
        reduction_order: tuple[str, ...] | None = None,
    ):
        self.agent = agent
        self.total_budget = int(total_budget)
        self.section_budgets = dict(DEFAULT_SECTION_BUDGETS)
        if section_budgets:
            self.section_budgets.update({str(key): int(value) for key, value in section_budgets.items()})
        self._section_floor_overrides = {str(key): int(value) for key, value in (section_floors or {}).items()}
        self.section_floors = self._compute_section_floors()
        self.reduction_order = tuple(reduction_order or DEFAULT_REDUCTION_ORDER)

    def build(self, user_message: str) -> tuple[str, dict[str, Any]]:
        """返回 ``(prompt, metadata)``。

        流程是：采集各段原始文本 → 选中相关记忆 → 按预算渲染 → 超预算则循环收缩 → 拼接。
        ``context_reduction`` 关闭时跳过收缩，各段按原始长度直接进入 Prompt，用于测量“没有
        预算控制时模型看到什么”；``memory`` 或 ``relevant_memory`` 关闭时对应段落写成显式的
        关闭事实，而不是留一段空白。

        返回的 Prompt 以本轮请求结尾，元数据里的段落顺序与实际拼接顺序一致。
        """
        user_message = str(user_message)
        self.section_floors = self._compute_section_floors()
        memory_enabled = True
        relevant_memory_enabled = True
        context_reduction_enabled = True
        if hasattr(self.agent, "feature_enabled"):
            memory_enabled = self.agent.feature_enabled(MEMORY)
            relevant_memory_enabled = self.agent.feature_enabled(RELEVANT_MEMORY)
            context_reduction_enabled = self.agent.feature_enabled(CONTEXT_REDUCTION)

        section_texts = {
            INSTRUCTIONS_SECTION: str(getattr(self.agent, "prefix", "")),
            MEMORY_SECTION: MEMORY_DISABLED_TEXT if not memory_enabled else str(self.agent.memory_text()),
            HISTORY_SECTION: "",
            CURRENT_REQUEST_SECTION: f"Current user request:\n{user_message}",
        }

        checkpoint_text = ""
        if hasattr(self.agent, "render_checkpoint_text"):
            checkpoint_text = str(self.agent.render_checkpoint_text() or "").strip()
        if checkpoint_text:
            section_texts[INSTRUCTIONS_SECTION] = section_texts[INSTRUCTIONS_SECTION] + "\n\n" + checkpoint_text

        selected_notes = []
        if (
            memory_enabled
            and relevant_memory_enabled
            and hasattr(self.agent, "memory")
            and hasattr(self.agent.memory, "retrieval_candidates")
        ):
            selected_notes = self.agent.memory.retrieval_candidates(user_message, limit=RELEVANT_MEMORY_LIMIT)

        if not context_reduction_enabled:
            rendered = self._render_without_reduction(section_texts, selected_notes=selected_notes)
            prompt = self._assemble(rendered)
            metadata = self._metadata(
                prompt=prompt,
                rendered=rendered,
                budgets={
                    section: render.budget for section, render in rendered.items() if section != CURRENT_REQUEST_SECTION
                },
                reduction_log=[],
                selected_notes=selected_notes,
                user_message=user_message,
                section_texts=section_texts,
            )
            return prompt, metadata

        budgets = dict(self.section_budgets)
        rendered = self._render(section_texts, budgets, selected_notes=selected_notes)
        prompt = self._assemble(rendered)
        reduction_log: list[dict[str, Any]] = []

        while len(prompt) > self.total_budget:
            overflow = len(prompt) - self.total_budget
            step = next_reduction(budgets, self.section_floors, self.reduction_order, overflow)
            if step is None:
                break
            section, new_budget = step
            reduction_log.append(reduction_record(section, budgets.get(section, 0), new_budget, overflow))
            budgets[section] = new_budget
            rendered = self._render(section_texts, budgets, selected_notes=selected_notes)
            prompt = self._assemble(rendered)

        metadata = self._metadata(
            prompt=prompt,
            rendered=rendered,
            budgets=budgets,
            reduction_log=reduction_log,
            selected_notes=selected_notes,
            user_message=user_message,
            section_texts=section_texts,
        )
        return prompt, metadata

    def _compute_section_floors(self) -> dict[str, int]:
        """把预算换算成各段下限，并套用显式覆盖。"""
        return compute_section_floors(self.section_budgets, self._section_floor_overrides)

    def _render(
        self,
        section_texts: dict[str, str],
        budgets: dict[str, int],
        selected_notes: list[dict[str, Any]] | None = None,
    ) -> dict[str, SectionRender]:
        """按 ``SECTION_ORDER`` 渲染每个段落。

        本轮请求不消耗预算，长度等于原文；历史段的原文不来自 ``section_texts``，而是直接从会话
        历史渲染，因为它需要逐条压缩而不是整段裁剪。
        """
        rendered: dict[str, SectionRender] = {}
        for section in SECTION_ORDER:
            budget = budgets.get(section)
            if section == CURRENT_REQUEST_SECTION:
                raw = section_texts[section]
                rendered[section] = SectionRender(raw=raw, budget=0, rendered=raw, details={})
            elif section == RELEVANT_MEMORY_SECTION:
                rendered[section] = render_relevant_memory(selected_notes or [], int(budget or 0))
            elif section == HISTORY_SECTION:
                rendered[section] = render_history(self._history(), int(budget or 0), self._file_summaries())
            elif section == MEMORY_SECTION:
                rendered[section] = render_memory(section_texts[section], int(budget or 0))
            else:
                rendered[section] = render_instructions(section_texts[section], int(budget or 0))
        return rendered

    def _render_without_reduction(
        self,
        section_texts: dict[str, str],
        selected_notes: list[dict[str, Any]] | None = None,
    ) -> dict[str, SectionRender]:
        """关闭收缩时的渲染：每段都按原文长度给出。

        相关记忆仍然只做“选中条目原样列出”，不逐条平分预算——这条路径存在的意义就是测量
        不受预算约束的 Prompt，任何裁剪都会污染对照结果。
        """
        selected_notes = selected_notes or []
        relevant_lines = ["Relevant memory:"]
        if selected_notes:
            relevant_lines.extend(f"- {note['text']}" for note in selected_notes)
        else:
            relevant_lines.append("- none")
        relevant_raw = "\n".join(relevant_lines)
        history = self._history()
        history_raw = raw_history_text(history)
        return {
            INSTRUCTIONS_SECTION: SectionRender(
                raw=section_texts[INSTRUCTIONS_SECTION],
                budget=len(section_texts[INSTRUCTIONS_SECTION]),
                rendered=section_texts[INSTRUCTIONS_SECTION],
                details={},
            ),
            MEMORY_SECTION: SectionRender(
                raw=section_texts[MEMORY_SECTION],
                budget=len(section_texts[MEMORY_SECTION]),
                rendered=section_texts[MEMORY_SECTION],
                details={},
            ),
            RELEVANT_MEMORY_SECTION: SectionRender(
                raw=relevant_raw,
                budget=len(relevant_raw),
                rendered=relevant_raw,
                details={
                    "selected_notes": [note["text"] for note in selected_notes],
                    "rendered_notes": [note["text"] for note in selected_notes],
                    "selected_count": len(selected_notes),
                    "rendered_count": len(selected_notes),
                    "note_budget": 0,
                },
            ),
            HISTORY_SECTION: SectionRender(
                raw=history_raw, budget=len(history_raw), rendered=history_raw, details={"rendered_entries": []}
            ),
            CURRENT_REQUEST_SECTION: SectionRender(
                raw=section_texts[CURRENT_REQUEST_SECTION],
                budget=0,
                rendered=section_texts[CURRENT_REQUEST_SECTION],
                details={},
            ),
        }

    def _assemble(self, rendered: dict[str, SectionRender]) -> str:
        """按固定顺序拼接段落。

        稳定规则放前面、最新请求放后面，与模型“先读约束再读任务”的顺序一致，也让前缀相同的
        两轮请求共享同一串开头。
        """
        return "\n\n".join([rendered[section].rendered for section in SECTION_ORDER]).strip()

    def _history(self) -> list[dict[str, Any]]:
        """返回会话历史的浅拷贝，避免渲染过程改写调用方持有的列表。"""
        return list(getattr(self.agent, "session", {}).get("history", []))

    def _file_summaries(self) -> dict[str, str]:
        """取出工作记忆里已经沉淀的文件摘要，供历史压缩阶段复用。

        没有记忆对象或没有摘要时返回空字典，历史压缩因此退回逐条摘要而不是报错。
        """
        memory = getattr(self.agent, "memory", None)
        if memory is None or not hasattr(memory, "to_dict"):
            return {}
        summaries: dict[str, str] = {}
        for path, entry in (memory.to_dict().get("file_summaries", {}) or {}).items():
            summary = str((entry or {}).get("summary", "")).strip()
            if summary:
                summaries[str(path)] = summary
        return summaries

    def _metadata(
        self,
        prompt: str,
        rendered: dict[str, SectionRender],
        budgets: dict[str, int],
        reduction_log: list[dict[str, Any]],
        selected_notes: list[dict[str, Any]],
        user_message: str,
        section_texts: dict[str, str],
    ) -> dict[str, Any]:
        """汇总本轮 Prompt 的构成事实。

        段落级信息给出原始长度、分配预算与实际渲染长度三者，三者不相等就说明了“这里发生了
        裁剪”。相关记忆与历史各自附带压缩计数，当前请求永远完整，因此只记录长度。
        """
        section_metadata: dict[str, Any] = {}
        for section in BUDGETED_SECTIONS:
            section_metadata[section] = {
                "raw_chars": rendered[section].raw_chars,
                "budget_chars": int(budgets.get(section, 0)),
                "rendered_chars": rendered[section].rendered_chars,
            }
        section_metadata[CURRENT_REQUEST_SECTION] = {
            "raw_chars": len(section_texts[CURRENT_REQUEST_SECTION]),
            "budget_chars": None,
            "rendered_chars": len(rendered[CURRENT_REQUEST_SECTION].rendered),
        }
        relevant_details = rendered[RELEVANT_MEMORY_SECTION].details
        history_details = rendered[HISTORY_SECTION].details
        return {
            "prompt_chars": len(prompt),
            "prompt_budget_chars": self.total_budget,
            "prompt_over_budget": len(prompt) > self.total_budget,
            "section_order": list(SECTION_ORDER),
            "section_budgets": {
                section: (None if section == CURRENT_REQUEST_SECTION else int(budgets.get(section, 0)))
                for section in SECTION_ORDER
            },
            "sections": section_metadata,
            "budget_reductions": reduction_log,
            "reduction_order": list(self.reduction_order),
            "relevant_memory": {
                "limit": RELEVANT_MEMORY_LIMIT,
                "selected_count": len(selected_notes),
                "selected_notes": [note["text"] for note in selected_notes],
                "selected_sources": [str(note.get("source", "")).strip() for note in selected_notes],
                "selected_kinds": [str(note.get("kind", "episodic")).strip() or "episodic" for note in selected_notes],
                "selected_durable_count": sum(
                    1
                    for note in selected_notes
                    if (str(note.get("kind", "episodic")).strip() or "episodic") == "durable"
                ),
                "raw_chars": rendered[RELEVANT_MEMORY_SECTION].raw_chars,
                "rendered_chars": rendered[RELEVANT_MEMORY_SECTION].rendered_chars,
                "rendered_notes": list(relevant_details.get("rendered_notes", [])),
                "rendered_count": int(relevant_details.get("rendered_count", 0)),
            },
            "history": {
                "raw_chars": rendered[HISTORY_SECTION].raw_chars,
                "rendered_chars": rendered[HISTORY_SECTION].rendered_chars,
                "older_entries_count": int(history_details.get("older_entries_count", 0)),
                "collapsed_duplicate_reads": int(history_details.get("collapsed_duplicate_reads", 0)),
                "reused_file_summary_count": int(history_details.get("reused_file_summary_count", 0)),
                "summarized_tool_count": int(history_details.get("summarized_tool_count", 0)),
            },
            "current_request": {
                "text": user_message,
                "raw_chars": len(user_message),
                "rendered_chars": len(user_message),
                "section_chars": len(rendered[CURRENT_REQUEST_SECTION].rendered),
            },
        }

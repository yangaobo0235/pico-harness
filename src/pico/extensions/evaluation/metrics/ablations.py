"""消融实验：在同一次运行里只关掉某一项能力，看指标怎么动。

这一层有两个对象家族。`measure_feature_ablation_metrics` 配合 `_temporary_feature_flags` 把
`Pico` 的 feature flag 临时改成 `full` / `no_context_reduction` / `no_memory` 三种形态，各组装一次
Prompt 后比较长度、记忆段与收缩次数；`_MemoryExperimentModelClient` 与
`_RecoveryScenarioModelClient` 是两种按 Prompt 内容临场应答的假模型，让 `run_memory_dependency_experiment`
和 `run_recovery_ablation_v2` 在没有网络的前提下复现「记忆在不在」「checkpoint 能不能恢复」的差别。
`run_context_ablation_v2`、`run_memory_ablation_v2`、`run_recovery_ablation_v2` 再把结果落成带
`schema_version` 的 JSON 工件。

边界：这里只做消融，不评判指标好坏（那是 `reporting`），也不消费真实模型——需要真实模型或额外预算的
同名 real 实验属于 `experiments`，只由带 ``real_llm`` marker 的实验调用，默认回归不触发付费请求。每个
``_run_*_variant`` 都在独立临时目录里新建一个 agent，因此重复调用只重复产出、不会串味；代价是同一
variant 的不同轮次之间没有共享现场，跨轮次比较的只有聚合数字。三个 ``run_*_v2`` 对 `experiments` 与
`reporting` 的引用刻意放在函数内部：那两层的入口会反过来用本模块的消融原语，模块级互相 import 会成环。
"""

import json
import tempfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pico.config.models.features import CONTEXT_REDUCTION, MEMORY, RELEVANT_MEMORY
from pico.config.paths import WorkspacePaths
from pico.extensions.evaluation.metrics.aggregates import (
    DEFAULT_CONTEXT_ABLATION_V2_PATH,
    DEFAULT_MEMORY_ABLATION_V2_PATH,
    DEFAULT_RECOVERY_ABLATION_V2_PATH,
    METRICS_SCHEMA_VERSION,
    _safe_mean,
    _safe_ratio,
)
from pico.integrations.llm.providers.fake import FakeModelClient
from pico.runtime.agent.agent import Pico
from pico.runtime.sessions.service import SessionStore
from pico.runtime.workspace.snapshot import WorkspaceContext


@contextmanager
def _temporary_feature_flags(agent: Pico, updates: dict[str, bool]) -> Iterator[None]:
    """临时把 ``updates`` 覆盖到 agent 的 feature flag 上，退出时整份还原成进入前的字典。"""
    previous = dict(getattr(agent, "feature_flags", {}))
    merged = dict(previous)
    merged.update(updates)
    agent.feature_flags = merged
    try:
        yield
    finally:
        agent.feature_flags = previous


def measure_feature_ablation_metrics(agent: Pico, user_message: str) -> dict[str, dict[str, Any]]:
    """让同一个 agent 在三种能力开关下各组装一次 Prompt，返回按 variant 分组的对照数字。

    ``agent`` 是已经装配好的运行时，``user_message`` 是这一轮的请求文本。variant 固定三种：
    ``full``（不改开关）、``no_context_reduction``（关掉 ``context_reduction``）、
    ``no_memory``（同时关掉 ``memory`` 与 ``relevant_memory``）。每个 variant 返回
    ``prompt_chars``、``memory_chars``、``history_chars``、``relevant_selected_count``、
    ``budget_reduction_count`` 与 ``current_request_preserved``；后两项取自 Prompt 元数据里的
    ``relevant_memory.selected_count`` 与 ``budget_reductions`` 列表长度，缺字段按 0 计。

    ``current_request_preserved`` 判定的是 Prompt 是否仍以 ``Current user request:\\n<原请求>`` 结尾，
    也就是收缩只许动历史与记忆、不许吞掉这一轮的请求。开关在 `contextmanager` 退出时还原，因此
    调用之后 agent 仍然处于进入前的配置。

    这里不重跑 `ask()`，只看组装结果：一次真实请求会写会话、落工件并消耗模型预算，那会污染对比。
    """
    variants = {
        "full": {},
        "no_context_reduction": {CONTEXT_REDUCTION: False},
        "no_memory": {MEMORY: False, RELEVANT_MEMORY: False},
    }
    results: dict[str, dict[str, Any]] = {}
    for name, updates in variants.items():
        with _temporary_feature_flags(agent, updates):
            prompt, metadata = agent._build_prompt_and_metadata(user_message)
        results[name] = {
            "prompt_chars": int(metadata.get("prompt_chars", 0)),
            "memory_chars": int(metadata.get("sections", {}).get("memory", {}).get("rendered_chars", 0)),
            "history_chars": int(metadata.get("sections", {}).get("history", {}).get("rendered_chars", 0)),
            "relevant_selected_count": int(metadata.get("relevant_memory", {}).get("selected_count", 0)),
            "budget_reduction_count": len(metadata.get("budget_reductions", [])),
            "current_request_preserved": prompt.endswith(f"Current user request:\n{user_message}"),
        }
    return results


class _MemoryExperimentModelClient(FakeModelClient):
    """按「事实有没有出现在 Prompt 里」来回答的假模型，用来量化记忆缺失时代价。

    它把一次会话分成 bootstrap 与提问两段：第一段固定发起一次 ``read_file`` 让事实进入工作记忆，
    随后回答 ``Done.``；提问阶段先在 Prompt 的 ``Memory:`` 与 ``Relevant memory:`` 两段里找期望事实，
    命中就直接答对，没命中则改发一次 ``read_file`` 并把 ``followup_reads`` 加一。这样
    「靠记忆答对」和「被迫重读才答对」在计数上可分，而不需要真实模型。

    它不认识工具协议之外的任何语义，也不模拟 token 数与延时。
    """

    def __init__(self, expected_fact: object, filename: object) -> None:
        super().__init__([])
        self.expected_fact = str(expected_fact).strip().lower()
        self.filename = str(filename).strip()
        self.phase = "bootstrap_tool"
        self.followup_reads = 0

    def complete(self, prompt: str, max_new_tokens: int, **kwargs: Any) -> str:
        """按当前 ``phase`` 返回一条脚本化输出，并推进到下一段。"""
        del max_new_tokens, kwargs
        self.prompts.append(prompt)
        self.last_completion_metadata = {}
        if self.phase == "bootstrap_tool":
            self.phase = "bootstrap_final"
            return f'<tool>{{"name":"read_file","args":{{"path":"{self.filename}","start":1,"end":20}}}}</tool>'
        if self.phase == "bootstrap_final":
            self.phase = "question"
            return "<final>Done.</final>"
        if self.phase == "question":
            prompt_lower = prompt.lower()
            memory_view = ""
            if "memory:" in prompt_lower and "\n\nrelevant memory:" in prompt_lower:
                memory_view = prompt_lower.split("memory:", 1)[1].split("\n\nrelevant memory:", 1)[0]
            relevant_view = ""
            if "relevant memory:" in prompt_lower and "\n\ntranscript:" in prompt_lower:
                relevant_view = prompt_lower.split("relevant memory:", 1)[1].split("\n\ntranscript:", 1)[0]
            if self.expected_fact in memory_view or self.expected_fact in relevant_view:
                return f"<final>{self.expected_fact.capitalize()}.</final>"
            self.phase = "question_after_read"
            self.followup_reads += 1
            return f'<tool>{{"name":"read_file","args":{{"path":"{self.filename}","start":1,"end":20}}}}</tool>'
        if self.phase == "question_after_read":
            self.phase = "done"
            return f"<final>{self.expected_fact.capitalize()}.</final>"
        return f"<final>{self.expected_fact.capitalize()}.</final>"


def _build_memory_experiment_agent(workspace_root: Path, expected_fact: object, filename: object) -> Pico:
    """在 ``workspace_root`` 装配一个由「按 Prompt 内容应答」的假模型驱动的 `Pico`，用于记忆消融。"""
    workspace = WorkspaceContext.build(workspace_root)
    store = SessionStore(WorkspacePaths(workspace_root).sessions_dir)
    return Pico(
        model_client=_MemoryExperimentModelClient(expected_fact, filename),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
    )


def _set_irrelevant_memory(agent: Pico) -> None:
    """把工作记忆换成一条与事实无关的笔记，制造「记忆开着但没用」的第三种对照。"""
    state = agent.memory.to_dict()
    state["episodic_notes"] = [
        {
            "text": "team mascot is blue",
            "tags": ["unrelated"],
            "source": "other.txt",
            "created_at": "2026-04-08T10:00:00+00:00",
            "note_index": 0,
        }
    ]
    state["notes"] = ["team mascot is blue"]
    state["file_summaries"] = {}
    agent.memory.state = state
    agent.session["memory"] = agent.memory.to_dict()


def _run_memory_variant(mode: str) -> dict[str, Any]:
    """在独立临时目录里跑一遍「读事实 → 提问」，返回该 variant 的单轮结果。"""
    with tempfile.TemporaryDirectory(prefix="pico-memory-experiment-") as temp_dir:
        workspace_root = Path(temp_dir)
        (workspace_root / "README.md").write_text("demo\n", encoding="utf-8")
        (workspace_root / "facts.txt").write_text("deploy key is red\n", encoding="utf-8")
        agent = _build_memory_experiment_agent(workspace_root, "deploy key is red", "facts.txt")
        assert agent.ask("Read facts.txt and remember the key fact.") == "Done."

        if mode == "memory_off":
            agent.feature_flags[MEMORY] = False
            agent.feature_flags[RELEVANT_MEMORY] = False
        elif mode == "memory_irrelevant":
            _set_irrelevant_memory(agent)

        result = agent.ask("What color is the deploy key?")
        task_state = agent.current_task_state
        model_client = agent.model_client
        return {
            "correct": result.strip().lower() == "deploy key is red.",
            "tool_steps": int(task_state.tool_steps),
            "attempts": int(task_state.attempts),
            "repeated_reads": int(getattr(model_client, "followup_reads", 0)),
        }


def run_memory_dependency_experiment(repetitions: int = 3) -> dict[str, dict[str, Any]]:
    """重复跑 ``repetitions`` 轮记忆消融，返回 ``memory_on`` / ``memory_off`` / ``memory_irrelevant`` 三组汇总。

    每个 variant 的汇总含 ``repeated_reads``（该组追问阶段重读次数的总和）、``avg_tool_steps``、
    ``avg_attempts`` 与 ``correct_rate``。``repetitions`` 默认 3，会先 `int()` 兜底，因此命令行传字符串
    也能用；传 0 时三组都没有样本，均值与比例按 `_safe_mean`、`_safe_ratio` 的口径给出 ``0.0``，
    而不是报错。

    每轮都在新建的临时 workspace 里进行，重复调用只会重复产出同样口径的数字，不会读到上一轮的残留
    状态。这里不记录 Prompt 文本，也不判断「记忆是否真的被用到」——那需要真实模型，属于
    `experiments` 里的 real 变体；本函数只用假模型证明「关掉记忆要付重读的代价」。
    """
    variants: dict[str, list[dict[str, Any]]] = {
        "memory_on": [],
        "memory_off": [],
        "memory_irrelevant": [],
    }
    for _ in range(int(repetitions)):
        for variant in variants:
            variants[variant].append(_run_memory_variant(variant))

    results: dict[str, dict[str, Any]] = {}
    for variant, rows in variants.items():
        results[variant] = {
            "repeated_reads": sum(row["repeated_reads"] for row in rows),
            "avg_tool_steps": _safe_mean(row["tool_steps"] for row in rows),
            "avg_attempts": _safe_mean(row["attempts"] for row in rows),
            "correct_rate": _safe_ratio(sum(1 for row in rows if row["correct"]), len(rows)),
        }
    return results


class _RecoveryScenarioModelClient(FakeModelClient):
    """只在 Prompt 同时含齐所有必需片段时才确认恢复成功的假模型。

    它把「恢复状态有没有被重建出来」翻译成一次字符串包含检查：``required_fragments`` 全部出现才答
    ``success_answer``，否则答 ``missing recovery state.``。片段一律按小写比较，因为检查发生在
    Prompt 的小写副本上。

    它不解析工具调用、也不推进 ``phase``，因此恢复实验衡量的是 checkpoint 文本是否重新进入
    Prompt，而不是模型能否多走一步。
    """

    def __init__(self, required_fragments: Iterable[str], success_answer: object) -> None:
        super().__init__([])
        self.required_fragments = [str(fragment).lower() for fragment in required_fragments]
        self.success_answer = str(success_answer)

    def complete(self, prompt: str, max_new_tokens: int, **kwargs: Any) -> str:
        """片段齐全时返回 ``success_answer``，否则返回缺失提示。"""
        del max_new_tokens, kwargs
        self.prompts.append(prompt)
        self.last_completion_metadata = {}
        prompt_lower = str(prompt).lower()
        if all(fragment in prompt_lower for fragment in self.required_fragments):
            return f"<final>{self.success_answer}</final>"
        return "<final>missing recovery state.</final>"


#: 恢复消融的任务表：``setup`` 决定要造出哪种现场，``required_fragments`` 决定恢复文本必须留下什么。
RECOVERY_ABLATION_TASKS: list[dict[str, Any]] = [
    {
        "id": "checkpoint_resume_goal",
        "category": "checkpoint_resume",
        "setup": "checkpoint_resume",
        "required_fragments": [
            "task checkpoint:",
            "current goal: resume the benchmark task",
            "next step: apply the locked change",
        ],
    },
    {
        "id": "checkpoint_resume_files",
        "category": "checkpoint_resume",
        "setup": "checkpoint_resume",
        "required_fragments": [
            "task checkpoint:",
            "current goal: continue from the latest benchmark checkpoint",
            "key files: sample.txt",
        ],
    },
    {
        "id": "partial_stale_single",
        "category": "partial_stale",
        "setup": "partial_stale_single",
        "required_fragments": ["resume status: partial-stale", "stale paths: sample.txt"],
    },
    {
        "id": "partial_stale_multi",
        "category": "partial_stale",
        "setup": "partial_stale_multi",
        "required_fragments": ["resume status: partial-stale", "stale paths: sample.txt, notes.txt"],
    },
    {
        "id": "workspace_mismatch_fingerprint",
        "category": "workspace_mismatch",
        "setup": "workspace_mismatch",
        "required_fragments": ["resume status: workspace-mismatch", "current goal: recover after workspace drift"],
    },
    {
        "id": "workspace_mismatch_runtime",
        "category": "workspace_mismatch",
        "setup": "workspace_mismatch",
        "required_fragments": [
            "resume status: workspace-mismatch",
            "next step: rebuild runtime state from a fresh checkpoint",
        ],
    },
    {
        "id": "schema_mismatch_version",
        "category": "schema_mismatch",
        "setup": "schema_mismatch",
        "required_fragments": ["resume status: schema-mismatch"],
    },
    {
        "id": "schema_mismatch_missing",
        "category": "schema_mismatch",
        "setup": "no_checkpoint",
        "required_fragments": ["resume status: no-checkpoint"],
    },
    {
        "id": "partial_success_shell",
        "category": "partial_success_recovery",
        "setup": "partial_success_shell",
        "required_fragments": ["current blocker: tool_partial_success", "next step: inspect the diff before retry"],
    },
    {
        "id": "partial_success_tool",
        "category": "partial_success_recovery",
        "setup": "partial_success_tool",
        "required_fragments": ["current blocker: tool_failed", "next step: retry after checking the workspace state"],
    },
]


def _build_recovery_agent(workspace_root: Path, required_fragments: Iterable[str]) -> Pico:
    """装配一个只依赖恢复片段的 agent，``max_steps`` 固定为 4 以压住单轮成本。"""
    workspace = WorkspaceContext.build(workspace_root)
    store = SessionStore(WorkspacePaths(workspace_root).sessions_dir)
    return Pico(
        model_client=_RecoveryScenarioModelClient(required_fragments, "recovery state restored."),
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        max_steps=4,
    )


def _apply_recovery_setup(agent: Pico, task: dict[str, Any], workspace_root: str | Path) -> None:
    """按 ``task["setup"]`` 造出对应现场：写入 fixture、伪造 checkpoint，并把会话落盘。

    六个分支各对应一类恢复结论：``checkpoint_resume`` 造一份现场完好的 checkpoint；
    ``partial_stale_single`` / ``partial_stale_multi`` 先记下文件摘要再改写文件内容，让新鲜度必然过期；
    ``workspace_mismatch`` 故意写一个过期的 ``workspace_fingerprint``；``schema_mismatch`` 用
    ``legacy-v0``；``no_checkpoint`` 干脆删掉整段 checkpoint。``partial_success_shell`` 与
    ``partial_success_tool`` 只补一个带 blocker 的 checkpoint。

    未识别的 ``setup`` 静默什么都不做，此时 agent 会以 ``no-checkpoint`` 起步——这与「现场本来就没有
    checkpoint」是同一种情况，不需要额外报错。这里只准备现场不发起请求，判定留给 `_run_recovery_task_variant`。
    """
    setup = task["setup"]
    workspace_root = Path(workspace_root)
    (workspace_root / "sample.txt").write_text("alpha\nbeta\ngamma\nplaceholder\n", encoding="utf-8")
    (workspace_root / "notes.txt").write_text("note-one\nnote-two\n", encoding="utf-8")
    agent.session["memory"] = agent.memory.to_dict()

    if setup == "checkpoint_resume":
        agent.memory.remember_file("sample.txt")
        agent.session["memory"] = agent.memory.to_dict()
        agent.session["checkpoints"] = {
            "current_id": "ckpt_resume",
            "items": {
                "ckpt_resume": {
                    "checkpoint_id": "ckpt_resume",
                    "parent_checkpoint_id": "",
                    "schema_version": "phase1-v1",
                    "created_at": "2026-04-15T08:00:00+00:00",
                    "current_goal": "Resume the benchmark task"
                    if task["id"] == "checkpoint_resume_goal"
                    else "Continue from the latest benchmark checkpoint",
                    "completed": ["Read sample.txt"],
                    "excluded": [],
                    "current_blocker": "",
                    "next_step": "Apply the locked change"
                    if task["id"] == "checkpoint_resume_goal"
                    else "Continue from remembered file anchors",
                    "key_files": [{"path": "sample.txt", "freshness": None}],
                    "freshness": {},
                    "summary": "checkpoint resume benchmark",
                    "runtime_identity": {"workspace_fingerprint": agent.workspace.fingerprint()},
                }
            },
        }
        if task["id"] == "checkpoint_resume_files":
            agent.session["checkpoints"]["items"]["ckpt_resume"]["key_files"] = [
                {"path": "sample.txt", "freshness": None}
            ]
        agent.session_store.save(agent.session)
        return

    if setup in {"partial_stale_single", "partial_stale_multi"}:
        agent.memory.set_file_summary("sample.txt", "sample.txt: cached benchmark summary")
        agent.memory.remember_file("sample.txt")
        sample_freshness = agent.memory.to_dict()["file_summaries"]["sample.txt"]["freshness"]
        key_files = [{"path": "sample.txt", "freshness": sample_freshness}]
        freshness = {"sample.txt": sample_freshness}
        if setup == "partial_stale_multi":
            agent.memory.set_file_summary("notes.txt", "notes.txt: cached note summary")
            agent.memory.remember_file("notes.txt")
            notes_freshness = agent.memory.to_dict()["file_summaries"]["notes.txt"]["freshness"]
            key_files.append({"path": "notes.txt", "freshness": notes_freshness})
            freshness["notes.txt"] = notes_freshness
        agent.session["memory"] = agent.memory.to_dict()
        agent.session["checkpoints"] = {
            "current_id": "ckpt_stale",
            "items": {
                "ckpt_stale": {
                    "checkpoint_id": "ckpt_stale",
                    "parent_checkpoint_id": "",
                    "schema_version": "phase1-v1",
                    "created_at": "2026-04-15T08:00:00+00:00",
                    "current_goal": "Recover from stale benchmark summaries",
                    "completed": [],
                    "excluded": [],
                    "current_blocker": "",
                    "next_step": "Re-anchor the stale summaries",
                    "key_files": key_files,
                    "freshness": freshness,
                    "summary": "partial stale benchmark",
                    "runtime_identity": {"workspace_fingerprint": agent.workspace.fingerprint()},
                }
            },
        }
        agent.session_store.save(agent.session)
        # 先落 checkpoint 再改写文件：新鲜度的过期必须由这次改写造成，而不是构造时就对不上。
        (workspace_root / "sample.txt").write_text("alpha\nbeta\nstale-shifted\nplaceholder\n", encoding="utf-8")
        if setup == "partial_stale_multi":
            (workspace_root / "notes.txt").write_text("note-one\nnote-two-shifted\n", encoding="utf-8")
        return

    if setup == "workspace_mismatch":
        agent.session["checkpoints"] = {
            "current_id": "ckpt_workspace",
            "items": {
                "ckpt_workspace": {
                    "checkpoint_id": "ckpt_workspace",
                    "parent_checkpoint_id": "",
                    "schema_version": "phase1-v1",
                    "created_at": "2026-04-15T08:00:00+00:00",
                    "current_goal": "Recover after workspace drift",
                    "completed": [],
                    "excluded": [],
                    "current_blocker": "",
                    "next_step": "Rebuild runtime state from a fresh checkpoint",
                    "key_files": [],
                    "freshness": {},
                    "summary": "workspace mismatch benchmark",
                    "runtime_identity": {"workspace_fingerprint": "outdated-workspace-fingerprint"},
                }
            },
        }
        agent.session_store.save(agent.session)
        return

    if setup == "schema_mismatch":
        agent.session["checkpoints"] = {
            "current_id": "ckpt_schema",
            "items": {
                "ckpt_schema": {
                    "checkpoint_id": "ckpt_schema",
                    "parent_checkpoint_id": "",
                    "schema_version": "legacy-v0",
                    "created_at": "2026-04-15T08:00:00+00:00",
                    "current_goal": "Recover after schema mismatch",
                    "completed": [],
                    "excluded": [],
                    "current_blocker": "",
                    "next_step": "Migrate the stale checkpoint",
                    "key_files": [],
                    "freshness": {},
                    "summary": "schema mismatch benchmark",
                    "runtime_identity": {"workspace_fingerprint": agent.workspace.fingerprint()},
                }
            },
        }
        agent.session_store.save(agent.session)
        return

    if setup == "no_checkpoint":
        agent.session.pop("checkpoints", None)
        agent.session_store.save(agent.session)
        return

    if setup in {"partial_success_shell", "partial_success_tool"}:
        blocker = "tool_partial_success" if setup == "partial_success_shell" else "tool_failed"
        next_step = (
            "Inspect the diff before retry"
            if setup == "partial_success_shell"
            else "Retry after checking the workspace state"
        )
        agent.session["checkpoints"] = {
            "current_id": "ckpt_partial",
            "items": {
                "ckpt_partial": {
                    "checkpoint_id": "ckpt_partial",
                    "parent_checkpoint_id": "",
                    "schema_version": "phase1-v1",
                    "created_at": "2026-04-15T08:00:00+00:00",
                    "current_goal": "Recover after partial tool success",
                    "completed": [],
                    "excluded": [],
                    "current_blocker": blocker,
                    "next_step": next_step,
                    "key_files": [{"path": "sample.txt", "freshness": None}],
                    "freshness": {},
                    "summary": "partial success benchmark",
                    "runtime_identity": {"workspace_fingerprint": agent.workspace.fingerprint()},
                }
            },
        }
        agent.session_store.save(agent.session)


def _run_recovery_task_variant(task: dict[str, Any], variant: str) -> dict[str, Any]:
    """跑一次恢复任务的单个 variant，从 report 与 trace 里读出恢复结论，而不是靠答案猜。"""
    with tempfile.TemporaryDirectory(prefix="pico-recovery-ablation-") as temp_dir:
        workspace_root = Path(temp_dir)
        (workspace_root / "README.md").write_text("demo\n", encoding="utf-8")
        agent = _build_recovery_agent(workspace_root, task["required_fragments"])
        _apply_recovery_setup(agent, task, workspace_root)
        if variant == "resume_disabled":
            agent.session.pop("checkpoints", None)
            agent.session_store.save(agent.session)
        final_answer = agent.ask("Continue the recovery task.")
        report = agent.run_store.load_report(agent.current_task_state.run_id)
        trace = [
            json.loads(line)
            for line in agent.run_store.trace_path(agent.current_task_state).read_text(encoding="utf-8").splitlines()
        ]
        resume_status = str(report.get("prompt_metadata", {}).get("resume_status", ""))
        stale_reanchored = any(
            event.get("event") == "checkpoint_created" and event.get("trigger") == "freshness_mismatch"
            for event in trace
        )
        workspace_drift_detected = any(event.get("event") == "runtime_identity_mismatch" for event in trace)
        invalid_resume = task["category"] in {"partial_stale", "workspace_mismatch", "schema_mismatch"}
        return {
            "task_id": task["id"],
            "category": task["category"],
            "variant": variant,
            "resume_status": resume_status,
            "resume_succeeded": final_answer == "recovery state restored.",
            "stale_reanchored": stale_reanchored,
            "workspace_drift_detected": workspace_drift_detected,
            "false_accept": invalid_resume and resume_status == "full-valid",
            "final_answer": final_answer,
        }


def _recovery_variant_summary(rows: Iterable[dict[str, Any]]) -> dict[str, float]:
    """把一组恢复记录压成四个比率，分母按各自类别的记录数算。"""
    rows = list(rows)
    stale_rows = [row for row in rows if row["category"] == "partial_stale"]
    drift_rows = [row for row in rows if row["category"] == "workspace_mismatch"]
    invalid_rows = [
        row for row in rows if row["category"] in {"partial_stale", "workspace_mismatch", "schema_mismatch"}
    ]
    return {
        "resume_success_rate": _safe_ratio(sum(1 for row in rows if row["resume_succeeded"]), len(rows)),
        "stale_reanchor_rate": _safe_ratio(sum(1 for row in stale_rows if row["stale_reanchored"]), len(stale_rows)),
        "workspace_drift_detection_rate": _safe_ratio(
            sum(1 for row in drift_rows if row["workspace_drift_detected"]), len(drift_rows)
        ),
        "resume_false_accept_rate": _safe_ratio(
            sum(1 for row in invalid_rows if row["false_accept"]), len(invalid_rows)
        ),
    }


def _captured_at() -> str:
    """给出 UTC 时刻的 ISO-8601 字符串，结尾保持 ``Z`` 以沿用历史工件的时间戳写法。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_context_ablation_v2(
    artifact_path: str | Path = DEFAULT_CONTEXT_ABLATION_V2_PATH,
    repetitions: int = 5,
) -> dict[str, Any]:
    """跑一遍合成上下文压力矩阵，并把结果落成 ``context-ablation-v2`` 工件。

    ``artifact_path`` 默认 `DEFAULT_CONTEXT_ABLATION_V2_PATH`，父目录不存在时会被创建，同一路径重复
    运行直接覆盖旧工件；``repetitions`` 默认 5，透传给 `run_context_stress_matrix`。工件字段为
    ``schema_version``、``artifact_type``、``captured_at``、``config_count``、``configs`` 与 ``summary``，
    后三个字段原样取自实验结果，不在这里二次加工。

    返回写进磁盘的那份 payload。矩阵构造与落盘工具分别属于 `experiments` 与 `reporting`，两者都会
    反过来用本模块的消融原语，因此这里在函数内部 import 以避免模块级成环。
    """
    from pico.extensions.evaluation.metrics.experiments import run_context_stress_matrix
    from pico.extensions.evaluation.metrics.reporting import _write_json_artifact

    payload = run_context_stress_matrix(repetitions=repetitions)
    artifact = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "artifact_type": "context-ablation-v2",
        "captured_at": _captured_at(),
        "config_count": payload["config_count"],
        "configs": payload["configs"],
        "summary": payload["summary"],
    }
    return _write_json_artifact(artifact_path, artifact)


def run_memory_ablation_v2(
    artifact_path: str | Path = DEFAULT_MEMORY_ABLATION_V2_PATH,
    repetitions: int = 5,
) -> dict[str, Any]:
    """跑一遍大规模记忆消融并把结果落成 ``memory-ablation-v2`` 工件。

    ``artifact_path`` 默认 `DEFAULT_MEMORY_ABLATION_V2_PATH`，重复运行覆盖同名工件；``repetitions``
    默认 5，表示每个任务在每个 variant 下重复几次。工件带 ``schema_version``、``artifact_type``、
    ``captured_at``、``task_count``、``runs_per_variant``、``category_counts``、``variants`` 与原始
    ``rows``，其中 ``variants`` 保留 `run_large_scale_memory_experiment` 给出的全部口径，本层不再换算。

    与 `run_context_ablation_v2` 同理，实验构造与落盘工具在函数内部 import。
    """
    from pico.extensions.evaluation.metrics.experiments import run_large_scale_memory_experiment
    from pico.extensions.evaluation.metrics.reporting import _write_json_artifact

    payload = run_large_scale_memory_experiment(repetitions=repetitions)
    artifact = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "artifact_type": "memory-ablation-v2",
        "captured_at": _captured_at(),
        "task_count": payload["task_count"],
        "runs_per_variant": payload["runs_per_variant"],
        "category_counts": payload["category_counts"],
        "variants": payload["variants"],
        "rows": payload["rows"],
    }
    return _write_json_artifact(artifact_path, artifact)


def run_recovery_ablation_v2(
    artifact_path: str | Path = DEFAULT_RECOVERY_ABLATION_V2_PATH,
    repetitions: int = 3,
) -> dict[str, Any]:
    """对 `RECOVERY_ABLATION_TASKS` 跑 ``resume_enabled`` 与 ``resume_disabled`` 对照并落成工件。

    ``artifact_path`` 默认 `DEFAULT_RECOVERY_ABLATION_V2_PATH`，重复运行覆盖旧文件；``repetitions``
    默认 3。工件按 variant 分组，每组含 ``summary``（`_recovery_variant_summary` 的四个比率）与逐条
    ``rows``，``task_count`` 取任务表长度而不是运行次数。

    关闭 variant 的做法是直接删掉会话里的 checkpoint 段落，因为这正是「没有恢复状态可用」时 runtime
    实际看到的现场；不改造 runtime 本身，否则测出来的就是改动后的 runtime。落盘工具在 `reporting`，
    而那层会反过来用本模块的消融入口，因此在函数内部 import 以避免模块级成环。
    """
    from pico.extensions.evaluation.metrics.reporting import _write_json_artifact

    repetitions = int(repetitions)
    variants: dict[str, list[dict[str, Any]]] = {"resume_enabled": [], "resume_disabled": []}
    for task in RECOVERY_ABLATION_TASKS:
        for _ in range(repetitions):
            for variant in variants:
                variants[variant].append(_run_recovery_task_variant(task, variant))
    artifact = {
        "schema_version": METRICS_SCHEMA_VERSION,
        "artifact_type": "recovery-ablation-v2",
        "captured_at": _captured_at(),
        "task_count": len(RECOVERY_ABLATION_TASKS),
        "variants": {
            variant: {
                "summary": _recovery_variant_summary(rows),
                "rows": rows,
            }
            for variant, rows in variants.items()
        },
    }
    return _write_json_artifact(artifact_path, artifact)

"""Checkpoint：为一次任务留下可恢复的现场，并判断这份现场还值不值得信。

`create_checkpoint` 在每次工具执行、每次运行结束以及一次失配之后记录“当前目标、卡点、下一步、
关键文件及其新鲜度、runtime 身份”。`evaluate_resume_state` 则在恢复或下一轮开始前重新核对这些
事实：文件是否已经变化、运行配置是否与记录一致，并给出四种状态之一。

这里不决定何时停机，也不改写会话历史；恢复策略的消费方是 Prompt 组装（把 checkpoint 文本并入
稳定前缀）与 Trace 事件。判断标准是“记录与当下是否一致”，不是“任务是否值得继续”。
"""

import uuid
from typing import TYPE_CHECKING, Any

from pico.capabilities.memory.workspace_paths import file_freshness
from pico.contracts.turns import TaskState
from pico.shared.clock import now
from pico.shared.text import clip

if TYPE_CHECKING:
    from pico.runtime.agent.agent import Pico

CHECKPOINT_SCHEMA_VERSION = "phase1-v1"
CHECKPOINT_NONE_STATUS = "no-checkpoint"
CHECKPOINT_FULL_VALID_STATUS = "full-valid"
CHECKPOINT_PARTIAL_STALE_STATUS = "partial-stale"
CHECKPOINT_WORKSPACE_MISMATCH_STATUS = "workspace-mismatch"
CHECKPOINT_SCHEMA_MISMATCH_STATUS = "schema-mismatch"

#: 一次 checkpoint 里逐项比较的 runtime 身份字段。只有列在这里的字段变化才会被判为失配。
RUNTIME_IDENTITY_KEYS = (
    "cwd",
    "model",
    "model_client",
    "approval_policy",
    "read_only",
    "max_steps",
    "max_new_tokens",
    "feature_flags",
    "shell_env_allowlist",
    "workspace_fingerprint",
    "tool_signature",
)

#: summary 行里保留的用户请求长度。
SUMMARY_CLIP = 120


def current_runtime_identity(agent: "Pico") -> dict[str, Any]:
    """采集“现在这套运行配置”的可比较事实。

    包含模型名与 client 类名、审批策略、只读标记、步数与输出预算、能力开关、Shell 环境白名单、
    Workspace 指纹和工具签名。字段全部可 JSON 序列化，因此同一份身份既能进 checkpoint，也能
    直接写进会话文件。
    """
    return {
        "session_id": agent.session.get("id", ""),
        "cwd": str(agent.root),
        "model": str(getattr(agent.model_client, "model", "")),
        "model_client": agent.model_client.__class__.__name__,
        "approval_policy": agent.approval_policy,
        "read_only": bool(agent.read_only),
        "max_steps": int(agent.max_steps),
        "max_new_tokens": int(agent.max_new_tokens),
        "feature_flags": dict(agent.feature_flags),
        "shell_env_allowlist": list(agent.shell_env_allowlist),
        "workspace_fingerprint": getattr(
            getattr(agent, "prefix_state", None), "workspace_fingerprint", agent.workspace.fingerprint()
        ),
        "tool_signature": agent.tool_signature(),
    }


def checkpoint_state(agent: "Pico") -> dict[str, Any]:
    """返回会话里存放 checkpoint 的字典（``current_id`` 与 ``items``）。

    取之前先补齐结构，因此调用方不需要处理旧会话缺少字段的情况；返回的是会话内的同一个对象，
    写入会直接反映到下一次保存。
    """
    agent.ensure_session_shape()
    return agent.session["checkpoints"]


def current_checkpoint(agent: "Pico") -> dict[str, Any] | None:
    """返回最近一次 checkpoint，没有记录时返回 ``None``。

    ``current_id`` 存在但在 ``items`` 里找不到时同样返回 ``None``，这种情况通常来自手工编辑过
    的会话文件；不抛异常，因为“没有可信现场”本身就是恢复流程可以处理的起点。
    """
    state = checkpoint_state(agent)
    checkpoint_id = str(state.get("current_id", "")).strip()
    if not checkpoint_id:
        return None
    return state.get("items", {}).get(checkpoint_id)


def evaluate_resume_state(agent: "Pico") -> dict[str, Any]:
    """核对 checkpoint 与当下事实，返回一份恢复状态说明。

    顺序是：先把过期的文件摘要作废，再取最近 checkpoint，然后分三路判断——schema 版本不符直接
    判为 ``schema-mismatch``（旧格式不做迁移）；否则逐一比对关键文件的新鲜度，再比对 runtime
    身份字段。有文件变陈旧判为 ``partial-stale``，只有身份变化判为 ``workspace-mismatch``，
    两者都没有才是 ``full-valid``。

    结果同时写回会话，供 Prompt 与 Trace 引用；``stale_summary_invalidations`` 保留历史峰值，
    以免一次成功的重算把 earlier 的失效计数抹平。
    """
    previous_resume_state = dict(agent.session.get("resume_state", {}) or {})
    invalidated = agent.invalidate_stale_memory()
    checkpoint = current_checkpoint(agent)
    status = CHECKPOINT_NONE_STATUS
    stale_paths = list(invalidated)
    mismatch_fields: list[str] = []
    if checkpoint:
        if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            status = CHECKPOINT_SCHEMA_MISMATCH_STATUS
        else:
            for item in checkpoint.get("key_files", []):
                path = str(item.get("path", "")).strip()
                if not path:
                    continue
                expected = item.get("freshness")
                current = file_freshness(path, agent.root)
                if expected != current and path not in stale_paths:
                    stale_paths.append(path)
            saved_identity = dict(
                checkpoint.get("runtime_identity", {}) or agent.session.get("runtime_identity", {}) or {}
            )
            current_identity = current_runtime_identity(agent)
            for key in RUNTIME_IDENTITY_KEYS:
                if key not in saved_identity:
                    continue
                if saved_identity.get(key) != current_identity.get(key):
                    mismatch_fields.append(key)
            mismatch_fields.sort()
            if stale_paths:
                status = CHECKPOINT_PARTIAL_STALE_STATUS
            elif mismatch_fields:
                status = CHECKPOINT_WORKSPACE_MISMATCH_STATUS
            else:
                status = CHECKPOINT_FULL_VALID_STATUS

    resume_state = {
        "status": status,
        "stale_paths": stale_paths,
        "runtime_identity_mismatch_fields": mismatch_fields,
        "stale_summary_invalidations": max(
            len(invalidated),
            int(previous_resume_state.get("stale_summary_invalidations", 0))
            if status == CHECKPOINT_PARTIAL_STALE_STATUS
            else 0,
        ),
    }
    agent.session["resume_state"] = resume_state
    agent.session["runtime_identity"] = current_runtime_identity(agent)
    return resume_state


def render_checkpoint_text(agent: "Pico") -> str:
    """把最近一次 checkpoint 渲染成进入 Prompt 的文本块。

    没有记录时返回空串，调用方因此可以原样拼接。文本里显式写出恢复状态与陈旧路径，让模型知道
    “这份现场有多新”，而不是把 checkpoint 当成绝对事实。
    """
    checkpoint = current_checkpoint(agent)
    if not checkpoint:
        return ""
    lines = [
        "Task checkpoint:",
        f"- Resume status: {agent.resume_state.get('status', CHECKPOINT_NONE_STATUS)}",
        f"- Current goal: {checkpoint.get('current_goal', '-') or '-'}",
        f"- Current blocker: {checkpoint.get('current_blocker', '-') or '-'}",
        f"- Next step: {checkpoint.get('next_step', '-') or '-'}",
    ]
    key_files = [
        str(item.get("path", "")).strip()
        for item in checkpoint.get("key_files", [])
        if str(item.get("path", "")).strip()
    ]
    lines.append(f"- Key files: {', '.join(key_files) or '-'}")
    if checkpoint.get("completed"):
        lines.append("- Completed: " + " | ".join(str(item) for item in checkpoint.get("completed", [])))
    if checkpoint.get("excluded"):
        lines.append("- Excluded: " + " | ".join(str(item) for item in checkpoint.get("excluded", [])))
    if agent.resume_state.get("stale_paths"):
        lines.append("- Stale paths: " + ", ".join(agent.resume_state["stale_paths"]))
    summary = str(checkpoint.get("summary", "")).strip()
    if summary:
        lines.append(f"- Summary: {summary}")
    return "\n".join(lines)


def infer_next_step(task_state: TaskState) -> str:
    """从停止状态推断一句“下一步该做什么”。

    已完成的运行不再需要下一步；被步数预算打断的运行需要显式回到 checkpoint 继续；其他情况
    把最后一个工具当作线索，让下一次请求至少不从零开始。这是给模型看的提示文本，不是计划
    系统，也不保证真的可行。
    """
    if task_state.status == "completed":
        return "No next step recorded."
    if task_state.stop_reason == "step_limit_reached":
        return "Resume from the latest checkpoint and continue the task."
    if task_state.last_tool:
        return f"Decide the next action after {task_state.last_tool}."
    return "Continue the task from the latest checkpoint."


def create_checkpoint(
    agent: "Pico",
    task_state: TaskState,
    user_message: str,
    trigger: str,
) -> dict[str, Any]:
    """记录一份新的 checkpoint，并把它设为当前现场。

    ``trigger`` 说明这次记录因何发生（工具执行、运行结束、新鲜度失配、上下文收缩等），它进入
    summary 文本，用于事后区分“同一目标被反复记录”的原因。关键文件取自工作记忆最近读写过的
    路径，新鲜度逐个取样，因此恢复判断比较的是内容而不是修改时间。

    新记录保留 ``parent_checkpoint_id`` 形成一条可回溯的链，但不删除旧记录：一次会话里的
    checkpoint 全部留在会话文件中，便于比较两次现场差异。返回写入的 checkpoint 字典。
    """
    state = checkpoint_state(agent)
    current = current_checkpoint(agent)
    checkpoint_id = "ckpt_" + uuid.uuid4().hex[:8]
    key_files: list[dict[str, Any]] = []
    freshness: dict[str, Any] = {}
    for path in agent.memory.to_dict()["working"]["recent_files"]:
        file_freshness_value = file_freshness(path, agent.root)
        freshness[path] = file_freshness_value
        key_files.append({"path": path, "freshness": file_freshness_value})
    checkpoint = {
        "checkpoint_id": checkpoint_id,
        "parent_checkpoint_id": current.get("checkpoint_id", "") if current else "",
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "created_at": now(),
        "current_goal": str(user_message),
        "completed": [task_state.final_answer] if task_state.final_answer else [],
        "excluded": [],
        "current_blocker": ""
        if str(task_state.stop_reason or "") in ("", "final_answer_returned")
        else str(task_state.stop_reason),
        "next_step": infer_next_step(task_state),
        "key_files": key_files,
        "freshness": freshness,
        "summary": f"{trigger}: {clip(str(user_message), SUMMARY_CLIP)}",
        "runtime_identity": current_runtime_identity(agent),
    }
    state["items"][checkpoint_id] = checkpoint
    state["current_id"] = checkpoint_id
    task_state.checkpoint_id = checkpoint_id
    agent.session["runtime_identity"] = checkpoint["runtime_identity"]
    agent.save_session()
    return checkpoint

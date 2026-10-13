"""Agent 运行时门面：把装配好的能力粘合成一次可请求的 `ask()`。

`Pico` 是包在模型外面的控制循环的持有者：它组织 Prompt 前缀与工作记忆、维护会话与 checkpoint、
按预算组装每一轮请求、把工具调用交给执行层，并把状态、Trace 与报告写到运行目录。真正的迭代
推进在 `pico.runtime.agent.loop`，工具护栏在 `pico.capabilities.tools.executor`，这里保留调用点
需要看到的那些事实。

它不负责：命令行解析（`pico.interfaces.cli`）、创建模型客户端（`pico.bootstrap`）、判断动作
是否被允许（`pico.security`）。实例按一次会话构造，子 Agent 是另一个实例而不是同一实例的嵌套
调用栈。
"""

from pathlib import Path
from typing import Any

from pico.capabilities.memory import promotion
from pico.capabilities.memory.contracts import default_memory_state
from pico.capabilities.memory.service import LayeredMemory
from pico.capabilities.memory.state import summarize_read_result
from pico.capabilities.tools import registry as toolkit
from pico.capabilities.tools.contracts import ToolContext, ToolResult
from pico.capabilities.tools.executor import ToolExecutor
from pico.capabilities.tools.interaction.approvals import confirm_approval
from pico.config.models.features import DEFAULT_FEATURE_FLAGS
from pico.config.models.runtime import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_SHELL_ENV_ALLOWLIST,
    MAX_HISTORY,
)
from pico.contracts.events import TraceEvent
from pico.contracts.turns import TaskState, new_run_id, new_task_id
from pico.observability.runs import RunStore, build_report
from pico.runtime.agent import checkpoints, prompts
from pico.runtime.context.assembler import ContextAssembler
from pico.runtime.context.history_trimmer import summary_text
from pico.runtime.context.instructions import PromptPrefix, build_prompt_prefix, tool_signature
from pico.runtime.sessions import models as session_models
from pico.runtime.sessions.service import SessionStore
from pico.runtime.subagents import manager as subagents
from pico.runtime.workspace import WorkspaceContext, capture_snapshot, diff_snapshots
from pico.security import redaction
from pico.security.authorization import (
    APPROVAL_APPROVED,
    APPROVAL_ASK_USER,
    evaluate_approval,
    filter_shell_env,
)
from pico.security.authorization.workspace_paths import resolve_within_root
from pico.shared.clock import now

REPEATED_CALL_WINDOW = 2
RETRY_HEADROOM_MULTIPLIER = 3
RETRY_HEADROOM_FLOOR = 4


class Pico:
    """一次会话的 Agent 运行时。

    构造参数就是这次运行的全部边界：模型客户端、工作区快照、会话存储、审批策略、步数与输出
    预算、能力开关、允许使用的工具名单，以及需要额外脱敏的环境变量名。实例化即完成装配——
    工具目录、上下文组装器和恢复状态都已就绪，因此第一次 `ask()` 不需要再惰性创建任何东西。

    ``depth`` 与 ``max_depth`` 描述当前实例在委派链里的位置；``read_only`` 会无条件拒绝写入类
    工具，即使审批策略是 ``auto``。
    """

    def __init__(
        self,
        model_client: Any,
        workspace: WorkspaceContext,
        session_store: SessionStore,
        session: dict[str, Any] | None = None,
        run_store: RunStore | None = None,
        approval_policy: str = "ask",
        max_steps: int = 6,
        max_new_tokens: int = 512,
        depth: int = 0,
        max_depth: int = DEFAULT_MAX_DEPTH,
        read_only: bool = False,
        shell_env_allowlist: tuple[str, ...] | None = None,
        secret_env_names: Any = None,
        feature_flags: dict[str, bool] | None = None,
        allowed_tools: Any = None,
    ):
        self.model_client = model_client
        self.workspace = workspace
        self.root = Path(workspace.repo_root)
        self.session_store = session_store
        self.approval_policy = approval_policy
        self.max_steps = max_steps
        self.max_new_tokens = max_new_tokens
        self.depth = depth
        self.max_depth = max_depth
        self.read_only = read_only
        self.shell_env_allowlist = tuple(shell_env_allowlist or DEFAULT_SHELL_ENV_ALLOWLIST)
        self.secret_env_names = {str(name).upper() for name in (secret_env_names or ())}
        self.feature_flags = dict(DEFAULT_FEATURE_FLAGS)
        if feature_flags:
            self.feature_flags.update({str(key): bool(value) for key, value in feature_flags.items()})
        self.allowed_tools = self._normalize_allowed_tools(allowed_tools)
        self.run_store = run_store or RunStore(Path(workspace.repo_root) / ".pico" / "runs")
        self.session = session or self._new_session()
        self.ensure_session_shape()
        self.memory = LayeredMemory(self.session.setdefault("memory", default_memory_state()), workspace_root=self.root)
        self.session["memory"] = self.memory.to_dict()
        self.tools = self._apply_tool_allowlist(self.build_tools())
        self.tool_executor = ToolExecutor(self)
        self.prefix_state = self.build_prefix()
        self.prefix = self.prefix_state.text
        self.context_manager = ContextAssembler(self)
        self.resume_state = self.evaluate_resume_state()
        self.session_path = self.session_store.save(self.session)
        self.current_task_state: TaskState | None = None
        self.current_run_dir: Path | None = None
        self.last_prompt_metadata: dict[str, Any] = {}
        self.last_completion_metadata: dict[str, Any] = {}
        self.last_durable_promotions: list[Any] = []
        self.last_durable_rejections: list[str] = []
        self.last_durable_superseded: list[Any] = []
        self._last_tool_result_metadata: dict[str, Any] = {}
        self._last_prefix_refresh = {
            "workspace_changed": False,
            "prefix_changed": False,
        }

    def _new_session(self) -> dict[str, Any]:
        """构造一份空白会话，ID 与创建时间当场生成。"""
        return session_models.new_session(
            workspace_root=self.workspace.repo_root,
            session_id=session_models.new_session_id(),
            created_at=now(),
        )

    @classmethod
    def from_session(
        cls,
        model_client: Any,
        workspace: WorkspaceContext,
        session_store: SessionStore,
        session_id: str,
        **kwargs: Any,
    ) -> "Pico":
        """从已保存的会话恢复一个运行时。

        会话内容原样交给构造函数补齐，恢复状态在构造过程中重新核对；文件不存在时让
        `FileNotFoundError` 传播到 CLI，由入口翻译成用户能读懂的提示。
        """
        return cls(
            model_client=model_client,
            workspace=workspace,
            session_store=session_store,
            session=session_store.load(session_id),
            **kwargs,
        )

    def ensure_session_shape(self) -> None:
        """补齐会话字典的必要字段。"""
        session_models.ensure_session_shape(self.session)

    def save_session(self) -> Path:
        """把当前会话写回存储并更新 ``session_path``。"""
        self.session_path = self.session_store.save(self.session)
        return self.session_path

    # ------------------------------------------------------------------
    # 运行时身份与 checkpoint
    # ------------------------------------------------------------------

    def current_runtime_identity(self) -> dict[str, Any]:
        """返回当前运行配置的可比较事实。"""
        return checkpoints.current_runtime_identity(self)

    def checkpoint_state(self) -> dict[str, Any]:
        """返回会话内的 checkpoint 容器。"""
        return checkpoints.checkpoint_state(self)

    def current_checkpoint(self) -> dict[str, Any] | None:
        """返回最近一次 checkpoint。"""
        return checkpoints.current_checkpoint(self)

    def evaluate_resume_state(self) -> dict[str, Any]:
        """核对 checkpoint 与当下事实，返回恢复状态说明。"""
        return checkpoints.evaluate_resume_state(self)

    def render_checkpoint_text(self) -> str:
        """渲染进入 Prompt 的 checkpoint 文本。"""
        return checkpoints.render_checkpoint_text(self)

    def create_checkpoint(self, task_state: TaskState, user_message: str, trigger: str) -> dict[str, Any]:
        """记录一份新的 checkpoint。"""
        return checkpoints.create_checkpoint(self, task_state, user_message, trigger)

    def infer_next_step(self, task_state: TaskState) -> str:
        """从停止状态推断下一步提示文本。"""
        return checkpoints.infer_next_step(task_state)

    def invalidate_stale_memory(self) -> list[str]:
        """作废内容已经变化的文件摘要，返回被作废的路径。"""
        invalidated = self.memory.invalidate_stale_file_summaries()
        self.session["memory"] = self.memory.to_dict()
        return invalidated

    # ------------------------------------------------------------------
    # 工具目录
    # ------------------------------------------------------------------

    def build_tools(self) -> dict[str, dict[str, Any]]:
        """按当前上下文装配工具目录。"""
        return toolkit.build_tool_registry(self.tool_context())

    @staticmethod
    def _normalize_allowed_tools(allowed_tools: Any) -> tuple[str, ...] | None:
        """把允许名单规范成非空名称元组，``None`` 表示不限制。

        空序列与含空串的名称都直接拒绝：那通常意味着上游拼错了参数，按“不限制”解释会把一次
        本应收敛权限的运行变成全量开放。
        """
        if allowed_tools is None:
            return None
        normalized = tuple(str(name).strip() for name in allowed_tools)
        if not normalized or any(not name for name in normalized):
            raise ValueError("allowed_tools must be a non-empty sequence of tool names")
        return normalized

    def _apply_tool_allowlist(self, tools: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """把允许名单套到已注册的工具上，未登记名称在启动时就报错。

        校验发生在装配期而不是调用期：名单里的工具名不存在，说明这份配置在任何一次运行里都
        不会生效，等到模型申请它时才报错会让问题看起来像模型行为异常。
        """
        if self.allowed_tools is None:
            return tools
        legal_names = set(toolkit.legal_tool_names())
        unknown = [name for name in self.allowed_tools if name not in legal_names]
        if unknown:
            raise ValueError(f"unknown allowed tool: {', '.join(unknown)}")
        allowed = set(self.allowed_tools)
        return {name: tool for name, tool in tools.items() if name in allowed}

    def tool_signature(self) -> str:
        """返回当前工具目录的声明指纹。"""
        return tool_signature(self.tools)

    def tool_example(self, name: str) -> str:
        """返回某个工具的示例调用文本。"""
        return toolkit.tool_example(name)

    def validate_tool(self, name: str, args: dict[str, Any]) -> None:
        """把通用工具校验和 runtime 级约束串起来。"""
        toolkit.validate_tool(self.tool_context(), name, args)

    def tool_context(self) -> ToolContext:
        """构造注入给工具的窄上下文。"""
        return ToolContext(
            root=self.root,
            path_resolver=self.path,
            shell_env_provider=self.shell_env,
            depth=self.depth,
            max_depth=self.max_depth,
            spawn_delegate=self.spawn_delegate,
        )

    def spawn_delegate(self, args: dict[str, Any]) -> str:
        """创建一个受限子 Agent 完成一次调查。"""
        return subagents.spawn(self, args)

    def tool_list_files(self, args: dict[str, Any]) -> str:
        """直接调用目录列举工具，绕过执行护栏。"""
        return toolkit.bind("list_files", self.tool_context())["run"](args)

    def tool_read_file(self, args: dict[str, Any]) -> str:
        """直接调用文件读取工具，绕过执行护栏。"""
        return toolkit.bind("read_file", self.tool_context())["run"](args)

    def tool_search(self, args: dict[str, Any]) -> str:
        """直接调用搜索工具，绕过执行护栏。"""
        return toolkit.bind("search", self.tool_context())["run"](args)

    def tool_run_shell(self, args: dict[str, Any]) -> str:
        """直接调用 Shell 工具，绕过执行护栏。"""
        return toolkit.bind("run_shell", self.tool_context())["run"](args)

    def tool_write_file(self, args: dict[str, Any]) -> str:
        """直接调用文件写入工具，绕过执行护栏。"""
        return toolkit.bind("write_file", self.tool_context())["run"](args)

    def tool_patch_file(self, args: dict[str, Any]) -> str:
        """直接调用精确替换工具，绕过执行护栏。"""
        return toolkit.bind("patch_file", self.tool_context())["run"](args)

    def tool_delegate(self, args: dict[str, Any]) -> str:
        """直接调用委派工具，绕过执行护栏。"""
        return toolkit.bind("delegate", self.tool_context())["run"](args)

    # ------------------------------------------------------------------
    # 前缀与工作记忆
    # ------------------------------------------------------------------

    def build_prefix(self) -> PromptPrefix:
        """按当前工作区与工具目录构造稳定前缀。"""
        return build_prompt_prefix(workspace=self.workspace, tools=self.tools)

    def _apply_prefix_state(self, prefix_state: PromptPrefix) -> None:
        """把新的前缀状态同步到 ``prefix`` 文本。"""
        self.prefix_state = prefix_state
        self.prefix = prefix_state.text

    def refresh_prefix(self, force: bool = False) -> dict[str, bool]:
        """按需重建稳定前缀，返回本次是否发生变化。

        工作区事实相对稳定，所以整份重新采集一次快照，只在指纹真的变化时才重建前缀文本。
        这一步的存在是为了让 prompt 缓存有意义：每轮都重建前缀会让哈希每轮都不同，缓存永远
        不命中，而全量扫描仓库本身也不便宜。

        返回的 ``workspace_changed`` 与 ``prefix_changed`` 会进入 Trace，用来解释这一轮的缓存键
        为什么和上一轮不同。
        """
        previous_hash = getattr(getattr(self, "prefix_state", None), "hash", None)
        previous_workspace_fingerprint = getattr(getattr(self, "prefix_state", None), "workspace_fingerprint", None)

        refreshed_workspace = WorkspaceContext.build(self.root)
        refreshed_workspace_fingerprint = refreshed_workspace.fingerprint()
        workspace_changed = force or refreshed_workspace_fingerprint != previous_workspace_fingerprint
        if workspace_changed:
            self.workspace = refreshed_workspace

        prefix_state = self.build_prefix() if workspace_changed or force or previous_hash is None else self.prefix_state
        prefix_changed = force or previous_hash != prefix_state.hash
        if prefix_changed:
            self._apply_prefix_state(prefix_state)

        self._last_prefix_refresh = {
            "workspace_changed": workspace_changed,
            "prefix_changed": prefix_changed,
        }
        return dict(self._last_prefix_refresh)

    def memory_text(self) -> str:
        """渲染当前工作记忆文本。"""
        return self.memory.render_memory_text()

    def history_text(self) -> str:
        """渲染一份用于压缩场景的历史摘要。"""
        return summary_text(self.session["history"], limit=MAX_HISTORY)

    def feature_enabled(self, name: str) -> bool:
        """判断某个可选能力在本次运行里是否开启。"""
        return bool(self.feature_flags.get(str(name), False))

    # ------------------------------------------------------------------
    # Prompt 组装
    # ------------------------------------------------------------------

    def prompt(self, user_message: str) -> str:
        """只返回 Prompt 文本，用于“看一眼这轮会发什么”的路径。"""
        prompt, _ = self._build_prompt_and_metadata(user_message)
        return prompt

    def prompt_metadata(self, user_message: str, prompt: str) -> dict[str, Any]:
        """返回本轮 Prompt 的构成说明。

        ``prompt`` 参数保留是为了让调用点读起来对称；构成说明始终由一次真实组装产生，
        不接受外部传入的文本，否则元数据和文本可能来自不同现场。
        """
        _, metadata = self._build_prompt_and_metadata(user_message)
        return metadata

    def _build_prompt_and_metadata(self, user_message: str) -> tuple[str, dict[str, Any]]:
        """刷新前缀与恢复状态，再按预算组装这一轮 Prompt。

        这里把“这轮 prompt 是怎么拼出来的”连同缓存相关状态一起记录下来，后面 Trace 与报告
        才能解释：为什么这一轮 prefix 变了、缓存有没有命中、哪些段落被收缩过。

        附加的字段都属于观察项，不参与模型可见文本的构造；环境里被识别为敏感的变量名会一并
        记录，用于解释工件里出现的占位符。
        """
        refresh = self.refresh_prefix()
        self.resume_state = self.evaluate_resume_state()
        prompt, metadata = self.context_manager.build(user_message)
        metadata.update(
            {
                "prefix_chars": len(self.prefix),
                "workspace_chars": len(self.workspace.text()),
                "memory_chars": len(self.memory_text()),
                "history_chars": len(self.history_text()),
                "request_chars": len(user_message),
                "tool_count": len(self.tools),
                "workspace_docs": len(self.workspace.project_docs),
                "recent_commits": len(self.workspace.recent_commits),
                "prefix_hash": self.prefix_state.hash,
                "prompt_cache_key": self.prefix_state.hash,
                "workspace_fingerprint": self.prefix_state.workspace_fingerprint,
                "tool_signature": self.prefix_state.tool_signature,
                "workspace_changed": refresh["workspace_changed"],
                "prefix_changed": refresh["prefix_changed"],
                "prompt_cache_supported": bool(getattr(self.model_client, "supports_prompt_cache", False)),
                "resume_status": self.resume_state.get("status", checkpoints.CHECKPOINT_NONE_STATUS),
                "stale_summary_invalidations": int(self.resume_state.get("stale_summary_invalidations", 0)),
                "stale_paths": list(self.resume_state.get("stale_paths", [])),
                "runtime_identity_mismatch_fields": list(self.resume_state.get("runtime_identity_mismatch_fields", [])),
            }
        )
        metadata.update(self.detected_secret_env_summary())
        return prompt, metadata

    # ------------------------------------------------------------------
    # 记录与工件
    # ------------------------------------------------------------------

    def record(self, item: dict[str, Any]) -> None:
        """把一条记录加入会话历史并立刻落盘。

        每写一条就保存，是为了让中途被终止的运行仍然留下可复盘的历史；这条路径上不做裁剪，
        完整记录属于会话，压缩只发生在进入 Prompt 之前。
        """
        self.session["history"].append(item)
        self.save_session()

    def emit_trace(self, task_state: TaskState, event: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """向本次运行的 Trace 追加一条事件。

        载荷在写入前整体脱敏，随后补上事件名与时间戳。Trace 是运行中的逐事件时间线，适合回答
        “这一轮 agent 到底做了什么”，因此记录的是阶段事实而不是结论摘要。
        """
        event_payload = redaction.redact_artifact(dict(payload or {}), secret_env_names=self.secret_env_names)
        record = TraceEvent(name=event, created_at=now(), payload=event_payload).to_dict()
        self.run_store.append_trace(task_state, record)
        return record

    def build_report(self, task_state: TaskState) -> dict[str, Any]:
        """汇总一次运行的最终报告。

        报告关注结果与关键指标，和 Trace 的分工是“结果 vs 过程”；Prompt 元数据取最近一次组装
        的结果，长期记忆的三个列表解释本轮沉淀了什么。
        """
        return build_report(
            task_state,
            prompt_metadata=self.last_prompt_metadata,
            durable_promotions=self.last_durable_promotions,
            durable_rejections=self.last_durable_rejections,
            durable_superseded=self.last_durable_superseded,
            redacted_env=self.detected_secret_env_summary(),
        )

    def capture_workspace_snapshot(self) -> dict[str, str]:
        """采集当前 Workspace 的文件摘要。"""
        return capture_snapshot(self.root)

    @staticmethod
    def diff_workspace_snapshots(before: dict[str, str], after: dict[str, str]) -> tuple[list[str], list[str]]:
        """比较两份快照，返回受影响路径与变化摘要。"""
        return diff_snapshots(before, after)

    # ------------------------------------------------------------------
    # 安全与脱敏
    # ------------------------------------------------------------------

    @staticmethod
    def looks_sensitive_env_name(name: str) -> bool:
        """按命名启发式判断环境变量是否像凭证。"""
        return redaction.looks_sensitive_env_name(name)

    def is_secret_env_name(self, name: str) -> bool:
        """结合显式名单判断某个环境变量是否需要脱敏。"""
        return redaction.is_secret_env_name(name, secret_env_names=self.secret_env_names)

    def configured_secret_env_items(self) -> list[tuple[str, str]]:
        """返回显式声明且当前有值的敏感变量条目。"""
        return redaction.configured_secret_env_items(secret_env_names=self.secret_env_names)

    def detected_secret_env_items(self) -> list[tuple[str, str]]:
        """返回被识别为敏感且当前有值的环境变量条目。"""
        return redaction.detected_secret_env_items(secret_env_names=self.secret_env_names)

    def secret_env_summary(self) -> dict[str, Any]:
        """汇总显式声明的敏感变量。"""
        return redaction.secret_env_summary(secret_env_names=self.secret_env_names)

    def detected_secret_env_summary(self) -> dict[str, Any]:
        """汇总自动识别到的敏感变量。"""
        return redaction.detected_secret_env_summary(secret_env_names=self.secret_env_names)

    def redact_text(self, text: object) -> str:
        """把文本里出现的敏感值替换为占位符。"""
        return redaction.redact_text(text, secret_env_names=self.secret_env_names)

    def redact_artifact(self, value: Any, key: str | None = None) -> Any:
        """递归脱敏一件待写工件。"""
        return redaction.redact_artifact(value, key=key, secret_env_names=self.secret_env_names)

    def shell_env(self) -> dict[str, str]:
        """返回执行命令时使用的过滤后环境变量。"""
        return filter_shell_env(self.shell_env_allowlist, self.root)

    def approve(self, name: str, args: dict[str, Any]) -> bool:
        """判断一次高风险调用是否放行。

        只读实例永远拒绝写入类动作，``auto`` 与 ``never`` 都不会读取标准输入；只有 ``ask``
        才真正向终端提问，管道输入结束时按拒绝处理。
        """
        decision = evaluate_approval(self.approval_policy, read_only=self.read_only)
        if decision == APPROVAL_ASK_USER:
            return confirm_approval(name, args)
        return decision == APPROVAL_APPROVED

    def path(self, raw_path: object) -> Path:
        """把工具给出的路径锚定在 Workspace 根之内。"""
        return resolve_within_root(self.root, raw_path)

    # ------------------------------------------------------------------
    # 记忆沉淀
    # ------------------------------------------------------------------

    def update_memory_after_tool(self, name: str, args: dict[str, Any], result: str) -> None:
        """把少量高价值工具结果沉淀进工作记忆。

        不是每个工具结果都值得长期带进下一轮 Prompt。完整结果已经进了 ``history``，这里只挑
        “下一轮大概率还会用到”的事实做提纯：最近读写过哪些文件、某个文件读出来的短摘要。

        读文件生成摘要并记一条笔记；写文件与精确替换会让旧摘要失效，因为内容可能已经变了。
        ``memory`` 能力关闭时整个动作跳过，历史本身不受影响。
        """
        if not self.feature_enabled("memory"):
            return
        path = args.get("path")
        if not path:
            return

        canonical_path = self.memory.canonical_path(path)
        if name in {"read_file", "write_file", "patch_file"}:
            self.memory.remember_file(canonical_path)
        if name == "read_file":
            summary = summarize_read_result(result)
            self.memory.set_file_summary(canonical_path, summary)
            self.memory.append_note(summary, tags=(canonical_path,), source=canonical_path)
        elif name in {"write_file", "patch_file"}:
            self.memory.invalidate_file_summary(canonical_path)

    def note_tool(self, name: str, args: dict[str, Any], result: str) -> None:
        """工具执行完成后的记忆回写入口。"""
        self.update_memory_after_tool(name, args, result)

    def record_process_note_for_tool(self, name: str, metadata: dict[str, Any]) -> None:
        """把失败或部分成功的工具调用记成一条过程笔记。

        过程笔记和事实笔记分开存放（``kind="process"``），因为“这一步失败了，先检查再重试”
        对下一轮决策有用，却不应该被当成项目事实晋升进长期记忆。成功的调用不留笔记，
        否则记忆会被每次正常输出淹没。
        """
        status = str(metadata.get("tool_status", "")).strip()
        if status not in {"partial_success", "error", "rejected"}:
            return
        affected_paths = [str(path).strip() for path in metadata.get("affected_paths", []) if str(path).strip()]
        path_text = ", ".join(affected_paths) or "workspace"
        if status == "partial_success":
            text = f"{name} partial_success on {path_text}; inspect diff before retry"
        elif status == "error":
            text = f"{name} error on {path_text}; check the failure before retry"
        else:
            text = f"{name} rejected; choose a different action before retry"
        tags = ["process", status, *affected_paths]
        self.memory.append_note(text, tags=tuple(tags), source=name, kind="process")
        self.session["memory"] = self.memory.to_dict()

    def reject_durable_reason(self, note_text: str) -> str:
        """返回一条候选笔记不应晋升的原因。"""
        return promotion.reject_reason(note_text)

    def extract_durable_promotions(
        self, user_message: str, final_answer: str
    ) -> tuple[list[tuple[str, str]], list[str]]:
        """从最终答案里抽取可晋升的长期记忆候选。"""
        return promotion.extract_promotions(user_message, final_answer)

    def promote_durable_memory(self, user_message: str, final_answer: str) -> tuple[list[Any], list[str], list[Any]]:
        """执行长期记忆晋升，并记录本轮的晋升、拒绝与被取代结果。"""
        promoted, rejections, superseded = promotion.promote(self, user_message, final_answer)
        self.last_durable_promotions = promoted
        self.last_durable_rejections = rejections
        self.last_durable_superseded = superseded
        return promoted, rejections, superseded

    # ------------------------------------------------------------------
    # 控制循环入口
    # ------------------------------------------------------------------

    def ask(self, user_message: str) -> str:
        """推进一次完整请求，返回模型的最终答案文本。"""
        from pico.runtime.agent.loop import AgentLoop

        return AgentLoop(self).run(user_message)

    def execute_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
        """执行一次工具调用并保留结构化元数据。"""
        result = self.tool_executor.execute(name, args)
        self._last_tool_result_metadata = dict(result.metadata)
        return result

    def run_tool(self, name: str, args: dict[str, Any]) -> str:
        """执行一次工具调用并只返回模型可见文本。

        在 agent 系统里，真正危险的不是“模型会不会想调用工具”，而是“平台有没有在执行前把
        边界守住”。这个方法就是工具层的总闸口：所有来自模型的调用都经过它，模型拿不到直接
        触碰底层函数的路径。失败也以文本返回，让下一轮模型能够消费这份反馈。
        """
        return self.execute_tool(name, args).content

    def repeated_tool_call(self, name: str, args: dict[str, Any]) -> bool:
        """判断最近两次工具调用是否是同一次调用的重复。

        agent 常见的一种坏循环是在没有新信息的情况下反复发起同一调用。这里只挡最简单的形态
        （连续两次同名同参数），因为再往上的“意图重复”需要理解任务语义，那不是执行层能判定的。
        """
        tool_events = [item for item in self.session["history"] if str(item.get("role", "")) == "tool"]
        if len(tool_events) < REPEATED_CALL_WINDOW:
            return False
        recent = tool_events[-REPEATED_CALL_WINDOW:]
        return all(item["name"] == name and item["args"] == args for item in recent)

    @staticmethod
    def new_task_id() -> str:
        """生成任务标识。"""
        return new_task_id()

    @staticmethod
    def new_run_id() -> str:
        """生成运行标识。"""
        return new_run_id()

    def max_attempts(self) -> int:
        """返回本轮允许消耗的模型请求次数上限。

        上限比 ``max_steps`` 宽松，因为格式错误的输出会消耗请求但不消耗工具预算；同时给一个
        下限，避免 ``max_steps`` 很小时模型一次也没有被纠正的机会。
        """
        return max(self.max_steps * RETRY_HEADROOM_MULTIPLIER, self.max_steps + RETRY_HEADROOM_FLOOR)

    # ------------------------------------------------------------------
    # 模型输出解析与会话重置
    # ------------------------------------------------------------------

    @staticmethod
    def parse(raw: object) -> tuple[str, Any]:
        """把模型原始输出解析成 runtime 可执行的动作或最终答案。"""
        return prompts.parse(raw)

    @staticmethod
    def retry_notice(problem: str | None = None) -> str:
        """构造格式错误时的重试提示文本。"""
        return prompts.retry_notice(problem)

    @staticmethod
    def parse_xml_tool(raw: str) -> dict[str, Any] | None:
        """解析 XML 风格工具标签。"""
        return prompts.parse_xml_tool(raw)

    @staticmethod
    def parse_attrs(text: str) -> dict[str, str]:
        """解析标签属性串。"""
        return prompts.parse_attrs(text)

    @staticmethod
    def extract(text: str, tag: str) -> str:
        """取出标签内容并去掉两端空白。"""
        return prompts.extract(text, tag)

    @staticmethod
    def extract_raw(text: str, tag: str) -> str:
        """取出标签内容并保留内部空白。"""
        return prompts.extract_raw(text, tag)

    def reset(self) -> None:
        """清空当前会话的历史与记忆，保留会话身份。

        会话 ID 不变，因此 ``/reset`` 之后 ``--resume`` 仍然能找到同一份文件；checkpoint 保留，
        因为“上一次任务停在哪里”对人工排查仍然有用，只是不会再进入下一轮 Prompt。
        """
        self.session["history"] = []
        self.session["memory"] = default_memory_state()
        self.memory = LayeredMemory(self.session["memory"], workspace_root=self.root)
        self.save_session()

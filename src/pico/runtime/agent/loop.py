"""把一条用户请求推进为模型回复、工具执行和可交付结果的 Agent Loop 核心引擎。

没有 Agent 开发经验时，可以先把这里理解为一次请求的“现场总调度”：它从 Spine 接收
`TurnRequest`，借助 Context Engine 拼出模型本轮可见的历史、Memory 与 Skill，调用
Provider 获得模型输出，再执行模型选择的 Tool。只要模型继续请求工具，这条链路就会
在受限迭代预算内重复；得到最终文本、达到上限或遇到 Provider 错误后，结果再沿 Spine
的单一 `emit` 边界交给 TUI、REPL 或其他出口。

本模块还拥有几条不能被“循环调用模型”这个表面描述掩盖的边界：流式文本与非流式文本
不能重复交付，工具输出过大时要在持久化和上下文窗口处分别收缩，MCP 与 Sandbox 资源
按运行时生命周期启动和关闭，Checkpoint 只为符合策略的 Turn 留下 shadow-git 恢复证据。
阅读时可先看 `AgentLoop.run_turn` 的入口与 `_run_agent_loop` 的迭代，再回到上下文组装、
工具注册、恢复和关闭方法理解各自所有权。
"""

from __future__ import annotations

import asyncio
import re
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from pico.capabilities.memory.consolidation.consolidator import MemoryConsolidator
from pico.capabilities.tools.builtin.ask_user import AskUserTool
from pico.capabilities.tools.builtin.file_search import FindTool, GrepTool
from pico.capabilities.tools.builtin.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from pico.capabilities.tools.builtin.message import MessageTool
from pico.capabilities.tools.builtin.shell import ExecTool
from pico.capabilities.tools.builtin.skill import SkillReadTool
from pico.capabilities.tools.builtin.spawn import SpawnTool
from pico.capabilities.tools.builtin.web import WebFetchTool, WebSearchTool
from pico.capabilities.tools.registry import ToolRegistry
from pico.contracts.messages import Media
from pico.contracts.turns import Origin
from pico.integrations.execution import SandboxConfig, SandboxExecutor, build_executor
from pico.integrations.llm.contracts import LLMProvider, LLMResponse
from pico.observability.tracing import semconv, trace
from pico.runtime.agent.recovery import RecoveryLimits
from pico.runtime.context.budget import TokenBudget
from pico.runtime.context.instructions import ContextBuilder
from pico.runtime.sessions.service import Session, SessionManager
from pico.runtime.subagents import SubagentManager
from pico.shared.persisted_payload import sanitize_persisted_payload
from pico.shared.tokenization import estimate_prompt_tokens

# 刻意在 ``__init__`` 和 ``_assemble_context_messages`` 内延迟导入 ``pico.runtime.context``，以打破运行时
# 循环导入：``pico.runtime.agent.__init__`` 急切加载 AgentLoop，而 ``pico.runtime.context.curator``
# 又从 ``pico.runtime.context.instructions`` 导入 ``ContextBuilder``。如果在此模块顶层导入，会重新进入
# 只初始化了一部分的包，并在 ``TurnContext`` 上抛出 ImportError。

if TYPE_CHECKING:
    from pico.capabilities.automation.cron.service import CronService
    from pico.capabilities.memory.contracts import MemoryBackend
    from pico.capabilities.tools.contracts import Tool
    from pico.config.models.features import ContextConfig, MemoryConfig, RuntimeConfig, SkillForgeRouterConfig
    from pico.config.models.runtime import ChannelsConfig, ExecToolConfig
    from pico.contracts.turns import TurnRequest
    from pico.integrations.execution.debug_server import SandboxDebugServer
    from pico.integrations.llm.routing.router import ModelRouter
    from pico.integrations.llm.strategies.base import UsageSnapshot
    from pico.integrations.llm.strategies.registry import StrategyRegistry
    from pico.observability.usage import CallEfficiency
    from pico.runtime.context import ContextEngine
    from pico.runtime.context.factory import ContextEngineFactory
    from pico.runtime.hooks import CompositeHook
    from pico.runtime.scheduling.runner import Drain, Emit, TurnOutcome


from pico.runtime.agent.failures import _is_hard_tool_failure, _is_tool_failure, _loop_break_nudge
from pico.runtime.agent.models import ProviderTurnError, TurnOutcome
from pico.runtime.agent.streaming import _finalize_tool_calls, _merge_tool_call_fragments

__all__ = [
    "AgentLoop",
    "TurnOutcome",
    "ProviderTurnError",
    "_is_tool_failure",
    "_is_hard_tool_failure",
    "_loop_break_nudge",
    "_merge_tool_call_fragments",
    "_finalize_tool_calls",
]


class AgentLoop:
    """统筹一个 Agent Turn 从 Spine 入站到回复出站的核心处理引擎。

    对初学者而言，`AgentLoop` 不是“无限让模型思考”的循环，而是有预算、有资源生命周期、
    有单一交付边界的请求协调器。它依次接收 Spine 消息，使用历史、Memory 和 Skill 构建
    Context，调用 LLM，执行模型发出的 Tool 调用，并把文本、推理增量、工具事件、媒体与
    Usage 送回同一个 `emit`。模型若请求工具，新的工具结果会进入下一次模型调用，直到得到
    最终回答或抵达明确终态。

    实例通常由 Gateway 等 Host 长期持有，因此它同时拥有 ToolRegistry、Context Engine、
    SessionManager、SubagentManager、Sandbox executor、MCP 连接和后台个性化任务。`run`
    只负责把这些运行时资源拉起并保持存活，真正的一轮请求从 `run_turn` 进入；`close` 与
    `stop` 则分别完成异步资源清理和停止保活循环。跨 Turn 的可变状态必须显式按
    `session_key` 隔离，不能把一次请求的恢复或失败计数泄漏给另一段会话。
    """

    _TOOL_RESULT_MAX_CHARS = 16_000
    # 每个 Turn 在上下文溢出成为致命错误前，最多执行的紧急收缩次数。
    _MAX_COMPRESS_RETRIES = 2
    # 紧急收缩时保持完整的最新工具结果数；更旧结果被省略，
    # 因为它们的正文是 Turn 中途上下文增长的主体。
    _SHRINK_KEEP_RECENT_TOOL_RESULTS = 3
    # 工具失败循环打断：同一工具连续确定性失败达到此次数后发出提示；
    # 同时限制每个 Turn 的提示次数，避免提示本身形成循环。
    _LOOP_BREAK_THRESHOLD = 2
    _LOOP_BREAK_MAX = 2

    def __init__(
        self,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 40,
        context_window_tokens: int = 65_536,
        brave_api_key: str | None = None,
        web_proxy: str | None = None,
        exec_config: ExecToolConfig | None = None,
        cron_service: CronService | None = None,
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
        mcp_servers: dict | None = None,
        sandbox_config: SandboxConfig | None = None,
        channels_config: ChannelsConfig | None = None,
        router: "ModelRouter | None" = None,
        strategies: "StrategyRegistry | None" = None,
        call_efficiency: "CallEfficiency | None" = None,
        skill_forge_config: Any = None,
        hooks: "CompositeHook | None" = None,
        now_fn: Callable | None = None,
        context_config: "ContextConfig | None" = None,
        runtime_config: "RuntimeConfig | None" = None,
        interactive: bool = True,
        jina_api_key: str | None = None,
        max_concurrent_subagents: int = 4,
        max_subagent_spawns_per_hour: int = 30,
        disabled_tools: list[str] | None = None,
        tool_search_config: Any = None,
        # 可选的插件 MemoryBackend。None 禁用后端回忆和存储，但保留 Session 和本地 Skill。
        backend: "MemoryBackend | None" = None,
        # 转发给 ``build_context_engine``，供 Memory 通道和本地 Skill 路由器使用。
        memory_config: "MemoryConfig | None" = None,
        skill_forge_router_config: "SkillForgeRouterConfig | None" = None,
        # 已激活插件贡献的工具，由 CLI 通过 ``build_plugin_tools`` 构建，并在
        # ``_register_default_tools`` 中与内置工具一起注册。None 或空列表表示无插件工具，
        # 默认行为不变。
        plugin_tools: "list[Tool] | None" = None,
        empty_recovery: RecoveryLimits | None = None,
        context_engine_factory: "ContextEngineFactory | None" = None,
        state: Path | None = None,
    ):
        from pico.config.models.runtime import ExecToolConfig
        from pico.integrations.llm.strategies.registry import StrategyRegistry
        from pico.observability.usage import CallEfficiency
        from pico.runtime.hooks import CompositeHook

        self.channels_config = channels_config
        self.provider = provider
        self.workspace = workspace
        self.state = state or workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        # 空响应恢复预算。None 表示使用已启用的默认值。
        self._recovery_limits = empty_recovery if empty_recovery is not None else RecoveryLimits()
        self.context_window_tokens = context_window_tokens
        self.brave_api_key = brave_api_key
        self.jina_api_key = jina_api_key
        self.web_proxy = web_proxy
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self.restrict_to_workspace = restrict_to_workspace
        # 旧版注册表继续作为工具列表和基准扩展边界。
        self.strategies = strategies if strategies is not None else StrategyRegistry([])
        self.call_efficiency = call_efficiency or CallEfficiency.disabled()
        # 基准和模拟框架的伪时钟注入点。默认使用墙上时钟，不影响网关和 REPL 等生产路径。
        # 它同时用于会话项时间戳并传入 ContextBuilder，使 LLM 提示词中的 ``Current Time:``
        # 与持久化消息记录的时间保持同步。
        self._now_fn = now_fn or datetime.now

        self.backend: "MemoryBackend | None" = backend
        self.memory_enabled = backend is not None

        # 已激活插件贡献的工具，由 ``_register_default_tools`` 注册到 ToolRegistry。
        self.plugin_tools: "list[Tool]" = list(plugin_tools or [])

        self.context = ContextBuilder(
            workspace,
            state=self.state,
            skill_forge_config=skill_forge_config,
            llm_provider=self.provider,
            now_fn=now_fn,
        )
        self.sessions = session_manager or SessionManager(self.state)
        # 从注册表中排除的工具名称。在默认工具注册和 MCP 连接后均应用，因此可同时限制两组。
        # 供 BCP 等需要严格工具子集的评测框架使用。
        self._disabled_tools = set(disabled_tools or [])
        self._tool_search_config = tool_search_config
        self.tools = ToolRegistry()

        # Context Engine 是唯一的 ContextAssembler。在 self.tools 之后于此构建，使工厂能将
        # ``self.tools.get_definitions`` 捕获为延迟可调用对象；真正的工具注册表内容
        # 稍后由同一构造函数中的 ``_register_default_tools`` 填充。
        #
        # 延迟导入 ``pico.runtime.context`` 的原因见模块顶部关于 ``pico.runtime.agent.__init__`` 循环导入的说明。
        if context_config is None:
            from pico.config.models.features import ContextConfig

            context_config = ContextConfig()
        if context_engine_factory is None:
            from pico.runtime.context import build_context_engine

            context_engine_factory = build_context_engine
        self.context_config = context_config

        self.context_engine: "ContextEngine" = context_engine_factory(
            workspace=workspace,
            config=context_config,
            builder=self.context,
            provider=self.provider,
            model=self.model,
            context_window_tokens=context_window_tokens,
            get_tool_definitions=self.tools.get_definitions,
            now_fn=now_fn,
            # 工厂使用这些参数组装统一的 Memory 和本地 Skill 通道。
            backend=backend,
            memory_config=memory_config,
            skill_forge_router_config=skill_forge_router_config,
            skill_forge_config=skill_forge_config,
        )

        # 运行时约束（第五支柱）。检查点受 policy 和 interactive 联合门控，见 ``_checkpoint_active``。
        # 门禁关闭时，Agent Loop 与基线字节级一致。
        if runtime_config is None:
            from pico.config.models.features import RuntimeConfig

            runtime_config = RuntimeConfig()
        self.runtime_config = runtime_config
        self.interactive = interactive
        self._checkpoint = None
        if self._checkpoint_active(runtime_config.checkpoint.policy, interactive):
            from pico.runtime.agent.checkpoints import CheckpointService

            try:
                self._checkpoint = CheckpointService(
                    workspace,
                    shadow_dir=runtime_config.checkpoint.shadow_dir,
                    state=self.state if self.state != workspace else None,
                )
            except ValueError as exc:
                # shadow_dir 无效（如 ``../escape`` 或绝对路径）时 CheckpointService 拒绝构建。
                # 不因配置笔误让整个 Agent 崩溃；记录日志并禁用安全网，使 Turn 仍可运行。
                logger.warning("runtime.checkpoint disabled — {}", exc)
        # Turn 因迭代上限中断时，保存 session_key -> {"checkpoint_id", "files"}；
        # 下一个 Turn 的恢复提示词会消费它。
        self._pending_recovery: dict[str, dict] = {}

        self._sandbox_config = sandbox_config
        self._owned_ids: set[str] = set()
        self.subagents = SubagentManager(
            provider=self.provider,
            workspace=workspace,
            state=self.state,
            model=self.model,
            brave_api_key=brave_api_key,
            jina_api_key=jina_api_key,
            web_proxy=web_proxy,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
            sandbox_config=sandbox_config,
            owned_ids=self._owned_ids,
            max_concurrent=max_concurrent_subagents,
            max_spawns_per_hour=max_subagent_spawns_per_hour,
        )

        # 执行器此处只同步构建，虚拟机在 _start_executor() 中启动。
        self._executor: SandboxExecutor = build_executor(sandbox_config, workspace, self._owned_ids)
        self._executor_stack: AsyncExitStack | None = None
        self._executor_started: bool = False
        self._executor_start_lock = asyncio.Lock()
        self._debug_server: SandboxDebugServer | None = None

        self.router = router
        self.enable_personalization = False  # 通过 configure_personalization() 设置
        self._running = False
        self._mcp_servers = mcp_servers or {}
        self._mcp_stack: AsyncExitStack | None = None
        self._mcp_connected = False
        self._mcp_connecting = False
        self._processing_lock = asyncio.Lock()
        # 每个已分派 Turn 结束后触发，无论成功、错误还是取消。回调必须低成本且不得抛错。
        self.on_turn_complete: list[Callable[[], None]] = []
        self.memory_consolidator = MemoryConsolidator(
            workspace=self.state,
            provider=self.provider,
            model=self.model,
            sessions=self.sessions,
            context_window_tokens=context_window_tokens,
            build_messages=self.context.build_messages,
            get_tool_definitions=self.tools.get_definitions,
            now_fn=now_fn,
        )

        self._personalization_tasks: set[asyncio.Task[Any]] = set()
        self._personalization_closed = False
        self._close_lock = asyncio.Lock()
        self._closed = False

        # B-3 阶段已移除 L4 外观（``DefaultMemoryEngine`` / ``MemoryEngine`` 抽象基类）。
        # AgentLoop 现在直接持有底层子系统：
        #
        # - ``self.memory_consolidator`` 负责 Markdown 压缩策略，并拥有它构建的 ``MemoryStore``；
        #   需要时通过 ``self.memory_consolidator.store`` 访问。
        # - ``self.context.skills`` 是 :class:`LocalSkillCatalog`，负责常驻 Skill 和 ``# Skills`` 渲染路径。
        #   由 ``context_engine.factory`` 组装的 SkillForgeRouter 栈拥有检索职责。

        # AgentHook 生命周期链。评测 Hook 和调用方 Hook 共享同一个有序接口，
        # 无需按功能定制回调适配器。
        self.hooks: "CompositeHook" = CompositeHook()
        if hooks is not None:
            self.hooks.extend(hooks)

        self._register_default_tools()
        self._apply_disabled_tools()

    def _apply_disabled_tools(self) -> None:
        """从当前注册表移除 ``tools.disabled_tools`` 指定的 Tool。

        这一步必须在 :meth:`_register_default_tools` 注册内置与插件工具后执行，也必须在
        :meth:`_connect_mcp` 动态加入 MCP 工具后再次执行，否则同一黑名单只能覆盖其中一组。
        名称未注册时保持静默：评测配置经常给出比当前构建实际工具更宽的列表，缺失项应当是
        no-op，而不是让 Agent 无法启动。方法原地修改 `ToolRegistry`，没有返回值。
        """
        if not self._disabled_tools:
            return
        for name in self._disabled_tools:
            if self.tools.has(name):
                self.tools.unregister(name)

    def configure_personalization(self, enable: bool) -> None:
        """设置全局四阶段个性化流程开关，该流程受 PAHF 思路启发。

        开启后，一条消息先由 ``classify()`` 判断是否需要询问偏好；需要时在执行前只问一个
        问题并提取、保存答案；随后进入完全不变的普通 Agent Loop；回复完成后再把
        ``post_learn()`` 作为后台任务运行。这样偏好交互围绕主执行链展开，而不是替换它。

        ``enable`` 只是调用方意图，真正状态还受 `memory_enabled` 约束：没有 MemoryBackend
        时无法持久化学习结果，即使传入 ``True`` 也会保持关闭。功能默认禁用，可由配置
        ``agents.defaults.enable_personalization: true`` 开启。方法只更新实例状态并记录日志。
        """
        self.enable_personalization = bool(enable and self.memory_enabled)
        logger.info("Personalization flow: {}", "enabled" if self.enable_personalization else "disabled")

    def _start_personalization_task(self, factory: Callable[[], Awaitable[Any]]) -> None:
        """Delegate start personalization task to its owning execution module."""
        from pico.runtime.agent.resources import start_personalization_task

        return start_personalization_task(self, factory)

    def begin_close(self) -> None:
        """Delegate begin close to its owning execution module."""
        from pico.runtime.agent.resources import begin_close

        return begin_close(self)

    def _register_default_tools(self) -> None:
        """按运行时约束组装并注册 Agent 默认可用的 Tool 集合。

        文件、Shell、Web、消息、子 Agent、提问和可选 Cron Tool 在这里绑定工作区、代理、
        Sandbox executor 等依赖。插件工具随后以 ``replace=True`` 注册，因此插件可有意覆盖
        同名内置实现；渐进式 Tool Search 最后建立，才能看到此前完整目录。MCP Tool 不在
        此处连接，而由 `_connect_mcp` 在首次 Turn 前延迟加入。

        方法只完成注册，不代表所有工具都最终可见：调用方紧接着执行
        `_apply_disabled_tools`，Tool Search 策略也可能按 Turn 缩小暴露集合。若启用 Cron，
        函数内延迟导入是为避开 `pico.runtime.agent.__init__` 的循环导入边界。
        """
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        for cls in (ReadFileTool, WriteFileTool, EditFileTool, ListDirTool, GrepTool, FindTool):
            self.tools.register(cls(workspace=self.workspace, allowed_dir=allowed_dir))
        self.tools.register(SkillReadTool(self.context.skills))
        self.tools.register(
            ExecTool(
                working_dir=str(self.workspace),
                timeout=self.exec_config.timeout,
                restrict_to_workspace=self.restrict_to_workspace,
                path_append=self.exec_config.path_append,
                executor=self._executor,
            )
        )
        self.tools.register(WebSearchTool(api_key=self.brave_api_key, proxy=self.web_proxy))
        self.tools.register(WebFetchTool(api_key=self.jina_api_key, proxy=self.web_proxy))
        self.tools.register(MessageTool())
        self.tools.register(SpawnTool(manager=self.subagents))
        # QuestionBroker 按传输层为单例；当传输层（TUI RPC 服务器或网关 hub）存在后，
        # 通过 set_broker 延迟绑定。
        self.tools.register(AskUserTool())
        if self.cron_service:
            # 延迟导入：CronTool 所在模块会导入 pico.capabilities.tools.contracts，触发 pico.runtime.agent.__init__，
            # 后者又导入当前循环模块。在函数作用域导入可打破循环，因为执行
            # _register_default_tools 时 loop.py 已完全加载。
            from pico.capabilities.tools.builtin.cron import CronTool

            self.tools.register(CronTool(self.cron_service))

        # 插件贡献的工具最后注册，使插件在有意提供同名工具时能覆盖内置实现。
        # 随后仍会运行 ``_apply_disabled_tools``，因此任何工具都可被移除。
        for tool in self.plugin_tools:
            self.tools.register(tool, replace=True)

        # 渐进式工具披露最后注册，使其搜索目录覆盖上方全部内置和插件工具。
        # MCP 工具稍后在 ``_connect_mcp`` 中加入；策略每个 Turn 都重读注册表，因此能自动获取。
        cfg = self._tool_search_config
        if cfg is not None and cfg.enabled:
            from pico.capabilities.tools.tool_search import (
                DEFAULT_ALWAYS_VISIBLE,
                ToolCallTool,
                ToolSearchController,
                ToolSearchStrategy,
                ToolSearchTool,
            )

            always = set(DEFAULT_ALWAYS_VISIBLE) | set(cfg.always_visible)
            self.tool_search_controller = ToolSearchController(
                self.tools,
                always_visible=always,
                search_result_limit=cfg.search_result_limit,
            )
            self.tools.register(ToolSearchTool(self.tool_search_controller))
            self.tools.register(ToolCallTool(self.tool_search_controller))
            # ``first=True`` 表示在 CacheOptimizer 用 ``cache_control`` 标记最后一个工具前先过滤列表；
            # 否则已标记的工具可能被过滤，导致缓存断点丢失。
            self.strategies.register(
                ToolSearchStrategy(
                    self.tool_search_controller,
                    compaction_threshold=cfg.compaction_threshold,
                ),
                first=True,
            )

    # ── 上下文引擎辅助方法 ─────────────────────────────────────────────

    def _context_messages_for_session(self, session: Session) -> list[dict[str, Any]]:
        """按当前 Context Engine 的所有权返回待组装会话消息视图。

        `Session` 保存追加式消息记录，但不同引擎对压缩的责任不同。Curator 在
        ``owns_compaction=True`` 时必须看到完整 append-only log，才能自行决定哪些内容归档；
        Legacy 引擎不拥有该决策，只读取 `get_history(max_messages=0)` 提供的 consolidation 后
        切片，以保持引入 Curator 前的行为。返回的是新列表视图，方法不会修改 Session。
        """
        if self.context_engine.owns_compaction:
            return list(session.messages)
        return session.get_history(max_messages=0)

    def _make_token_budget(self, selected_skills: list[Any] | None = None) -> TokenBudget:
        """为当前 Context Engine 计算一份保守的单 Turn Prompt 预算。

        预算从 `context_window_tokens` 总窗口中依次预留模型最大输出、当前 Tool definitions
        和 System Prompt 所需 Token，剩余值才写入 `available_history` 供历史消息使用。
        ``selected_skills`` 会影响 System Prompt 大小，因此必须在估算时传入；Provider 未
        声明生成上限时按 4096 预留。任何扣减导致的负数都会收敛为 0，避免把超额空间伪装
        成可用历史。返回 `TokenBudget`，不裁剪消息本身。
        """
        reserved_output = int(getattr(getattr(self.provider, "generation", None), "max_tokens", 4096) or 4096)
        tool_tokens = estimate_prompt_tokens([], self.tools.get_definitions())
        system_prompt = self.context.build_system_prompt(
            selected_skills,
            include_memory=self.memory_enabled,
        )
        system_tokens = estimate_prompt_tokens([{"role": "system", "content": system_prompt}])
        available_history = max(
            0,
            self.context_window_tokens - reserved_output - tool_tokens - system_tokens,
        )
        return TokenBudget(
            context_length=self.context_window_tokens,
            reserved_output=reserved_output,
            reserved_tools=tool_tokens,
            reserved_system=system_tokens,
            available_history=available_history,
        )

    async def _select_skills_for_turn(
        self,
        current_message: str,
        history: list[dict],
    ) -> list[Any] | None:
        """保留旧调用形状，但不在 Host 侧预选 Skill。

         统一 Context Engine 内部的 `SkillForgeRouter` 同时拥有 Skill 选择与渲染，随后通过
        每 Turn 的 assembly metadata 暴露 ``injected_skill_ids``。因此 ``current_message``
         与 ``history`` 在这条兼容入口中不会被再次消费，也没有 `SkillMeta` 列表流回 Host；
         方法始终返回 ``None``。把选择留在 Engine 内可避免 Host 与 Context 对同一预算做两次
         决策。
        """
        return None

    async def _assemble_context_messages(
        self,
        *,
        session: Session,
        session_key: str,
        current_message: str,
        media: list[str | Media] | None = None,
        channel: str | None = None,
        chat_id: str | None = None,
        selected_skills: list[Any] | None = None,
        metadata_sink: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """请求当前 Context Engine 组装主 Agent 本轮实际可见的消息窗口。

        方法先依据压缩所有权取得 Session 候选消息，再把 ``current_message``、媒体、通道、
        会话标识和已选 Skill 封装为 `TurnContext`，连同 `_make_token_budget` 的结果交给
        `context_engine.assemble`。返回值是可直接发给 Provider 的消息列表，不是完整 Session。

        若提供 ``metadata_sink``，Engine 产出的 Memory 命中、Skill 注入和回退路径等元数据
        会原地写入该字典，供 `run_turn` 形成证据；随后 `_inject_recovery_block` 可能把上轮
        中断通知加到当前用户消息前。`TurnContext` 使用延迟导入，以维持模块顶部说明的循环
        导入边界。
        """
        from pico.runtime.context import TurnContext

        session_messages = self._context_messages_for_session(session)
        assembled = await self.context_engine.assemble(
            session_key,
            session_messages,
            self._make_token_budget(selected_skills),
            turn=TurnContext(
                current_message=current_message,
                media=media,
                channel=channel,
                chat_id=chat_id,
                selected_skills=selected_skills,
            ),
        )
        if metadata_sink is not None:
            metadata_sink.update(assembled.metadata or {})
        messages = assembled.messages
        self._inject_recovery_block(session_key, messages)
        return messages

    @staticmethod
    def _checkpoint_active(policy: str, interactive: bool) -> bool:
        """结合调用现场是否交互，解析 ``runtime.checkpoint.policy`` 是否启用快照。

        默认策略 ``"interactive"`` 直接采用 ``interactive`` 信号：持续会话可能有 "next
        turn" 可注入恢复信息，而一次性 ``-m`` 调用没有下一轮，创建快照只会增加无用成本。
        ``"always"`` 无视调用形态强制开启，``"never"`` 无条件关闭。返回布尔值，只决定本次
        AgentLoop 是否构建 CheckpointService，不创建任何快照。
        """
        if policy == "never":
            return False
        if policy == "always":
            return True
        return interactive  # policy 为 interactive

    def _stash_recovery(self, session_key: str, outcome: "TurnOutcome") -> None:
        """暂存一次中断 Turn 的快照证据，供同一 Session 的下一轮生成恢复提示。

        只有 Checkpoint 已启用、``outcome.status`` 精确为 ``"interrupted"``，并且确实存在
        `checkpoint_id` 或 `edited_files` 时，方法才会把证据写入按 ``session_key`` 隔离的
        `_pending_recovery`。其他情况是 no-op，避免为空现场制造恢复通知。

        状态过滤是有意的：``"error"`` Turn 仍可能产生逐 Turn shadow commit 用于审计，但
        Provider 400 等错误通常没有可继续的部分编辑轨迹；此时向用户展示 "Files modified
        last turn" 会造成误导。这里保存的是下一轮要核验的线索，不把快照等同于恢复成功。
        """
        if self._checkpoint is None or outcome.status != "interrupted":
            return
        if outcome.edited_files or outcome.checkpoint_id:
            self._pending_recovery[session_key] = {
                "checkpoint_id": outcome.checkpoint_id,
                "files": outcome.edited_files,
            }

    def _inject_recovery_block(self, session_key: str, messages: list[dict]) -> None:
        """把上轮中断现场的恢复通知前置到当前用户消息，并在成功后一次性消费。

        方法按 ``session_key`` 查找待恢复记录，只在消息列表以 ``role="user"`` 结尾时处理。
        通知包含可用的文件清单、Checkpoint 标识以及“先核对现状再继续”的要求；字符串内容
        直接前置，多模态列表则插入一个文本块。这样 Provider 在读取用户本轮要求前先看到
        上次未完成工作的证据边界。

        若 ``content`` 是 None、dict 或其他未知形状，方法不会猜测如何改写，也不会删除待
        恢复记录；后续一次正常 assembly 仍可注入。只有内容已安全写入后才从
        `_pending_recovery` 弹出，保证异常形状不会让恢复线索静默丢失。
        """
        recovery = self._pending_recovery.get(session_key)
        if not recovery or not messages:
            return
        last = messages[-1]
        if last.get("role") != "user":
            # 最后一条消息不是用户 Turn 时，保持恢复待处理，使下次以用户消息结尾的组装注入它。
            return
        content = last.get("content")
        files = recovery.get("files") or []
        cid = recovery.get("checkpoint_id")
        lines = ["[Recovery — the previous turn was interrupted before finishing]"]
        if files:
            lines.append("Files modified last turn: " + ", ".join(files))
        if cid:
            lines.append(f"Checkpoint: {cid}")
        lines.append("Verify the current state of these files before continuing.")
        block = "\n".join(lines)
        # 先修改、后弹出，从调用方视角看是原子操作。如果无法安全写入形状未知的 ``content``，
        # 恢复保持待处理，而不是被静默丢弃。
        if isinstance(content, str):
            last["content"] = f"{block}\n\n{content}"
        elif isinstance(content, list):
            last["content"] = [{"type": "text", "text": block}] + content
        else:
            return  # 内容形状异常时保持待恢复状态
        self._pending_recovery.pop(session_key, None)

    @trace.instrument("memory.store", extract=semconv.memory_store)
    async def _dispatch_backend_store(
        self,
        session_key: str,
        messages_slice: list[dict],
    ) -> None:
        """AG-1：把本轮新增消息转交插件 :class:`MemoryBackend` 持久化或建立索引。

        一轮结束后有三个并列步骤：``context_engine.after_turn`` 处理 Engine 自身账本，
        ``memory.maybe_consolidate`` 执行 Pico compaction，本方法负责插件 Backend。传入的
        ``messages_slice`` 会先经 `sanitize_persisted_payload` 清理再调用 `store`，而不是让
        后端接触未经约束的运行时对象。

        当 ``self.backend is None`` 或消息切片为空时返回 no-op，使从未注册插件的旧调用方
        与 pre-AG-1 行为一致。Backend failure 会在 append-only Session 已保存之后继续向外
        传播：Session 事实不会回滚，但 Turn 也不能在索引失败时被报告为成功。
        """
        if self.backend is None or not messages_slice:
            return
        await self.backend.store(
            session_key,
            sanitize_persisted_payload(messages_slice),
        )

    def _collect_injected_skill_ids(
        self,
        selected: list[Any] | None,
    ) -> list[str]:
        """合并本轮 selector top-K 与 always-skills，生成去重后的 Skill 证据标识。

        ``selected`` 是检索 selector 返回的 :class:`SkillMeta` 列表；selector 关闭或无命中时
        可以是 ``None``。always-skills 无论检索结果如何都会由 :class:`LocalSkillCatalog`
        渲染，因此还要从 `self.context.skills` 单独读取，不能只记录 top-K。

        不同 SkillMeta 生产者对 ``meta.id`` 的填法并不一致：有的已经带 source，有的只有
        stable key。方法统一规范为 ``{source}/{stable_key}``，按首次出现顺序去重后返回，
        供 Turn evidence 写入 ``injected_skill_ids``。目录不存在或读取 always-skills 失败时
        保守返回已有结果，不让证据收集阻断主请求。
        """
        skills_svc = getattr(self.context, "skills", None)
        if skills_svc is None:
            return []

        seen: set[str] = set()
        ids: list[str] = []

        def _add(meta: Any) -> None:
            src = getattr(meta, "source", None)
            mid = getattr(meta, "id", None)
            if not src or not mid:
                return
            canonical = mid if "/" in mid else f"{src}/{mid}"
            if canonical not in seen:
                seen.add(canonical)
                ids.append(canonical)

        for meta in selected or []:
            _add(meta)
        try:
            always = skills_svc.get_always_skills()
        except Exception:
            always = []
        for meta in always:
            _add(meta)
        return ids

    async def _start_executor(self) -> None:
        """Delegate start executor to its owning execution module."""
        from pico.runtime.agent.resources import start_executor

        return await start_executor(self)

    async def _start_debug_server(self) -> None:
        """Delegate start debug server to its owning execution module."""
        from pico.runtime.agent.resources import start_debug_server

        return await start_debug_server(self)

    async def close_executor(self) -> None:
        """Delegate close executor to its owning execution module."""
        from pico.runtime.agent.resources import close_executor

        return await close_executor(self)

    async def _connect_mcp(self) -> None:
        """Delegate connect mcp to its owning execution module."""
        from pico.runtime.agent.resources import connect_mcp

        return await connect_mcp(self)

    def _set_tool_context(
        self, channel: str, chat_id: str, message_id: str | None = None, session_key: str | None = None
    ) -> None:
        """Delegate set tool context to its owning execution module."""
        from pico.runtime.agent.turn_runner import set_tool_context

        return set_tool_context(self, channel, chat_id, message_id, session_key)

    @staticmethod
    def _strip_think(text: str | None) -> str | None:
        """移除部分模型混入最终内容的 ``<think>…</think>`` 推理块。

        输入为空时返回 ``None``；有文本时跨行删除所有成对标签及内部内容，再去除首尾空白。
        清理后没有可见正文也返回 ``None``，让上层进入空响应恢复而不是交付空字符串。该方法
        只处理显式标签，不猜测普通文本是否属于推理，也不修改独立的
        `reasoning_content` 字段。
        """
        if not text:
            return None
        return re.sub(r"<think>[\s\S]*?</think>", "", text).strip() or None

    @staticmethod
    def _tool_hint(tool_calls: list) -> str:
        """把一组 Tool 调用压缩成供进度出口展示的简短提示。

        每个调用优先取参数字典中的第一个字符串值，渲染成例如
        ``'web_search("query")'`` 的形式；值超过 40 个字符时截断并追加省略号。参数不是
        字典、没有值或首值不是字符串时只展示 Tool 名，避免把复杂载荷泄漏到进度提示。
        多个调用以逗号连接，返回值仅用于人类可读状态，不参与实际 Tool 执行。
        """

        def _fmt(tc):
            args = (tc.arguments[0] if isinstance(tc.arguments, list) else tc.arguments) or {}
            val = next(iter(args.values()), None) if isinstance(args, dict) else None
            if not isinstance(val, str):
                return tc.name
            return f'{tc.name}("{val[:40]}…")' if len(val) > 40 else f'{tc.name}("{val}")'

        return ", ".join(_fmt(tc) for tc in tool_calls)

    @staticmethod
    def _build_usage_snapshot(response, model: str, session_key: str) -> "UsageSnapshot":
        """经统一计费归一化构建历史 TokenWise 兼容视图。

        方法用禁用上报的 `CallEfficiency` 记录 ``response``，同时带入请求 ``model`` 与
        ``session_key``，让模型名称、Token 和成本字段先走当前 canonical normalization；
        随后调用 `to_legacy_snapshot()` 转成旧 TokenWise 消费者期望的 `UsageSnapshot`。
        它不产生外部遥测，也不绕过统一计费规则直接拼字段。
        """
        from pico.observability.usage import CallEfficiency

        return (
            CallEfficiency.disabled()
            .record(
                response,
                requested_model=model,
                session_key=session_key,
            )
            .to_legacy_snapshot()
        )

    async def _llm_call_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        model: str | None,
        on_token_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """Delegate call model stream to its owning execution module."""
        from pico.runtime.agent.streaming import call_model_stream

        return await call_model_stream(self, messages, tools, model, on_token_delta, on_reasoning_delta)

    @classmethod
    def _emergency_shrink(cls, messages: list[dict]) -> tuple[list[dict], int]:
        """在 Turn 中途上下文溢出时，省略较旧 Tool 结果正文以腾出窗口。

        中途增长通常来自累积的 ``role="tool"`` 输出。方法保留最近
        `_SHRINK_KEEP_RECENT_TOOL_RESULTS` 条完整结果，把更旧且非空的正文替换成固定占位符；
        System、User、Assistant 推理以及消息顺序保持不变。它基于输入生成新列表和复制后的
        被改消息，不额外调用 LLM，因此收缩是确定且可计数的。

        返回 ``(new_messages, num_elided)``。当 ``num_elided == 0`` 时没有值得省略的旧结果，
        调用方不应靠相同重试期待窗口变小；原列表会直接返回。该机制保留最新操作现场，但
        明确牺牲旧 Tool 正文，不等同于无损压缩。
        """
        placeholder = "[earlier tool output elided to fit the context window]"
        tool_idxs = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        if len(tool_idxs) <= cls._SHRINK_KEEP_RECENT_TOOL_RESULTS:
            return messages, 0
        elide = set(tool_idxs[: -cls._SHRINK_KEEP_RECENT_TOOL_RESULTS])
        shrunk: list[dict] = []
        elided = 0
        for i, m in enumerate(messages):
            if i in elide and m.get("content") and m.get("content") != placeholder:
                clean = dict(m)
                clean["content"] = placeholder
                shrunk.append(clean)
                elided += 1
            else:
                shrunk.append(m)
        return shrunk, elided

    async def _synthesize_final_on_exhaustion(
        self,
        messages: list[dict],
        model: str | None,
        fallback_models: list[str] | None,
        session_key: str = "",
        on_token_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
    ) -> str:
        """Delegate synthesize final answer to its owning execution module."""
        from pico.runtime.agent.execution import synthesize_final_answer

        return await synthesize_final_answer(
            self, messages, model, fallback_models, session_key, on_token_delta, on_reasoning_delta
        )

    async def _run_agent_loop(
        self,
        initial_messages: list[dict],
        on_progress: Callable[..., Awaitable[None]] | None = None,
        session_key: str | None = None,
        model: str | None = None,
        fallback_models: list[str] | None = None,
        injected_skill_ids: list[str] | None = None,
        on_token_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_event: Callable[[str, dict], Awaitable[None]] | None = None,
        usage_sink: dict[str, Any] | None = None,
        drain: Drain | None = None,
        origin: Origin | None = None,
    ) -> tuple[str | None, list[str], list[dict], TurnOutcome]:
        """Delegate execute model loop to its owning execution module."""
        from pico.runtime.agent.execution import execute_model_loop

        return await execute_model_loop(
            self,
            initial_messages,
            on_progress,
            session_key,
            model,
            fallback_models,
            injected_skill_ids,
            on_token_delta,
            on_reasoning_delta,
            on_tool_event,
            usage_sink,
            drain,
            origin,
        )

    async def run(self) -> None:
        """Delegate run resources to its owning execution module."""
        from pico.runtime.agent.resources import run_resources

        return await run_resources(self)

    @property
    def is_processing(self) -> bool:
        """返回当前是否有 Turn 正在全局处理锁内分派。

        结果来自 `_processing_lock.locked()`，表示这个 AgentLoop 实例的临界区占用状态，供
        Host 判断 BusyPolicy 等行为。它不是队列长度，也不证明模型或 Tool 此刻正在运行；
        锁从 Turn 进入到分派结束覆盖整条请求链，因此 ``True`` 只说明已有工作拥有该边界。
        """
        return self._processing_lock.locked()

    def _notify_turn_complete(self) -> None:
        for callback in self.on_turn_complete:
            try:
                callback()
            except Exception:
                logger.exception("on_turn_complete callback failed")

    async def close_mcp(self) -> None:
        """Delegate close mcp to its owning execution module."""
        from pico.runtime.agent.resources import close_mcp

        return await close_mcp(self)

    async def close(self) -> None:
        """Delegate close resources to its owning execution module."""
        from pico.runtime.agent.resources import close_resources

        return await close_resources(self)

    def stop(self) -> None:
        """Delegate stop resources to its owning execution module."""
        from pico.runtime.agent.resources import stop_resources

        return stop_resources(self)

    def replace_provider(self, provider: LLMProvider, *, model: str | None = None) -> None:
        from pico.integrations.llm.metered_provider import CallEfficiencyProvider

        if isinstance(self.provider, CallEfficiencyProvider):
            self.provider.replace(provider)
        else:
            self.provider = provider
        if model is None:
            return
        self.model = model
        self.subagents.model = model
        self.memory_consolidator.model = model
        replace_model = getattr(self.context_engine, "replace_model", None)
        if callable(replace_model):
            replace_model(model)

    async def _process_message(
        self,
        req: TurnRequest,
        session_key: str | None = None,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
        on_token_delta: Callable[[str], Awaitable[None]] | None = None,
        on_reasoning_delta: Callable[[str], Awaitable[None]] | None = None,
        on_tool_event: Callable[[str, dict], Awaitable[None]] | None = None,
        usage_sink: dict[str, Any] | None = None,
        origin: Origin | None = None,
        drain: Drain | None = None,
        context_metadata_sink: dict[str, Any] | None = None,
    ) -> tuple[str | None, list[str]] | None:
        """Delegate process message to its owning execution module."""
        from pico.runtime.agent.turn_runner import process_message

        return await process_message(
            self,
            req,
            session_key,
            on_progress,
            on_token_delta,
            on_reasoning_delta,
            on_tool_event,
            usage_sink,
            origin,
            drain,
            context_metadata_sink,
        )

    def _save_turn(
        self,
        session: Session,
        messages: list[dict],
        skip: int,
        origin: Origin | None = None,
    ) -> list[dict]:
        """Delegate save turn to its owning execution module."""
        from pico.runtime.agent.turn_runner import save_turn

        return save_turn(self, session, messages, skip, origin)

    async def run_turn(
        self,
        req: TurnRequest,
        emit: Emit,
        drain: Drain,
        *,
        stream: bool = True,
        usage_sink: dict[str, Any] | None = None,
        text_sink: dict[str, Any] | None = None,
    ) -> TurnOutcome:
        """Delegate run turn to its owning execution module."""
        from pico.runtime.agent.turn_runner import run_turn

        return await run_turn(self, req, emit, drain, stream=stream, usage_sink=usage_sink, text_sink=text_sink)

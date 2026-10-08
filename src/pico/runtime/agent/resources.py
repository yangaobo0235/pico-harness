"""Agent resources with explicit ownership of execution state."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

from pico.integrations.execution import SandboxInitError

if TYPE_CHECKING:
    pass


def start_personalization_task(self, factory: Callable[[], Awaitable[Any]]) -> None:
    if self._personalization_closed:
        return
    task = asyncio.create_task(factory())
    self._personalization_tasks.add(task)
    task.add_done_callback(self._personalization_tasks.discard)


def begin_close(self) -> None:
    """同步封住新的个性化后台任务，并取消已经启动的任务。

    关闭流程需要先阻止 `_start_personalization_task` 再接纳工作，否则等待旧任务时仍可能
    产生新任务。该方法把 `_personalization_closed` 设为真并对当前任务快照调用
    `cancel()`，整个过程不发生 ``await``，所以调用方可在进入异步 drain 前建立清晰屏障。
    重复调用是 no-op；真正等待取消完成由 `close` 负责。
    """
    if self._personalization_closed:
        return
    self._personalization_closed = True
    for task in tuple(self._personalization_tasks):
        task.cancel()


async def start_executor(self) -> None:
    """在首次使用前启动 Sandbox executor，并保证并发调用下只启动一次。

    `_executor_start_lock` 串行化竞争者；已经启动时立即返回。首次启动会创建并进入
    `AsyncExitStack`，再把 executor 作为异步上下文压栈，使关闭责任集中到
    `close_executor`。若进入过程中抛出异常，临时 stack 会先清理再把异常原样传播，
    `_executor_started` 也不会被误设为真。
    """
    async with self._executor_start_lock:
        if self._executor_started:
            return
        stack = AsyncExitStack()
        try:
            await stack.__aenter__()
            await stack.enter_async_context(self._executor)
        except Exception:
            await stack.aclose()
            raise
        self._executor_stack = stack
        self._executor_started = True


async def start_debug_server(self) -> None:
    """在 Sandbox 调试模式启用时启动本地 socket 调试服务器。

    未配置 Sandbox、``debug.enabled`` 为假或 backend 为 ``"none"`` 时不会创建服务器；
    最后一种情况会记录警告，因为没有 BoxLite runtime 可供调试。启用路径根据数据目录
    解析 socket，传入当前 executor 拥有的实例 ID 和消息大小上限，再保存已启动的
    `SandboxDebugServer` 供关闭阶段使用。

    用户显式选择调试模式后，启动失败会记录具体错误但不终止整个 Agent runtime；这让
    主请求仍可运行，同时避免稍后 `pico sandbox` 只看到“套接字不存在”却没有原因。
    """
    cfg = self._sandbox_config
    if cfg is None or not cfg.debug.enabled:
        return
    if cfg.backend == "none":
        logger.warning("sandbox.debug.enabled=true is ignored because backend='none' (no boxlite runtime is active)")
        return
    try:
        from pico.config.paths import get_data_dir
        from pico.integrations.execution.debug_server import SandboxDebugServer

        socket_path = SandboxDebugServer.resolve_socket_path(cfg.debug.socket, get_data_dir())
        server = SandboxDebugServer(
            socket_path=socket_path,
            owned_ids=self._owned_ids,
            max_message_bytes=cfg.debug.max_message_bytes,
        )
        await server.start()
        self._debug_server = server
    except Exception as exc:
        # 用户已明确选择调试模式；此处静默失败会让用户在稍后看到 `pico sandbox`
        # 报“套接字不存在”时困惑。需明确记录原因。
        logger.error("Failed to start sandbox debug server: %s", exc)


async def close_executor(self) -> None:
    """关闭调试服务器和 Sandbox executor，并把实例状态复位为可重新启动。

    调试 socket 先停止，随后关闭保存 executor 生命周期的 `AsyncExitStack`。停止阶段的
    普通异常会记录或被容忍，`RuntimeError` 与 `BaseExceptionGroup` 也不会让 shutdown
    卡住；无论资源此前是否完整启动，最终都会清空引用并把 `_executor_started` 设为假。
    方法可重复调用，适用于 Turn 失败后的急停和正常 runtime 关闭两条路径。
    """
    if self._debug_server is not None:
        try:
            await self._debug_server.stop()
        except Exception as exc:
            logger.warning("Error stopping sandbox debug server: %s", exc)
        self._debug_server = None
    if self._executor_stack:
        try:
            await self._executor_stack.aclose()
        except (RuntimeError, BaseExceptionGroup):
            pass
        self._executor_stack = None
    self._executor_started = False


async def connect_mcp(self) -> None:
    """在首次需要时一次性连接已配置的 MCP servers，并注册其 Tool。

    已连接、正在连接或没有配置时立即返回。方法在第一个 ``await`` 前设置
    `_mcp_connecting`，利用 asyncio 单线程任务切换边界阻止重复连接；随后确保 Sandbox
    executor 已启动，用独立 `AsyncExitStack` 承担 MCP 连接的关闭责任，并把远端 Tool
    加入当前 `ToolRegistry`。连接后再次执行 `_apply_disabled_tools`，使黑名单也覆盖
    动态加入的 ``mcp_<server>_search`` 等名称。

    任一步失败都会复位 connecting 标志、关闭部分建立的 stack 并重新抛出异常，因此
    当前 Turn 能准确失败，后续调用也仍有机会重试，而不会永久停在“正在连接”状态。
    """
    if self._mcp_connected or self._mcp_connecting or not self._mcp_servers:
        return
    # 在第一个 await 之前同步设置标志。asyncio 单线程执行，此处不会发生上下文切换，
    # 该互斥模式无需锁。
    self._mcp_connecting = True
    try:
        await self._start_executor()  # MCP 服务器连接前，执行器必须已启动
        from pico.integrations.mcp.client import connect_mcp_servers

        self._mcp_stack = AsyncExitStack()
        await self._mcp_stack.__aenter__()
        await connect_mcp_servers(
            self._mcp_servers,
            self.tools,
            self._mcp_stack,
            executor=self._executor,
        )
        # 重新应用黑名单：MCP 服务器可能注册也出现在 ``disabled_tools`` 中的工具名，
        # 例如 ``mcp_<server>_search``。
        self._apply_disabled_tools()
        self._mcp_connected = True
        self._mcp_connecting = False
    except Exception:
        # 重置进行中标志，使后续调用可重试。
        self._mcp_connecting = False
        if self._mcp_stack:
            try:
                await self._mcp_stack.aclose()
            except Exception:
                pass
            self._mcp_stack = None
        raise


async def run_resources(self) -> None:
    """拉起 Agent runtime 依赖并作为长期任务保持存活。

    Turn 已经统一从 Spine 的 ``run_turn`` 进入，本协程不再消费 inbound bus。它依次启动
    executor、可选 debug server 和 MCP 连接，然后在 ``self._running`` 为真时短暂 sleep，
    让 Gateway 能把它作为长期任务 gather。shutdown 通过 ``stop()`` 清除运行标志；真正
    的 MCP、Sandbox 和后台任务清理由 `close` 系列方法负责。

    若启动依赖时抛出异常，异常向 Host 传播而不是进入空保活循环。正常退出循环后也不会
    自动重启资源，因此生命周期所有者必须显式决定何时再次调用 `run`。
    """
    self._running = True
    try:
        await self._start_executor()
        await self._start_debug_server()
        await self._connect_mcp()
    except SandboxInitError as exc:
        logger.error("Sandbox failed to start: {}", exc)
        await self.close_executor()
        self._running = False
        return
    except Exception:
        await self.close_executor()
        raise
    logger.info("Agent loop started")

    while self._running:
        await asyncio.sleep(1.0)


async def close_mcp(self) -> None:
    """关闭 MCP 连接栈，并无条件继续关闭 Sandbox executor。

    已建立的 `_mcp_stack` 会先执行 `aclose()`；关闭期异常只记录为调试噪声，不阻断整体
    shutdown。随后 `_mcp_connected` 与 `_mcp_connecting` 都复位，使实例若被重新使用仍可
    连接。即使从未配置 MCP，也始终调用 `close_executor`，因为 Sandbox 生命周期不应
    被 MCP 是否存在所绑架。
    """
    if self._mcp_stack:
        try:
            await self._mcp_stack.aclose()
        except (RuntimeError, BaseExceptionGroup):
            pass  # MCP SDK 的取消作用域清理会产生噪声，但无害
        self._mcp_stack = None
    self._mcp_connected = False  # 重置后 _connect_mcp() 才能在关闭后重连
    self._mcp_connecting = False  # 重置以免并发调用方永久阻塞
    await self.close_executor()  # 即使未配置 MCP 服务器也始终执行


async def close_resources(self) -> None:
    """先排空后台个性化任务，再关闭 Agent runtime 资源。

    `_close_lock` 让并发关闭串行化，`_closed` 使重复调用成为 no-op。首次关闭先执行
    `begin_close`，同步封住新个性化任务并取消旧任务；随后用 `gather(...,
    return_exceptions=True)` 等待其完成，最后调用 `close_mcp` 释放 MCP 与 Sandbox。
    只有这些步骤结束后才把实例标记为已关闭，避免 cleanup 尚未完成就对外宣称终止。
    """
    async with self._close_lock:
        if self._closed:
            return
        self.begin_close()
        tasks = tuple(self._personalization_tasks)
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.close_mcp()
        self._closed = True


def stop_resources(self) -> None:
    """请求长期 `run` 保活循环在下一次检查时停止。

    方法只把 `_running` 设为 ``False`` 并记录日志，不等待循环退出，也不释放 MCP、
    Sandbox 或后台任务。因此它适合 Host 的同步停止信号；需要完整资源清理时调用方仍应
    await `close()`。重复调用不会改变额外状态。
    """
    self._running = False
    logger.info("Agent loop stopping")

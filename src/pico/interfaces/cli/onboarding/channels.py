"""Onboarding channels: one screen or service responsibility."""

from __future__ import annotations

from typing import Any, Optional

import typer

from pico.interfaces.cli.onboarding import configuration, state, ui


def _ordered_channel_names() -> list[str]:
    from pico.runtime.delivery.channels.registry import discover_channel_names

    rank = {name: i for i, name in enumerate(state._CHANNEL_ORDER)}
    return sorted(discover_channel_names(), key=lambda n: (rank.get(n, len(rank)), n))


def _select_channel() -> Optional[str]:
    """List available channels via the registry and let the user pick one."""
    questionary = ui._require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    names = _ordered_channel_names()
    choices = [questionary.Choice(n, value=n) for n in names]
    choices.append(questionary.Choice(ui._t("Back", "返回"), value=state._BACK))
    picked = questionary.select(ui._t("Channel:", "渠道:"), choices=choices, style=PICO_STYLE, qmark=state._QMARK).ask()
    return picked


def _prompt_channel_fields(channel: str) -> Any:
    """Reflect a channel's Pydantic schema and prompt for credential-like fields."""
    questionary = ui._require_questionary()
    from pico.config.update_channels import channel_field_specs
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    try:
        specs = channel_field_specs(channel)
    except KeyError as exc:
        state.console.print(f"  [red]✗[/red] {exc}")
        raise typer.Exit(1)
    promptable = [
        (path, spec)
        for path, spec in specs.items()
        if path != "enabled" and spec.get("type", "") == "str" and (spec.get("default") in ("", None))
    ]
    if promptable:
        names = ", ".join((path for path, _ in promptable))
        state.console.print(
            ui._t(
                f"  [dim]Configuring {channel} — fill in:[/dim] {names}",
                f"  [dim]正在配置 {channel} — 请填写:[/dim] {names}",
            )
        )
        help_text = state._CHANNEL_CRED_HELP.get(channel)
        if help_text:
            state.console.print(
                ui._t(f"  [dim]Where to get it: {help_text[0]}[/dim]", f"  [dim]去哪拿:{help_text[1]}[/dim]")
            )
    else:
        state.console.print(
            ui._t(
                f"  [dim]{channel} needs no credentials; enabling.[/dim]",
                f"  [dim]{channel} 无需填写凭证,正在启用。[/dim]",
            )
        )
    fields: dict[str, Any] = {}
    for idx, (path, spec) in enumerate(promptable):
        required = bool(spec.get("required"))
        description = spec.get("description", "")
        opt_tag = "" if required else ui._t(" (optional)", " (可选)")
        prompt_label = f"{path}{opt_tag}" + (f" — {description}" if description else "") + ":"
        allow_back = idx == 0
        placeholder = ui._field_placeholder(allow_back, required)
        while True:
            if spec.get("is_secret"):
                value = questionary.password(
                    prompt_label, placeholder=placeholder, style=PICO_STYLE, qmark=state._QMARK
                ).ask()
            else:
                value = questionary.text(
                    prompt_label, placeholder=placeholder, style=PICO_STYLE, qmark=state._QMARK
                ).ask()
            if value is None:
                raise typer.Exit(1)
            value = value.strip()
            if value:
                fields[path] = value
                break
            if allow_back:
                return state._BACK
            if required:
                state.console.print(
                    ui._t(f"  [yellow]{path} is required.[/yellow]", f"  [yellow]{path} 为必填项。[/yellow]")
                )
                continue
            break
    return fields


def _channel_uses_interactive_login(channel: str) -> bool:
    """True for scancode/QR channels that pair via a live
    login flow rather than reflected credential fields."""
    try:
        from pico.runtime.delivery.channels.registry import discover_specs

        spec = discover_specs().get(channel)
        return bool(spec and spec.capabilities.interactive_login)
    except Exception:
        return False


def _scancode_login(channel: str, *, non_interactive: bool = False) -> None:
    """Run a scancode channel's real QR login (reuses ``channel.login``).

    Mirrors ``pico channels login``: enable the channel so its config section
    persists, build the adapter via its spec factory, then drive
    ``await channel.login()``, which displays the QR and waits. A failed or
    timed-out login drops into a numbered submenu (retry / skip).
    """
    import asyncio

    from pico.config.update_channels import disable_channel
    from pico.runtime.delivery.channels.registry import discover_specs

    configuration._enable_channel(channel, {})
    specs = discover_specs()
    spec = specs.get(channel)
    if spec is None:
        disable_channel(channel)
        state.console.print(ui._t(f"  [red]✗ Unknown channel: {channel}[/red]", f"  [red]✗ 未知渠道:{channel}[/red]"))
        return
    logged_in = False
    try:
        while True:
            from pico.config.loader import load_config

            channel_cfg = getattr(load_config().channels, channel, None)
            if channel_cfg is None:
                state.console.print(
                    ui._t(
                        f"  [red]✗ No config section for channel: {channel}[/red]",
                        f"  [red]✗ 渠道 {channel} 没有配置段。[/red]",
                    )
                )
                return
            adapter = spec.factory(channel_cfg)
            state.console.print(
                ui._t(
                    f"  [dim]Starting {spec.display_name} QR login…[/dim]",
                    f"  [dim]正在启动 {spec.display_name} 扫码登录…[/dim]",
                )
            )
            state.console.print(
                ui._t(
                    f"  [dim]A login link / QR code will appear below — scan it with {spec.display_name} (or open the link on a phone signed in to {spec.display_name}) to connect. This waits until you finish.[/dim]",
                    f"  [dim]下方会出现登录链接 / 二维码 — 用 {spec.display_name} 扫码(或在已登录 {spec.display_name} 的手机上打开该链接)即可接入;这里会一直等到你完成。[/dim]",
                )
            )
            from loguru import logger as _wiz_logger

            _login_log_scope = f"pico.integrations.channels.{channel}"
            try:
                _wiz_logger.enable(_login_log_scope)
                ok = asyncio.run(adapter.login(force=True))
            except Exception as exc:
                state.console.print(
                    ui._t(f"  [yellow]✗ Login failed: {exc}[/yellow]", f"  [yellow]✗ 登录失败:{exc}[/yellow]")
                )
                ok = False
            finally:
                _wiz_logger.disable(_login_log_scope)
            if ok:
                state.console.print(
                    ui._t(
                        f"  [green]✓ Logged in; {channel} connected.[/green]",
                        f"  [green]✓ 已登录;{channel} 已接入。[/green]",
                    )
                )
                logged_in = True
                return
            choice = ui._failure_choice(
                [(ui._t("Retry", "重试"), "retry"), (ui._t("Skip this channel", "跳过此渠道"), "skip")],
                non_interactive=non_interactive,
            )
            if choice == "retry":
                continue
            state.console.print(
                ui._t(
                    f"  [dim]{channel} not connected — finish later with pico channels login {channel}.[/dim]",
                    f"  [dim]{channel} 未接入 — 之后用 pico channels login {channel} 完成。[/dim]",
                )
            )
            return
    finally:
        if not logged_in:
            disable_channel(channel)


def _channel_maturity(channel: str) -> str:
    """Evidence level declared by the channel's spec (``ChannelSpec.maturity``)."""
    try:
        from pico.runtime.delivery.channels.registry import discover_specs

        spec = discover_specs().get(channel)
    except Exception:
        return "unknown"
    return spec.maturity if spec else "unknown"


def _print_maturity_note(channel: str) -> None:
    """State a Beta channel's evidence level before credentials are entered."""
    if _channel_maturity(channel) != "beta":
        return
    state.console.print(
        ui._t(
            f"  [dim]{channel} is Beta: deterministic contract and security checks only, no live send/receive evidence yet.[/dim]",
            f"  [dim]{channel} 处于 Beta:仅通过确定性契约与安全检查,尚无真实收发证据。[/dim]",
        )
    )


def _add_one_channel(*, non_interactive: bool = False) -> None:
    """Pick + (scancode login | reflect-prompt) + enable one channel."""
    while True:
        channel = _select_channel()
        if channel is None or channel is state._BACK:
            return
        _print_maturity_note(channel)
        if _channel_uses_interactive_login(channel):
            _scancode_login(channel, non_interactive=non_interactive)
            return
        fields = _prompt_channel_fields(channel)
        if fields is state._BACK:
            continue
        configuration._enable_channel(channel, fields)
        state.console.print(ui._t(f"  [green]✓ {channel} enabled.[/green]", f"  [green]✓ {channel} 已启用。[/green]"))
        return


def _manage_existing_channels() -> None:
    """Edit/disable submenu for already-enabled channels."""
    questionary = ui._require_questionary()
    from pico.config.update_channels import disable_channel, set_channel_fields
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    while True:
        enabled = configuration._enabled_channels()
        if not enabled:
            return
        choices = [questionary.Choice(n, value=n) for n in enabled]
        choices.append(questionary.Choice(ui._t("Back", "返回"), value=state._BACK))
        target = questionary.select(
            ui._t("Pick a channel to manage:", "选择要管理的渠道:"),
            choices=choices,
            style=PICO_STYLE,
            qmark=state._QMARK,
        ).ask()
        if target is None or target is state._BACK:
            return
        action = questionary.select(
            ui._t(f"What would you like to do with {target}?", f"对 {target} 想做什么?"),
            choices=[
                questionary.Choice(ui._t("Edit config (re-enter fields)", "编辑配置(重填字段)"), value="edit"),
                questionary.Choice(ui._t("Disable (keep credentials)", "停用(保留凭证)"), value="disable"),
                questionary.Choice(ui._t("Back", "返回"), value=state._BACK),
            ],
            style=PICO_STYLE,
            qmark=state._QMARK,
        ).ask()
        if action is None or action is state._BACK:
            continue
        if action == "edit":
            fields = _prompt_channel_fields(target)
            if fields is state._BACK:
                continue
            if fields:
                set_channel_fields(target, fields)
            state.console.print(
                ui._t(f"  [green]✓ {target} config updated.[/green]", f"  [green]✓ {target} 配置已更新。[/green]")
            )
        elif action == "disable":
            disable_channel(target)
            state.console.print(
                ui._t(
                    f"  [green]✓ Disabled {target} (credentials kept; re-enable later with pico channels enable {target}).[/green]",
                    f"  [green]✓ 已停用 {target}(凭证保留;之后用 pico channels enable {target} 重新启用)。[/green]",
                )
            )


def _step4_channel(*, channel: Optional[str], skip: bool, non_interactive: bool) -> object:
    """Step 4 — optionally enable chat channel(s)."""
    ui._step_header(
        4,
        ui._t(
            "(Optional) Connect a messaging app so you can chat with Pico there",
            "(可选)接入即时通讯软件,直接在里面和 Pico 聊天",
        ),
    )
    if skip:
        state.console.print(
            ui._t("  [dim]Skipped via --skip-channel.[/dim]", "  [dim]已通过 --skip-channel 跳过。[/dim]")
        )
        return None
    if non_interactive:
        if channel:
            state.console.print(
                f"[red]--channel {channel} given but non-interactive mode can't prompt for credential fields.[/red]\nRun [#fbe23f]pico channels enable {channel} --<field> <value> ...[/#fbe23f] after onboard finishes."
            )
            raise typer.Exit(2)
        state.console.print(
            ui._t(
                "  [dim]Skipped (non-interactive, --channel not given).[/dim]",
                "  [dim]已跳过(非交互且未提供 --channel)。[/dim]",
            )
        )
        return None
    questionary = ui._require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    if channel:
        if _channel_uses_interactive_login(channel):
            _scancode_login(channel, non_interactive=non_interactive)
        else:
            fields = _prompt_channel_fields(channel)
            if fields is state._BACK:
                state.console.print(ui._t("  [dim]Skipped.[/dim]", "  [dim]已跳过。[/dim]"))
                return None
            configuration._enable_channel(channel, fields)
            state.console.print(
                ui._t(f"  [green]✓ {channel} enabled.[/green]", f"  [green]✓ {channel} 已启用。[/green]")
            )
        return None
    while True:
        enabled = configuration._enabled_channels()
        if not enabled:
            action = questionary.select(
                ui._t("Connect a chat channel?", "接入一个聊天渠道吗?"),
                choices=[
                    questionary.Choice(ui._t("Add a channel", "新增一个渠道"), value="add"),
                    questionary.Choice(
                        ui._t("Skip (add later with pico channels enable)", "跳过(之后用 pico channels enable 添加)"),
                        value="skip",
                    ),
                ],
                style=PICO_STYLE,
                qmark=state._QMARK,
            ).ask()
            if action is None:
                raise typer.Exit(1)
            if action == "skip":
                state.console.print(ui._t("  [dim]Skipped.[/dim]", "  [dim]已跳过。[/dim]"))
                return None
            _add_one_channel(non_interactive=non_interactive)
            continue
        action = questionary.select(
            ui._t(
                f"Chat channel already connected: {', '.join(enabled)}. What would you like to do?",
                f"聊天渠道已接入:{', '.join(enabled)}。想做什么?",
            ),
            choices=[
                questionary.Choice(ui._t("Done, next step", "完成,下一步"), value="done"),
                questionary.Choice(ui._t("Add a channel", "新增一个渠道"), value="add"),
                questionary.Choice(ui._t("Edit / remove a channel", "编辑 / 移除渠道"), value="edit"),
            ],
            style=PICO_STYLE,
            qmark=state._QMARK,
        ).ask()
        if action is None:
            raise typer.Exit(1)
        if action == "done":
            return None
        if action == "add":
            _add_one_channel(non_interactive=non_interactive)
        elif action == "edit":
            _manage_existing_channels()

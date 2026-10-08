"""Onboarding providers: one screen or service responsibility."""

from __future__ import annotations

from typing import Any, Callable, Optional

import typer

from pico.interfaces.cli.onboarding import configuration, state, ui, verification
from pico.interfaces.cli.services import DEFAULT_PROBE_MESSAGE, print_probe_troubleshooting


def _provider_label(name: str) -> str:
    """Display label for a provider, falling back to the registry's display_name."""
    for entry in state._CURATED_PROVIDERS:
        if entry["name"] == name:
            return ui._t(entry["label"], entry.get("label_zh", entry["label"]))
    try:
        from pico.integrations.llm.providers.registry import find_by_name

        spec = find_by_name(name)
        return spec.label if spec else name
    except Exception:
        return name


def _validate_provider_name(name: str) -> str:
    """Resolve a user-supplied provider name (kebab or snake) to a registry key."""
    from pico.config.update_providers import provider_field_specs

    candidate = name.replace("-", "_")
    try:
        provider_field_specs(candidate)
    except KeyError as exc:
        raise typer.BadParameter(str(exc))
    return candidate


def _select_provider() -> Optional[str]:
    """Interactive provider picker built from the curated catalogue.

    Returns the provider name, ``_BACK`` if the user chose the back sentinel,
    or ``None`` on Ctrl+C.
    """
    questionary = ui._require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    choices: list[Any] = [
        questionary.Choice(ui._t(entry["label"], entry.get("label_zh", entry["label"])), value=entry["name"])
        for entry in state._CURATED_PROVIDERS
    ]
    choices.append(questionary.Separator())
    choices.append(questionary.Choice(ui._t("Back", "返回"), value=state._BACK))
    picked = questionary.select(
        ui._t("Provider:", "服务商:"), choices=choices, style=PICO_STYLE, qmark=state._QMARK
    ).ask()
    return picked


def _prompt_api_key(provider: str, *, allow_back: bool = False) -> Any:
    """Ask for an API key (hidden input). Returns ``_BACK`` on empty submit
    when ``allow_back`` is set, else the key string."""
    questionary = ui._require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    def _validate(v: str) -> Any:
        if allow_back and v == "":
            return True
        return (
            True
            if len(v) >= 8
            else ui._t(
                "API key looks off (empty or too short) — please re-enter (≥ 8 chars).",
                "API Key 看起来不对(过短或为空),请重新输入(至少 8 位)。",
            )
        )

    key = questionary.password(
        ui._t("Paste your API key:", "粘贴你的 API Key:"),
        validate=_validate,
        placeholder=ui._back_placeholder(allow_back),
        style=PICO_STYLE,
        qmark=state._QMARK,
    ).ask()
    if key is None:
        raise typer.Exit(1)
    key = key.strip()
    if allow_back and key == "":
        return state._BACK
    if not key:
        raise typer.Exit(1)
    return key


def _prompt_base_url(default: str = "https://", *, allow_back: bool = False) -> Any:
    """Ask for an OpenAI-compatible base URL (used by the 'custom' provider).
    Returns ``_BACK`` on empty submit when ``allow_back`` is set."""
    questionary = ui._require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    seed = "" if allow_back else default

    def _validate(v: str) -> Any:
        if allow_back and v == "":
            return True
        return (
            True
            if v.startswith(("http://", "https://"))
            else ui._t("URL must start with http:// or https://", "地址需以 http:// 或 https:// 开头")
        )

    url = questionary.text(
        ui._t("Base URL (must include /v1):", "Base URL(需包含 /v1):"),
        default=seed,
        validate=_validate,
        placeholder=ui._back_placeholder(allow_back),
        style=PICO_STYLE,
        qmark=state._QMARK,
    ).ask()
    if url is None:
        raise typer.Exit(1)
    url = url.strip()
    if allow_back and url == "":
        return state._BACK
    if not url:
        raise typer.Exit(1)
    return url


def _prompt_custom_model(*, allow_back: bool = False) -> Any:
    """Ask for the model name when using a custom OpenAI-compatible endpoint.
    Returns ``_BACK`` on empty submit when ``allow_back`` is set."""
    questionary = ui._require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    def _validate(v: str) -> Any:
        if allow_back and v.strip() == "":
            return True
        return True if v.strip() else ui._t("Model id is required for custom endpoints.", "自定义端点必须指定模型 id。")

    model = questionary.text(
        ui._t(
            "Default model id (e.g. 'gpt-3.5-turbo' or 'qwen-max'):", "默认模型 id(如 'gpt-3.5-turbo' 或 'qwen-max'):"
        ),
        validate=_validate,
        placeholder=ui._back_placeholder(allow_back),
        style=PICO_STYLE,
        qmark=state._QMARK,
    ).ask()
    if model is None:
        raise typer.Exit(1)
    if allow_back and model.strip() == "":
        return state._BACK
    if not model:
        raise typer.Exit(1)
    return model.strip()


def _run_oauth_login(provider: str) -> bool:
    """Dispatch the OAuth login handler registered by ``provider_commands``.

    Returns ``True`` on success. A login that fails (the handler raises
    ``typer.Exit`` or any error) returns ``False`` so the caller can offer a
    retry / back menu instead of tearing the whole wizard down. A genuine
    Ctrl+C (``KeyboardInterrupt``) is left to propagate as a quit.
    """
    from pico.integrations.llm.providers.registry import find_by_name
    from pico.interfaces.cli.commands.providers import _LOGIN_HANDLERS

    spec = find_by_name(provider)
    if not spec or not spec.is_oauth:
        state.console.print(
            ui._t(
                f"  [red]✗ {provider} is not an OAuth provider.[/red]", f"  [red]✗ {provider} 不是 OAuth 服务商。[/red]"
            )
        )
        raise typer.Exit(1)
    handler = _LOGIN_HANDLERS.get(spec.name)
    if not handler:
        state.console.print(
            ui._t(
                f"  [red]✗ No login handler registered for {provider}.[/red]",
                f"  [red]✗ 未为 {provider} 注册登录处理器。[/red]",
            )
        )
        raise typer.Exit(1)
    state.console.print(
        ui._t(
            f"  [#fbe23f]Starting OAuth login for {spec.label}…[/#fbe23f]\n",
            f"  [#fbe23f]正在为 {spec.label} 启动 OAuth 登录…[/#fbe23f]\n",
        )
    )
    state.console.print(
        ui._t(
            "  [dim]A browser window / link will open — finish the sign-in there, then come back here. This waits until you're done.[/dim]\n",
            "  [dim]会打开浏览器窗口 / 链接 — 在那里完成登录后回到这里;这里会一直等到你完成。[/dim]\n",
        )
    )
    try:
        handler()
    except typer.Exit as exc:
        if exc.exit_code:
            return False
    except Exception as exc:
        state.console.print(
            ui._t(f"  [yellow]✗ Login didn't complete: {exc}[/yellow]", f"  [yellow]✗ 登录未完成:{exc}[/yellow]")
        )
        return False
    return True


def _verify_provider(provider: str, *, skip_test: bool = False) -> tuple[bool, str, Optional[list[str]]]:
    """Hit ``GET /v1/models`` to verify the credentials we just stored.

    Returns ``(ok, status, model_ids)``. ``status`` is one of the ops-library
    failure codes (``invalid_key`` / ``no_credits`` / ``rate_limited`` /
    ``network_error`` / …) and drives the failure submenu's wording.
    """
    from pico.config.update_providers import test_provider as probe

    state.console.print(ui._t("  [dim]⏳ Verifying your API key…[/dim]", "  [dim]⏳ 正在验证 API Key…[/dim]"))
    result = probe(provider)
    if result["ok"]:
        models = result.get("models_count")
        suffix = ui._t(f" ({models} models available)", f"(共 {models} 个可用模型)") if models else ""
        state.console.print(ui._t(f"  [green]✓ Connected!{suffix}[/green]", f"  [green]✓ 连接成功!{suffix}[/green]"))
        return (True, "valid", result.get("model_ids"))
    status = result.get("status", "unknown")
    if status == "not_configured" and "api_base" in (result.get("error") or ""):
        if skip_test:
            state.console.print(
                ui._t(
                    "  [dim]Skipping the model-list pre-check (this provider has no public /models endpoint); connectivity is not tested (--skip-test).[/dim]",
                    "  [dim]跳过模型列表预检(该服务商无公开 /models 端点);未做连通测试(--skip-test)。[/dim]",
                )
            )
        else:
            state.console.print(
                ui._t(
                    "  [dim]Skipping the model-list pre-check (this provider has no public /models endpoint); the test message below will confirm connectivity.[/dim]",
                    "  [dim]跳过模型列表预检(该服务商无公开 /models 端点);稍后的测试消息会验证连通。[/dim]",
                )
            )
        return (True, "skipped", None)
    hint_map = {
        "invalid_key": ui._t(
            "Auth failed: the API key is invalid — check for typos / stray spaces.",
            "鉴权失败:API Key 无效 — 检查有无拼写错误或多余空格。",
        ),
        "no_credits": ui._t(
            "Account out of credits or not provisioned — top up and retry.", "账户余额不足或未开通 — 充值后重试。"
        ),
        "rate_limited": ui._t(
            "Rate limited — wait a bit and retry, or switch provider.", "触发限流 — 稍等后重试,或更换服务商。"
        ),
        "network_error": ui._t(
            "Network error reaching the provider — check network / proxy / VPN.",
            "连接服务商时网络出错 — 检查网络 / 代理 / VPN。",
        ),
        "oauth_token_missing": ui._t(
            f"Run: pico provider login {provider.replace('_', '-')}",
            f"请运行:pico provider login {provider.replace('_', '-')}",
        ),
    }
    msg = hint_map.get(status, ui._t(f"Verification failed: {status}", f"验证失败:{status}"))
    state.console.print(
        f"  [yellow]✗ {msg}[/yellow]" + (f"  [dim]{result['error']}[/dim]" if result.get("error") else "")
    )
    return (False, status, None)


def _model_routes_to_provider(model: str, spec: Any) -> bool:
    """True if ``model`` would auto-route to ``spec`` under ``provider='auto'``."""
    if not model or not spec:
        return False
    model_lower = model.lower()
    model_normalized = model_lower.replace("-", "_")
    if "/" in model_lower:
        prefix = model_lower.split("/", 1)[0].replace("-", "_")
        return prefix == spec.name
    return any(
        (
            kw.lower() in model_lower or kw.lower().replace("-", "_") in model_normalized
            for kw in getattr(spec, "keywords", None) or ()
        )
    )


def _format_model_for_provider(spec: Any, model_id: str) -> str:
    """Apply ``spec.litellm_prefix`` to a raw ``/v1/models`` id when needed."""
    if not model_id:
        return model_id
    prefix = getattr(spec, "litellm_prefix", "") or ""
    if not prefix:
        return model_id
    if model_id.startswith(f"{prefix}/"):
        return model_id
    for skip in getattr(spec, "skip_prefixes", ()) or ():
        if model_id.startswith(skip):
            return model_id
    return f"{prefix}/{model_id}"


def _pick_model(
    spec: Any,
    *,
    current_model: Optional[str],
    model_ids: Optional[list[str]],
    user_provided_model: Optional[str],
    non_interactive: bool,
) -> str:
    """Decide the model string to write into ``agents.defaults.model``."""
    if user_provided_model:
        return user_provided_model
    if non_interactive:
        if not spec.default_model:
            raise typer.BadParameter(
                f"--model is required for provider '{spec.name}' (no built-in default model in registry)."
            )
        return spec.default_model
    questionary = ui._require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    if current_model and _model_routes_to_provider(current_model, spec):
        default_value = current_model
    else:
        default_value = spec.default_model or ""
    if model_ids:
        choices = [_format_model_for_provider(spec, mid) for mid in model_ids]
        if default_value and default_value not in choices:
            choices.insert(0, default_value)
        prompt_label = ui._t(
            f"Default model ({len(choices)} available — type to filter, Tab to complete):",
            f"默认模型(共 {len(choices)} 个 — 输入可筛选,Tab 补全):",
        )
        chosen = questionary.autocomplete(
            prompt_label,
            choices=choices,
            default=default_value,
            style=PICO_STYLE,
            qmark=state._QMARK,
            ignore_case=True,
            match_middle=True,
        ).ask()
    else:
        state.console.print(
            ui._t(
                "  [dim]Couldn't fetch the model list — enter the model id by hand.[/dim]",
                "  [dim]未能拉取模型列表,请手动输入模型 id。[/dim]",
            )
        )
        if default_value:
            chosen = questionary.text(
                ui._t(f"Default model (press Enter for [{default_value}]):", f"默认模型(回车使用 [{default_value}]):"),
                default=default_value,
                style=PICO_STYLE,
                qmark=state._QMARK,
            ).ask()
        else:
            chosen = questionary.text(
                ui._t(f"Default model id for {spec.name}:", f"{spec.name} 的默认模型 id:"),
                validate=lambda v: True if v.strip() else ui._t("Model id is required.", "必须指定模型 id。"),
                style=PICO_STYLE,
                qmark=state._QMARK,
            ).ask()
    if chosen is None:
        raise typer.Exit(1)
    chosen = chosen.strip()
    if not chosen:
        if default_value:
            return default_value
        raise typer.Exit(1)
    return chosen


def _run_test_probe(provider: str, *, non_interactive: bool, warnings: list[str], allow_repick: bool = True) -> str:
    """Run the first Runtime Turn; on failure offer recovery options.

    Returns one of ``"ok"`` / ``"continue"`` / ``"repick"`` / ``"rekey"`` /
    ``"switch"``. A test-message failure can be a wrong model, a bad key, or an
    account/balance issue, so the menu offers all the matching exits (aligning
    with the connectivity-failure menu in ``_resolve_model_with_test``);
    ``allow_repick=False`` drops the model option for custom providers whose
    model was fixed with the base_url upfront (Switch re-enters both).
    """
    state.console.print(
        ui._t(
            f'  [dim]Sending test message: "{DEFAULT_PROBE_MESSAGE}"[/dim]',
            f'  [dim]正在发送测试消息:"{DEFAULT_PROBE_MESSAGE}"[/dim]',
        )
    )
    try:
        text, tokens, elapsed = verification.run_first_turn()
    except Exception as exc:
        state.console.print(ui._t(f"  [red]✗ Test failed:[/red] {exc}", f"  [red]✗ 测试失败:[/red] {exc}"))
        state.console.print(
            ui._t(
                "  [dim]Run 'pico provider test' to re-check, or confirm the model is served by this provider.[/dim]",
                "  [dim]可运行 'pico provider test' 复查,或确认该模型确由此服务商提供。[/dim]",
            )
        )
        print_probe_troubleshooting(provider)
        options = [(ui._t("Retry", "重试"), "retry")]
        if allow_repick:
            options.append((ui._t("Re-pick model", "重新选模型"), "repick"))
        options += [
            (ui._t("Re-enter key", "重新填 Key"), "rekey"),
            (ui._t("Switch provider", "更换服务商"), "switch"),
            (ui._t("Continue anyway", "仍然继续"), "continue"),
        ]
        choice = ui._failure_choice(options, non_interactive=non_interactive)
        if choice == "retry":
            return _run_test_probe(
                provider, non_interactive=non_interactive, warnings=warnings, allow_repick=allow_repick
            )
        if choice in ("repick", "rekey", "switch"):
            return choice
        warnings.append("first Runtime Turn")
        return "continue"
    state.console.print(f"  [bold]▶ Agent:[/bold] {text}")
    extras: list[str] = []
    if tokens:
        extras.append(f"{tokens} tokens")
    extras.append(f"{elapsed:.1f}s")
    state.console.print(f"  [green]✓ {', '.join(extras)}[/green]")
    return "ok"


def _configure_one_provider(
    *,
    provider: Optional[str],
    api_key: Optional[str],
    base_url: Optional[str],
    model: Optional[str],
    non_interactive: bool,
    warnings: list[str],
    skip_test: bool = False,
) -> Optional[dict[str, Any]]:
    """Drive one provider through pick → credentials → verify → model → test.

    Returns ``{"provider", "model"}`` on success, or ``None`` if the user
    chose to go back from the interactive provider picker.
    """
    from pico.integrations.llm.providers.registry import find_by_name

    flag_provider = provider
    configured_before = set(configuration._configured_providers())
    while True:
        if flag_provider:
            provider = _validate_provider_name(flag_provider)
        else:
            if non_interactive:
                raise typer.BadParameter("--provider is required in non-interactive mode")
            picked = _select_provider()
            if picked is None:
                raise typer.Exit(1)
            if picked is state._BACK:
                return None
            provider = picked
        spec = find_by_name(provider)
        is_oauth = bool(spec and spec.is_oauth)
        is_custom = provider == "custom"
        if flag_provider:
            state.console.print(
                ui._t(
                    f"  [dim]Provider:[/dim] [#fbe23f]{_provider_label(provider)}[/#fbe23f]",
                    f"  [dim]服务商:[/dim] [#fbe23f]{_provider_label(provider)}[/#fbe23f]",
                )
            )
        _prev = (configuration._load_raw_config().get("providers") or {}).get(provider) or {}
        old_key = _prev.get("apiKey")
        old_base = _prev.get("apiBase")
        custom_model = _collect_credentials(
            provider,
            is_oauth=is_oauth,
            is_custom=is_custom,
            api_key=api_key,
            base_url=base_url,
            model=model,
            non_interactive=non_interactive,
        )
        if custom_model is state._BACK:
            flag_provider = None
            continue
        chosen_model = _resolve_model_with_test(
            spec,
            is_custom=is_custom,
            custom_model=custom_model,
            user_model_flag=model,
            non_interactive=non_interactive,
            warnings=warnings,
            skip_test=skip_test,
            defer_first_turn=True,
        )
        if chosen_model is None:
            if provider not in configured_before:
                configuration._write_provider_fields(provider, {"api_key": ""})
            elif old_key:
                configuration._write_provider_fields(provider, {"api_key": old_key, "api_base": old_base})
            flag_provider = None
            continue
        configuration._persist_default_model(chosen_model)
        return {"provider": provider, "model": chosen_model}


def _collect_credentials(
    provider: str,
    *,
    is_oauth: bool,
    is_custom: bool,
    api_key: Optional[str],
    base_url: Optional[str],
    model: Optional[str],
    non_interactive: bool,
) -> Any:
    """Auth setup: OAuth browser flow or api_key write. Returns the custom
    model id when the provider is ``custom`` (locked in here), ``None`` for a
    non-custom provider, or ``_BACK`` if the user backed out of the first
    interactive credential field (caller should rewind to the picker)."""
    if is_oauth:
        if non_interactive:
            state.console.print(
                f"[red]OAuth providers require an interactive browser flow.[/red]\nRun [#fbe23f]pico provider login {provider.replace('_', '-')}[/#fbe23f] separately, then re-run onboard."
            )
            raise typer.Exit(2)
        while True:
            if _run_oauth_login(provider):
                return None
            choice = ui._failure_choice(
                [
                    (ui._t("Retry", "重试"), "retry"),
                    (ui._t("Back (pick another provider)", "返回(改选服务商)"), "back"),
                ],
                non_interactive=non_interactive,
            )
            if choice == "retry":
                continue
            return state._BACK
    pure_interactive = not non_interactive and (not api_key) and (not is_custom or (not base_url and (not model)))
    if pure_interactive:
        prompts: list[Callable[[], Any]] = [lambda: _prompt_api_key(provider, allow_back=True)]
        if is_custom:
            prompts.append(lambda: _prompt_base_url(allow_back=True))
            prompts.append(lambda: _prompt_custom_model(allow_back=True))
        collected = ui._collect_fields(prompts)
        if collected is None:
            return state._BACK
        api_key = collected[0]
        if is_custom:
            base_url = collected[1]
            model = collected[2]
    else:
        if not api_key:
            if non_interactive:
                raise typer.BadParameter("--api-key is required in non-interactive mode")
            api_key = _prompt_api_key(provider)
        if is_custom:
            if not base_url:
                if non_interactive:
                    raise typer.BadParameter("--base-url is required when --provider=custom in non-interactive mode")
                base_url = _prompt_base_url()
            if not model:
                if non_interactive:
                    raise typer.BadParameter("--model is required when --provider=custom in non-interactive mode")
                model = _prompt_custom_model()
    fields: dict[str, Any] = {"api_key": api_key}
    custom_model: Optional[str] = None
    if is_custom:
        fields["api_base"] = base_url
        custom_model = model
    elif base_url:
        fields["api_base"] = base_url
    configuration._write_provider_fields(provider, fields)
    return custom_model


def _resolve_model_with_test(
    spec: Any,
    *,
    is_custom: bool,
    custom_model: Optional[str],
    user_model_flag: Optional[str],
    non_interactive: bool,
    warnings: list[str],
    skip_test: bool = False,
    defer_first_turn: bool = False,
) -> Optional[str]:
    """Verify credentials, pick the default model, and optionally send a test Turn.

    On a verify or test-message failure, offers a recovery submenu (retry /
    re-pick model / re-enter key / switch / continue). Custom providers are
    probed too (model was fixed upfront). Only failures stop; success
    auto-advances. Returns the chosen model, or ``None`` to signal "switch
    provider" (the caller rewinds to the picker).
    """
    while True:
        ok, status, model_ids = _verify_provider(spec.name, skip_test=skip_test)
        if not ok:
            options = (
                [(ui._t("Retry", "重试"), "retry"), (ui._t("Continue anyway", "仍然继续"), "continue")]
                if status == "network_error"
                else [
                    (ui._t("Re-enter key", "重新填 Key"), "rekey"),
                    (ui._t("Switch provider", "更换服务商"), "switch"),
                    (ui._t("Continue anyway", "仍然继续"), "continue"),
                ]
            )
            choice = ui._failure_choice(options, non_interactive=non_interactive)
            if choice == "retry":
                continue
            if choice == "rekey" and (not non_interactive):
                configuration._write_provider_fields(spec.name, {"api_key": _prompt_api_key(spec.name)})
                continue
            if choice == "switch":
                return None
            warnings.append("provider connectivity")
            model_ids = None
        break
    if is_custom:
        if custom_model is None:
            raise ValueError("Custom provider requires a model")
        configuration._persist_default_model(custom_model)
        if skip_test or defer_first_turn:
            return custom_model
        while True:
            result = _run_test_probe(spec.name, non_interactive=non_interactive, warnings=warnings, allow_repick=False)
            if result == "switch":
                return None
            if result == "rekey":
                configuration._write_provider_fields(spec.name, {"api_key": _prompt_api_key(spec.name)})
                continue
            return custom_model
    current = configuration._load_current_default_model()
    while True:
        chosen = _pick_model(
            spec,
            current_model=current,
            model_ids=model_ids,
            user_provided_model=user_model_flag,
            non_interactive=non_interactive,
        )
        configuration._persist_default_model(chosen)
        if skip_test or defer_first_turn:
            return chosen
        result = _run_test_probe(spec.name, non_interactive=non_interactive, warnings=warnings)
        if result == "switch":
            return None
        if result == "rekey":
            configuration._write_provider_fields(spec.name, {"api_key": _prompt_api_key(spec.name)})
            current = chosen
            user_model_flag = None
            continue
        if result == "repick":
            current = chosen
            user_model_flag = None
            continue
        return chosen


def _manage_existing_providers(*, non_interactive: bool) -> None:
    """Edit/remove submenu for already-configured providers (interactive only)."""
    questionary = ui._require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    while True:
        configured = configuration._configured_providers()
        if not configured:
            return
        choices = [questionary.Choice(_provider_label(n), value=n) for n in configured]
        choices.append(questionary.Choice(ui._t("Back", "返回"), value=state._BACK))
        target = questionary.select(
            ui._t("Pick a provider to manage:", "选择要管理的服务商:"),
            choices=choices,
            style=PICO_STYLE,
            qmark=state._QMARK,
        ).ask()
        if target is None or target is state._BACK:
            return
        action = questionary.select(
            ui._t(
                f"What would you like to do with {_provider_label(target)}?", f"对 {_provider_label(target)} 想做什么?"
            ),
            choices=[
                questionary.Choice(ui._t("Update API key", "更新 API Key"), value="update"),
                questionary.Choice(
                    ui._t("Remove (clear this provider's key)", "移除(清除该服务商的 Key)"), value="remove"
                ),
                questionary.Choice(ui._t("Back", "返回"), value=state._BACK),
            ],
            style=PICO_STYLE,
            qmark=state._QMARK,
        ).ask()
        if action is None or action is state._BACK:
            continue
        if action == "update":
            configuration._write_provider_fields(target, {"api_key": _prompt_api_key(target)})
            state.console.print(
                ui._t(
                    f"  [green]✓ Updated {_provider_label(target)}.[/green]",
                    f"  [green]✓ 已更新 {_provider_label(target)}。[/green]",
                )
            )
        elif action == "remove":
            current = configuration._load_current_default_model()
            from pico.integrations.llm.providers.registry import find_by_name

            spec = find_by_name(target)
            was_default_source = bool(current and spec and _model_routes_to_provider(current, spec))
            if was_default_source:
                confirm = questionary.confirm(
                    ui._t(
                        f"The current default model comes from {_provider_label(target)}; removing it means you'll need to pick a new default. Remove anyway?",
                        f"当前默认模型来自 {_provider_label(target)};移除后需要重新选择默认模型。仍要移除吗?",
                    ),
                    default=False,
                    style=PICO_STYLE,
                    qmark=state._QMARK,
                ).ask()
                if not confirm:
                    continue
            configuration._write_provider_fields(target, {"api_key": ""})
            if was_default_source:
                from pico.config.update import set_default_model

                set_default_model("")
            state.console.print(
                ui._t(
                    f"  [green]✓ Removed {_provider_label(target)}'s configuration.[/green]",
                    f"  [green]✓ 已移除 {_provider_label(target)} 的配置。[/green]",
                )
            )


def _step1_provider(
    *,
    provider: Optional[str],
    api_key: Optional[str],
    base_url: Optional[str],
    model: Optional[str],
    non_interactive: bool,
    warnings: list[str],
    skip_test: bool = False,
) -> object:
    """Step 1 screen. Returns ``_BACK`` only when the user backs out of the
    first-run picker on the welcome screen (handled by the runner)."""
    ui._step_header(1, ui._t("Choose your LLM provider", "选择 LLM 服务商"))
    state.console.print(
        ui._t(
            "  [dim]Pico's chat and reasoning are all driven by it.[/dim]", "  [dim]Pico 的对话与思考都由它驱动。[/dim]"
        )
    )
    configured = configuration._configured_providers()
    if non_interactive or not configured:
        result = _configure_one_provider(
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
            non_interactive=non_interactive,
            warnings=warnings,
            skip_test=skip_test,
        )
        if result is None:
            return state._BACK
        return None
    questionary = ui._require_questionary()
    from pico.interfaces.cli.rendering.styles import PICO_STYLE

    while True:
        names = ", ".join((_provider_label(n).split(" (")[0] for n in configuration._configured_providers()))
        action = questionary.select(
            ui._t(
                f"LLM provider already configured: {names}. What would you like to do?",
                f"LLM 服务商已配置:{names}。想做什么?",
            ),
            choices=[
                questionary.Choice(ui._t("Done, continue", "完成,继续"), value="done"),
                questionary.Choice(ui._t("Add another provider", "新增一个服务商"), value="add"),
                questionary.Choice(ui._t("Edit / remove a provider", "编辑 / 移除服务商"), value="edit"),
            ],
            style=PICO_STYLE,
            qmark=state._QMARK,
        ).ask()
        if action is None:
            raise typer.Exit(1)
        if action == "done":
            if not (configuration._configured_providers() and configuration._load_current_default_model()):
                state.console.print(
                    ui._t(
                        "  [yellow]At least one provider with a default model is required — add or re-pick one.[/yellow]",
                        "  [yellow]至少需要一个带默认模型的服务商 — 请新增或重新选择一个。[/yellow]",
                    )
                )
                continue
            return None
        if action == "add":
            _configure_one_provider(
                provider=None,
                api_key=None,
                base_url=None,
                model=None,
                non_interactive=False,
                warnings=warnings,
                skip_test=skip_test,
            )
        elif action == "edit":
            _manage_existing_providers(non_interactive=non_interactive)

"""Contracts for the public surface of the layered `pico` package.

The root package deliberately exposes almost nothing; every stable entry point is reached
through the module that owns it. These cases pin both halves of that contract: the small root
surface, and the absence of the flat pre-layering module names.
"""

import importlib
import importlib.util
from pathlib import Path

import pico

#: Stable entries as ``module path`` / ``attribute`` pairs; each must resolve where it lives.
_STABLE_ENTRIES: list[tuple[str, str]] = [
    ("pico.runtime.agent.agent", "Pico"),
    ("pico.runtime.agent.loop", "AgentLoop"),
    ("pico.runtime.agent.checkpoints", "evaluate_resume_state"),
    ("pico.runtime.agent.prompts", "parse"),
    ("pico.runtime.context.assembler", "ContextAssembler"),
    ("pico.runtime.context.instructions", "build_prompt_prefix"),
    ("pico.runtime.sessions.service", "SessionStore"),
    ("pico.runtime.workspace.snapshot", "WorkspaceContext"),
    ("pico.capabilities.tools.registry", "build_tool_registry"),
    ("pico.capabilities.tools.builtin", "TOOL_DEFINITIONS"),
    ("pico.capabilities.tools.contracts", "ToolContext"),
    ("pico.capabilities.tools.contracts", "ToolResult"),
    ("pico.capabilities.tools.executor", "ToolExecutor"),
    ("pico.capabilities.memory.contracts", "default_memory_state"),
    ("pico.capabilities.memory.state", "append_note"),
    ("pico.capabilities.memory.durable", "DurableMemoryStore"),
    ("pico.capabilities.memory.service", "LayeredMemory"),
    ("pico.capabilities.memory.workspace_paths", "canonicalize_path"),
    ("pico.contracts.turns", "TaskState"),
    ("pico.observability.runs.store", "RunStore"),
    ("pico.observability.runs.report", "build_report"),
    ("pico.security.redaction", "redact_text"),
    ("pico.security.authorization.approval", "evaluate_approval"),
    ("pico.security.authorization.shell_environment", "filter_shell_env"),
    ("pico.security.authorization.workspace_paths", "resolve_within_root"),
    ("pico.integrations.llm.providers.fake", "FakeModelClient"),
    ("pico.config.loader", "load_project_env"),
    ("pico.config.providers", "provider_profile"),
    ("pico.bootstrap.container", "build_runtime"),
    ("pico.interfaces.cli.app", "build_arg_parser"),
    ("pico.interfaces.cli.app", "main"),
    ("pico.interfaces.cli.rendering.styles", "build_welcome"),
    ("pico.extensions.evaluation.engine", "BenchmarkEvaluator"),
    ("pico.extensions.evaluation.benchmark", "load_benchmark"),
    ("pico.extensions.evaluation.metrics.aggregates", "aggregate_benchmark_artifact"),
]

#: Flat module names retired by the layering; none may survive as a shim.
_RETIRED_MODULES: tuple[str, ...] = (
    "pico.agent_loop",
    "pico.checkpoint",
    "pico.cli",
    "pico.context_manager",
    "pico.evaluation",
    "pico.evaluator",
    "pico.features",
    "pico.memory",
    "pico.metrics",
    "pico.models",
    "pico.prompt_prefix",
    "pico.providers",
    "pico.run_store",
    "pico.session_store",
    "pico.task_state",
    "pico.tool_context",
    "pico.tool_executor",
    "pico.tools",
    "pico.workspace",
)


def test_root_package_exports_current_names_only() -> None:
    """The root package publishes product identity and nothing that belongs to a layer."""
    assert pico.PRODUCT_NAME
    assert pico.__version__
    assert pico.__all__ == ["PRODUCT_NAME", "__version__"]
    for retired_name in ("Pico", "SessionStore", "WorkspaceContext", "build_agent", "MiniAgent", "main"):
        assert not hasattr(pico, retired_name)
        assert retired_name not in pico.__all__


def test_build_runtime_returns_pico(tmp_path: Path) -> None:
    """The composition root assembles a runnable facade from a workspace directory."""
    from pico.bootstrap.container import build_runtime
    from pico.runtime.agent.agent import Pico

    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")

    agent = build_runtime(cwd=tmp_path, approval_policy="auto")

    assert isinstance(agent, Pico)
    assert agent.tools


def test_stable_entries_import_from_owning_modules() -> None:
    """Every stable symbol is reachable from the layered module that owns it."""
    missing = [
        f"{module_path}.{attribute}"
        for module_path, attribute in _STABLE_ENTRIES
        if not hasattr(importlib.import_module(module_path), attribute)
    ]

    assert missing == []


def test_layered_package_split_uses_package_paths_without_legacy_shims() -> None:
    """No retired flat module survives, either as a source file or as an importable shim."""
    retired_files = (
        "agent_loop.py",
        "checkpoint.py",
        "cli.py",
        "context_manager.py",
        "evaluator.py",
        "metrics.py",
        "models.py",
        "memory.py",
        "prompt_prefix.py",
        "run_store.py",
        "session_store.py",
        "task_state.py",
        "tool_context.py",
        "tool_executor.py",
        "tools.py",
        "workspace.py",
    )
    source_root = Path("src/pico")
    assert all(not (source_root / name).exists() for name in retired_files)
    assert not (source_root / "evaluation").exists()
    assert not (source_root / "features").exists()
    assert not (source_root / "providers").exists()

    shadowed = [name for name in _RETIRED_MODULES if importlib.util.find_spec(name) is not None]
    assert shadowed == []


def test_packaging_discovers_src_layout() -> None:
    """The wheel targets the layered package under `src` and the console script points at the CLI app."""
    pyproject_text = Path("pyproject.toml").read_text(encoding="utf-8")

    assert 'pico = "pico.interfaces.cli.app:main"' in pyproject_text
    assert 'packages = ["src/pico"]' in pyproject_text

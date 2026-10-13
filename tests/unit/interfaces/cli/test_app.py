"""Tests for pico.interfaces.cli.app: parser surface, entrypoints and module execution.

The CLI entry owns argument parsing and the installed `pico` command. Assembly itself moved to
`pico.bootstrap.container.build_runtime` (the old `pico.cli.build_agent`), so the entrypoint
checks below name that function instead.
"""

import subprocess
import sys
from pathlib import Path

import pico
from pico.bootstrap.container import build_runtime
from pico.integrations.llm.providers.fake import FakeModelClient
from pico.integrations.llm.providers.ollama import OllamaModelClient
from pico.interfaces.cli.app import build_arg_parser, main
from pico.interfaces.cli.rendering.styles import build_welcome
from pico.runtime.agent.agent import Pico
from pico.runtime.sessions.service import SessionStore
from pico.runtime.workspace.snapshot import WorkspaceContext


def test_build_arg_parser_leaves_provider_unset_for_runtime_resolution(tmp_path: Path) -> None:
    """No `--provider` on the command line means resolution stays deferred to configuration."""
    args = build_arg_parser().parse_args(["--cwd", str(tmp_path)])

    assert args.provider is None


def test_build_arg_parser_accepts_anthropic_provider(tmp_path: Path) -> None:
    """`anthropic` is an accepted provider choice."""
    args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "--provider", "anthropic"])

    assert args.provider == "anthropic"


def test_build_arg_parser_accepts_deepseek_provider(tmp_path: Path) -> None:
    """`deepseek` is an accepted provider choice."""
    args = build_arg_parser().parse_args(["--cwd", str(tmp_path), "--provider", "deepseek"])

    assert args.provider == "deepseek"


def test_public_api_exports_resolve_through_package_path() -> None:
    """The symbols the CLI surface depends on import cleanly and the package file stays addressable."""
    assert callable(build_welcome)
    assert FakeModelClient is not None
    assert Pico is not None
    assert OllamaModelClient is not None
    assert SessionStore is not None
    assert WorkspaceContext is not None
    assert Path(pico.__file__).as_posix().endswith("/pico/__init__.py")


def test_package_import_surface_includes_cli_entrypoints() -> None:
    """The entrypoint callables exist at their layered homes; `pico.cli.build_agent` is now `build_runtime`."""
    assert callable(main)
    assert callable(build_arg_parser)
    assert callable(build_runtime)


def test_module_execution_help_works() -> None:
    """Running `python -m pico --help` prints usage and exits successfully."""
    result = subprocess.run(
        [sys.executable, "-m", "pico", "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "usage:" in result.stdout.lower()
